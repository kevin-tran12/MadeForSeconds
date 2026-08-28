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

import argparse
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
    """Enough of the real client's surface for _cleanup_and_verify_healthy and
    the run()-level orchestration tests below: list/add/destroy/enable/access
    against a single in-memory version list, mutated in place so every call
    sees the effect of prior ones — same observable behavior as the real API,
    and shared between "operator_client" and "pruner_client" in these tests
    (both are just this one fake, matching how they hit the same underlying
    secret in reality)."""

    def __init__(self, versions, project: str = "test-project", secret_id: str = "secret-pruner-canary"):
        self._versions = list(versions)
        self._payloads: dict[str, bytes] = {}  # version name -> raw bytes; SecretVersion itself has no payload field
        self._project = project
        self._secret_id = secret_id
        self.destroy_calls: list[str] = []
        self.add_calls = 0
        self.enable_calls: list[str] = []
        self.access_calls: list[str] = []

        # Failure injection, all one-shot (fails exactly once, then behaves
        # normally) unless noted — simulates a transient failure partway
        # through a run that a later retry (this test's own, or cleanup's
        # separate _destroy_with_retry) can still recover from.
        self.fail_add_after: int | None = None  # raise once add_calls exceeds this count
        self.fail_destroy_for: set[str] = set()  # always fails for these names (matches original semantics)
        self.fail_destroy_once_for: set[str] = set()
        self.fail_enable_once_for: set[str] = set()
        self.fail_access_once_for: set[str] = set()

    def secret_path(self, project, secret_id):
        return f"projects/{project}/secrets/{secret_id}"

    def list_secret_versions(self, parent):
        return list(self._versions)

    def add_secret_version(self, request):
        self.add_calls += 1
        if self.fail_add_after is not None and self.add_calls > self.fail_add_after:
            raise RuntimeError(f"simulated add failure on call {self.add_calls}")
        from google.cloud.secretmanager_v1.types import SecretVersion

        number = max((_version_number_from_name(v.name) for v in self._versions), default=0) + 1
        v = SecretVersion()
        v.name = f"projects/{self._project}/secrets/{self._secret_id}/versions/{number}"
        v.state = SecretVersion.State.ENABLED
        v.etag = f"etag-{number}"
        self._payloads[v.name] = request.payload.data
        self._versions.append(v)
        return v

    def destroy_secret_version(self, name=None, request=None):
        from google.api_core.exceptions import FailedPrecondition

        target_name = name or request.name
        if target_name in self.fail_destroy_for:
            raise FailedPrecondition("simulated destroy failure")
        if target_name in self.fail_destroy_once_for:
            self.fail_destroy_once_for.discard(target_name)
            raise FailedPrecondition("simulated transient destroy failure")
        self.destroy_calls.append(target_name)
        for v in self._versions:
            if v.name == target_name:
                v.state = type(v.state).DISABLED
                v.scheduled_destroy_time = datetime.datetime.now(datetime.timezone.utc)

    def enable_secret_version(self, name=None, request=None):
        target_name = name or request.name
        if target_name in self.fail_enable_once_for:
            self.fail_enable_once_for.discard(target_name)
            raise RuntimeError("simulated transient enable failure")
        self.enable_calls.append(target_name)
        for v in self._versions:
            if v.name == target_name:
                v.state = type(v.state).ENABLED
                v.scheduled_destroy_time = None

    def access_secret_version(self, name=None, request=None):
        target_name = name or request.name
        if target_name in self.fail_access_once_for:
            self.fail_access_once_for.discard(target_name)
            raise RuntimeError("simulated transient access failure")
        self.access_calls.append(target_name)
        payload_bytes = self._payloads[target_name]

        class _Payload:
            data = payload_bytes

        class _Resp:
            payload = _Payload

        return _Resp()


def _version_number_from_name(name: str) -> int:
    return int(name.rsplit("/", 1)[-1])


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


# ─── _write_enabled_env_flag: gcloud's comma-in-dict-value escaping ─────────


def test_single_secret_value_uses_the_alternate_delimiter(smoke):
    flag = smoke._write_enabled_env_flag("admin-emails")
    assert flag == "--update-env-vars=^:^WRITE_ENABLED_SECRET_IDS=admin-emails"


def test_multi_secret_value_is_preserved_byte_for_byte_not_split_on_comma(smoke):
    """The regression this exists for: --update-env-vars is itself a
    comma-separated KEY=VALUE dict flag, and WRITE_ENABLED_SECRET_IDS's value
    is *also* comma-separated. Without the ^:^ alternate-delimiter prefix,
    gcloud would parse "admin-emails,instagram-access-token" as two dict
    entries — the second has no "=" and fails to parse, or worse silently
    drops half the allowlist."""
    value = "admin-emails,instagram-access-token,stripe-secret-key"
    flag = smoke._write_enabled_env_flag(value)
    assert flag == f"--update-env-vars=^:^WRITE_ENABLED_SECRET_IDS={value}"
    # The full original value must appear verbatim after the final "=" —
    # not truncated at the first comma, not re-ordered, not re-escaped.
    assert flag.endswith(f"WRITE_ENABLED_SECRET_IDS={value}")


def test_empty_value_still_uses_the_delimiter_form_for_consistency(smoke):
    """No special-casing by content — ^:^ is harmless even with zero commas,
    so every call site can use it unconditionally."""
    assert smoke._write_enabled_env_flag("") == "--update-env-vars=^:^WRITE_ENABLED_SECRET_IDS="


def test_set_write_enabled_env_passes_a_multi_secret_value_through_unchanged(smoke, monkeypatch):
    """One level up from _write_enabled_env_flag: proves the value that
    reaches the actual gcloud invocation for a multi-secret allowlist is
    byte-for-byte what was asked for, not truncated or re-split on comma."""
    captured = {}
    monkeypatch.setattr(smoke, "_run_gcloud_checked", lambda argv, **kw: captured.update(argv=argv) or "")

    value = "admin-emails,instagram-access-token,stripe-secret-key"
    smoke._set_write_enabled_env("made-for-seconds", "us-central1", "secret-pruner", value)

    matching = [a for a in captured["argv"] if a.startswith("--update-env-vars=")]
    assert matching == [f"--update-env-vars=^:^WRITE_ENABLED_SECRET_IDS={value}"]


def test_revert_remediation_message_uses_the_same_safe_encoding(smoke, monkeypatch):
    """The exact bug reported: the printed fix-it command inside
    _test_real_write_path's revert-failure path must not repeat the broken
    plain-comma encoding — it has to be gcloud-runnable as printed.

    Drives the real function: the try body fails naturally (operator_client
    is a bare object() with none of the real client's methods, so it raises
    AttributeError the moment the function tries to use it) right after the
    flip is confirmed, and the post-revert describe call is rigged to report
    a value that still doesn't match the original — forcing the exact
    revert-failure branch this remediation message lives in.
    """
    original_value = "admin-emails,instagram-access-token"
    responses = iter([
        original_value,          # 1st call: read the current (original) value
        smoke.CANARY_SECRET_ID,  # 2nd call: confirm the flip took effect
        "something-still-wrong",  # 3rd call: confirm the revert -- deliberately wrong
    ])
    monkeypatch.setattr(smoke, "_get_write_enabled_env", lambda *a: next(responses))
    monkeypatch.setattr(smoke, "_set_write_enabled_env", lambda *a: None)

    args = argparse.Namespace(project="made-for-seconds", region="us-central1", function_name="secret-pruner")

    with pytest.raises(smoke.SmokeTestFailure) as exc_info:
        smoke._test_real_write_path(args, object(), object(), object(), "https://example.invalid", "projects/p/secrets/secret-pruner-canary")

    assert "^:^WRITE_ENABLED_SECRET_IDS=admin-emails,instagram-access-token" in str(exc_info.value)


# ─── Scheduler completion, not just dispatch ────────────────────────────────


class _FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def test_find_attempt_finished_log_parses_a_successful_entry(smoke, monkeypatch):
    """Real shape observed in this project's own logs: a successful
    AttemptFinished has severity INFO and no jsonPayload.status at all."""
    monkeypatch.setattr(smoke, "_run_gcloud_checked", lambda argv, **kw: '[{"severity": "INFO", "jsonPayload": {}}]')
    entry = smoke._find_attempt_finished_log("p", "secret-version-pruner", "2026-08-28T00:00:00Z")
    assert entry["severity"] == "INFO"
    assert "status" not in entry["jsonPayload"]


def test_find_attempt_finished_log_parses_a_failed_entry(smoke, monkeypatch):
    """Real shape observed in this project's own logs (weekly-usage-report's
    actual failing attempts): severity ERROR, jsonPayload.status set to a
    google.rpc.Code name."""
    monkeypatch.setattr(smoke, "_run_gcloud_checked", lambda argv, **kw: '[{"severity": "ERROR", "jsonPayload": {"status": "INTERNAL", "debugInfo": "URL_UNREACHABLE-UNREACHABLE_5xx"}}]')
    entry = smoke._find_attempt_finished_log("p", "secret-version-pruner", "2026-08-28T00:00:00Z")
    assert entry["severity"] == "ERROR"
    assert entry["jsonPayload"]["status"] == "INTERNAL"


def test_find_attempt_finished_log_returns_none_when_nothing_landed_yet(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "_run_gcloud_checked", lambda argv, **kw: "[]")
    assert smoke._find_attempt_finished_log("p", "secret-version-pruner", "2026-08-28T00:00:00Z") is None


def test_find_attempt_finished_log_filters_by_job_id_and_since_time(smoke, monkeypatch):
    captured = {}

    def _fake(argv, **kw):
        captured["argv"] = argv
        return "[]"

    monkeypatch.setattr(smoke, "_run_gcloud_checked", _fake)
    smoke._find_attempt_finished_log("made-for-seconds", "secret-version-pruner", "2026-08-28T12:00:00+00:00")

    filter_arg = captured["argv"][2]  # ["logging", "read", <filter>, ...]
    assert 'resource.labels.job_id="secret-version-pruner"' in filter_arg
    assert 'timestamp>="2026-08-28T12:00:00+00:00"' in filter_arg
    assert "AttemptFinished" in filter_arg


def test_wait_for_scheduler_attempt_succeeds_once_a_successful_entry_appears(smoke, monkeypatch):
    clock = _FakeClock()
    results = iter([None, None, {"severity": "INFO", "jsonPayload": {}}])
    monkeypatch.setattr(smoke, "_find_attempt_finished_log", lambda *a: next(results))

    smoke._wait_for_scheduler_attempt("p", "r", "job", "2026-08-28T00:00:00Z", sleep=clock.sleep, now=clock.now)

    assert len(clock.sleeps) == 2  # polled twice before the entry landed


def test_wait_for_scheduler_attempt_raises_when_the_attempt_failed(smoke, monkeypatch):
    """A successful `jobs run` dispatch only forces the attempt — it says
    nothing about whether the HTTP target actually succeeded. This is the
    exact case that must not read as a pass."""
    clock = _FakeClock()
    monkeypatch.setattr(smoke, "_find_attempt_finished_log", lambda *a: {"severity": "ERROR", "jsonPayload": {"status": "INTERNAL", "debugInfo": "boom"}})

    with pytest.raises(smoke.SmokeTestFailure, match="INTERNAL"):
        smoke._wait_for_scheduler_attempt("p", "r", "job", "2026-08-28T00:00:00Z", sleep=clock.sleep, now=clock.now)


def test_wait_for_scheduler_attempt_treats_a_status_field_as_failure_even_with_info_severity(smoke, monkeypatch):
    """Belt and suspenders: jsonPayload.status being present at all (not just
    severity) is also treated as failure, since that field's mere presence
    is what the real API uses to distinguish success from failure."""
    clock = _FakeClock()
    monkeypatch.setattr(smoke, "_find_attempt_finished_log", lambda *a: {"severity": "INFO", "jsonPayload": {"status": "INTERNAL"}})

    with pytest.raises(smoke.SmokeTestFailure):
        smoke._wait_for_scheduler_attempt("p", "r", "job", "2026-08-28T00:00:00Z", sleep=clock.sleep, now=clock.now)


def test_wait_for_scheduler_attempt_times_out_if_no_entry_appears(smoke, monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(smoke, "_find_attempt_finished_log", lambda *a: None)  # never appears
    with pytest.raises(smoke.SmokeTestFailure, match="no AttemptFinished"):
        smoke._wait_for_scheduler_attempt(
            "p", "r", "job", "2026-08-28T00:00:00Z",
            deadline_seconds=10.0, poll_interval=3.0, sleep=clock.sleep, now=clock.now,
        )
    assert clock.t >= 10.0


def test_wait_for_scheduler_attempt_does_not_stop_early_just_because_time_advanced(smoke, monkeypatch):
    """The exact regression this whole rewrite exists for: a naive
    "lastAttemptTime changed" check would pass the instant an attempt
    *starts*, before its outcome (status) is known. This double-checks that
    the new implementation keeps polling — never returning early — for as
    long as no AttemptFinished entry has actually landed, regardless of how
    much wall-clock time passes."""
    clock = _FakeClock()
    call_count = {"n": 0}

    def _still_nothing(*a):
        call_count["n"] += 1
        return None

    monkeypatch.setattr(smoke, "_find_attempt_finished_log", _still_nothing)
    with pytest.raises(smoke.SmokeTestFailure):
        smoke._wait_for_scheduler_attempt("p", "r", "job", "2026-08-28T00:00:00Z", deadline_seconds=15.0, poll_interval=5.0, sleep=clock.sleep, now=clock.now)
    assert call_count["n"] >= 3  # kept checking across the whole deadline, never assumed success early


# ─── _check_response_is_clean ────────────────────────────────────────────────


def test_response_with_an_anomaly_on_any_secret_is_rejected(smoke):
    with pytest.raises(smoke.SmokeTestFailure):
        smoke._check_response_is_clean({"secret-pruner-canary": {"dry_run_would_destroy": []}, "admin-emails": {"anomaly": "latest version 6 is DISABLED"}})


def test_response_with_an_error_on_any_secret_is_rejected(smoke):
    with pytest.raises(smoke.SmokeTestFailure):
        smoke._check_response_is_clean({"secret-pruner-canary": {"dry_run_would_destroy": []}, "redis-url": {"error": "boom"}})


def test_clean_response_passes(smoke):
    smoke._check_response_is_clean({"secret-pruner-canary": {"dry_run_would_destroy": [1]}, "admin-emails": {"dry_run_would_destroy": []}})  # must not raise


# ─── run(): cleanup is guaranteed after a partial mutation, at every point ──
#
# Reproduces the exact regression: a failure after some (but not all) of
# Part B's mutating calls used to leave run()'s local added_versions empty,
# because _test_destroy_recovery_cycle only handed its mutation record back
# via a normal return — one an exception skips. Cleanup is now unconditional
# in run()'s finally and re-derives ground truth from a fresh listing, so
# these tests drive a real failure through run() at each of add/destroy/
# restore/verify and confirm the canary is still left healthy afterward,
# regardless of exactly how far Part B got.


@pytest.fixture
def orchestration(smoke, pruner_main, monkeypatch):
    """Wires run() up to a single shared fake Secret Manager client and stubs
    every other live-network dependency (impersonation, the deployed
    function's HTTP endpoint, gcloud) so only Part B's real logic — the
    thing this regression is about — actually executes."""
    import google.auth
    from google.auth import impersonated_credentials

    client = _FakeSecretManagerClient([_version(2, "ENABLED"), _version(1, "ENABLED")])

    monkeypatch.setattr(google.auth, "default", lambda: (object(), "test-project"))
    monkeypatch.setattr(impersonated_credentials, "Credentials", lambda **kw: object())
    monkeypatch.setattr(smoke.secretmanager, "SecretManagerServiceClient", lambda **kw: client)
    monkeypatch.setattr(smoke, "_get_function_url", lambda *a: "https://example.invalid/secret-pruner")
    monkeypatch.setattr(smoke, "_test_authenticated_boundary", lambda *a: None)  # real HTTP/gcloud — out of scope here

    return client


def _run_args(**overrides):
    defaults = dict(project="test-project", region="us-central1", function_name="secret-pruner", scheduler_job_name="secret-version-pruner", pruner_sa_email=None, test_write_path=False)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _assert_canary_left_healthy(pruner_main, client):
    """Two checks, not one: "no anomaly" alone is too weak to prove cleanup
    actually ran — orphaned extra versions sitting around aren't "anomalous"
    by plan_destructions' own definition (that only means "latest version
    disabled"), so a version-count check is what actually catches cleanup
    having been skipped entirely. Confirmed by deliberately reintroducing the
    original added_versions-gating bug and observing these tests still pass
    on anomaly alone but fail once this count check is added."""
    versions = [pruner_main._version_info(v) for v in client.list_secret_versions(parent=None)]
    enabled = [v for v in versions if v["state"] == "ENABLED"]
    _, anomaly = pruner_main.plan_destructions(versions)
    assert anomaly is None, f"canary left anomalous after run(): {anomaly}"
    assert len(enabled) <= 2, f"cleanup did not converge back to <=2 enabled versions (found {len(enabled)}): {enabled}"


def test_cleanup_runs_when_a_failure_happens_mid_add(orchestration, pruner_main, smoke):
    orchestration.fail_add_after = 2  # "a" and "b" succeed, "c" fails

    result = smoke.run(_run_args())

    assert result == 1
    _assert_canary_left_healthy(pruner_main, orchestration)


def test_cleanup_runs_when_the_direct_destroy_call_fails(orchestration, pruner_main, smoke):
    # The target is always the oldest of the three newly-added versions —
    # predict its name from the pre-seeded state (2 existing) + 1st add.
    target_name = "projects/test-project/secrets/secret-pruner-canary/versions/3"
    orchestration.fail_destroy_once_for = {target_name}

    result = smoke.run(_run_args())

    assert result == 1
    _assert_canary_left_healthy(pruner_main, orchestration)


def test_cleanup_runs_when_the_restore_call_fails(orchestration, pruner_main, smoke):
    target_name = "projects/test-project/secrets/secret-pruner-canary/versions/3"
    orchestration.fail_enable_once_for = {target_name}

    result = smoke.run(_run_args())

    assert result == 1
    _assert_canary_left_healthy(pruner_main, orchestration)


def test_cleanup_runs_when_the_post_restore_verification_fails(orchestration, pruner_main, smoke):
    target_name = "projects/test-project/secrets/secret-pruner-canary/versions/3"
    orchestration.fail_access_once_for = {target_name}

    result = smoke.run(_run_args())

    assert result == 1
    _assert_canary_left_healthy(pruner_main, orchestration)


def test_a_fully_successful_run_also_leaves_the_canary_healthy(orchestration, pruner_main, smoke):
    """Control case — no injected failure at all."""
    result = smoke.run(_run_args())

    assert result == 0
    _assert_canary_left_healthy(pruner_main, orchestration)
