"""Unit tests for scripts/smoke_test_receipt_role.py's retry helper.

wait_until() is the piece that waits out Cloud Storage's eventually-consistent
IAM propagation before the live script exercises a newly bound role — these
tests prove its retry/backoff/deadline behavior in isolation, with fake
sleep/now so no real time passes and no GCP call is made. The rest of that
script talks to real Cloud Storage and is exercised by actually running it
(see its own docstring), not by unit tests.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from google.api_core.exceptions import NotFound  # noqa: E402

from smoke_test_receipt_role import _delete_bucket_with_verification, wait_until  # noqa: E402


class _FakeClock:
    """now() advances only when sleep() is called, by exactly the requested amount."""

    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def test_succeeds_immediately_without_sleeping():
    clock = _FakeClock()
    attempts = wait_until(lambda: True, sleep=clock.sleep, now=clock.now)
    assert attempts == 1
    assert clock.sleeps == []


def test_retries_transient_denial_then_succeeds():
    """Injects two initial denials, then success on the third attempt."""
    results = iter([False, False, True])
    clock = _FakeClock()
    attempts = wait_until(lambda: next(results), sleep=clock.sleep, now=clock.now)
    assert attempts == 3
    assert len(clock.sleeps) == 2  # slept between attempts 1->2 and 2->3, not after success


def test_backoff_grows_between_retries():
    results = iter([False, False, False, True])
    clock = _FakeClock()
    wait_until(lambda: next(results), initial_delay=1.0, max_delay=100.0, sleep=clock.sleep, now=clock.now)
    # Each delay (before jitter) should be roughly double the last, and jitter
    # only adds up to 25% on top -- so delay[1] must exceed delay[0] alone,
    # not just by rounding noise.
    assert clock.sleeps[1] > clock.sleeps[0] * 1.5
    assert clock.sleeps[2] > clock.sleeps[1] * 1.5


def test_backoff_capped_at_max_delay():
    results = iter([False] * 10 + [True])
    clock = _FakeClock()
    wait_until(lambda: next(results), initial_delay=1.0, max_delay=5.0, sleep=clock.sleep, now=clock.now)
    # With jitter up to 25%, no single sleep should exceed max_delay * 1.25.
    assert all(s <= 5.0 * 1.25 for s in clock.sleeps)


def test_persistent_denial_raises_timeout_and_does_not_hang():
    """A check() that never returns True must raise, not loop forever."""
    clock = _FakeClock()
    with pytest.raises(TimeoutError):
        wait_until(lambda: False, deadline_seconds=30.0, initial_delay=1.0, sleep=clock.sleep, now=clock.now)
    # The fake clock only advances via sleep(), so reaching (approximately)
    # the deadline proves retries actually happened rather than failing on
    # the first check. Not an exact `>= 30.0` -- the last sleep is capped to
    # the remaining time, which can land a hair under 30 depending on the
    # backoff schedule's last step size.
    assert clock.t >= 29.9
    assert len(clock.sleeps) >= 2


def test_slow_probe_returning_true_after_the_deadline_is_rejected():
    """check() itself can be a slow network call, not an instant operation --
    a call that starts before the deadline but doesn't return until after it
    must not be accepted just because it eventually said True.

    Reproduces the exact scenario reported: a 10s deadline, a probe that
    (by the time it completes) has pushed the clock to 11s and returns True.
    """
    clock = _FakeClock()

    def slow_probe_that_succeeds() -> bool:
        clock.t += 11.0  # simulates the probe call itself taking 11s
        return True

    with pytest.raises(TimeoutError):
        wait_until(slow_probe_that_succeeds, deadline_seconds=10.0, sleep=clock.sleep, now=clock.now)


def test_success_observed_only_after_deadline_is_rejected():
    """A check() that would eventually return True, but not soon enough,
    must still raise TimeoutError -- not be accepted late.

    Rigged so the true condition is only reachable on the 100th call; the
    tight deadline/backoff below burns through far fewer attempts than that
    before giving up, so if this test ever sees a clean return instead of
    TimeoutError, the deadline stopped being enforced.
    """
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        return calls["n"] >= 100

    clock = _FakeClock()
    with pytest.raises(TimeoutError):
        wait_until(check, deadline_seconds=10.0, initial_delay=1.0, max_delay=2.0, sleep=clock.sleep, now=clock.now)
    assert calls["n"] < 100


def test_total_sleep_never_exceeds_configured_deadline():
    """Each sleep must be capped to the remaining budget, not the full
    jittered backoff step -- otherwise the command can run well past
    --propagation-timeout before finally giving up."""
    clock = _FakeClock()
    with pytest.raises(TimeoutError):
        wait_until(lambda: False, deadline_seconds=17.0, initial_delay=1.0, max_delay=10.0, sleep=clock.sleep, now=clock.now)
    assert sum(clock.sleeps) <= 17.0 + 1e-6
    assert clock.t <= 17.0 + 1e-6


def test_unexpected_exception_propagates_without_retry():
    """check() raising something other than returning False must not be swallowed."""
    def _boom():
        raise ValueError("not a permission problem")

    clock = _FakeClock()
    with pytest.raises(ValueError):
        wait_until(_boom, sleep=clock.sleep, now=clock.now)
    assert clock.sleeps == []


# ── _delete_bucket_with_verification: ambiguous bucket-creation cleanup ──────
#
# In run(), bucket_created is set True *before* calling create_bucket() --
# if that call raises after the server actually created the bucket (response
# lost, client retries exhausted), cleanup must still find and remove it
# rather than skipping it because the create call "failed". These tests
# cover both outcomes that unconditional cleanup can encounter: the bucket
# genuinely exists (server-side creation succeeded despite the client-side
# error), and it genuinely never existed (creation truly failed).

class _FakeBucketHandle:
    def __init__(self, existed: bool, delete_raises: Exception | None = None):
        self._existed = existed
        self._delete_raises = delete_raises

    def delete(self, force=True):
        if self._delete_raises is not None:
            raise self._delete_raises
        self._existed = False

    def exists(self):
        return self._existed


class _FakeStorageClient:
    def __init__(self, bucket_handle: _FakeBucketHandle):
        self._handle = bucket_handle

    def bucket(self, name):
        return self._handle


def test_cleanup_removes_a_bucket_the_server_actually_created():
    """Simulates create_bucket() having raised even though the bucket exists
    server-side -- cleanup must still find and delete it."""
    client = _FakeStorageClient(_FakeBucketHandle(existed=True))
    assert _delete_bucket_with_verification(client, "whatever-bucket") is True
    assert client.bucket("whatever-bucket").exists() is False


def test_cleanup_is_a_safe_noop_when_bucket_never_existed():
    """Simulates create_bucket() having genuinely failed -- delete() on a
    bucket that was never created raises NotFound in the real API; that
    must count as successful cleanup, not an error."""
    client = _FakeStorageClient(_FakeBucketHandle(existed=False, delete_raises=NotFound("no such bucket")))
    assert _delete_bucket_with_verification(client, "whatever-bucket") is True


def test_cleanup_reports_failure_when_bucket_persists():
    """A bucket that still exists after every delete attempt must not be
    reported as cleaned up -- this is what makes the script exit non-zero
    even when every functional check passed."""
    handle = _FakeBucketHandle(existed=True, delete_raises=RuntimeError("transient API error"))
    client = _FakeStorageClient(handle)
    assert _delete_bucket_with_verification(client, "whatever-bucket", attempts=1) is False
