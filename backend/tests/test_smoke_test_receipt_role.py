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

from smoke_test_receipt_role import wait_until  # noqa: E402


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
    # The fake clock only advances via sleep(), so reaching the deadline at
    # all proves retries actually happened rather than failing on the first
    # check.
    assert clock.t >= 30.0
    assert len(clock.sleeps) >= 2


def test_unexpected_exception_propagates_without_retry():
    """check() raising something other than returning False must not be swallowed."""
    def _boom():
        raise ValueError("not a permission problem")

    clock = _FakeClock()
    with pytest.raises(ValueError):
        wait_until(_boom, sleep=clock.sleep, now=clock.now)
    assert clock.sleeps == []
