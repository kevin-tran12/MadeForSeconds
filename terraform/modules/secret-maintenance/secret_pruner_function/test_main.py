"""Tests for the Secret Manager version pruner.

This function's whole job is to decide what is safe to permanently destroy,
so the properties pinned here are the ones that lose data or leave a secret
unusable if they regress:

  - the newest ENABLED version and its ENABLED predecessor are never destroyed
  - a DISABLED version numerically newer than the protected pair still
    protects everything at or above it — it does not make older versions
    "more prunable"
  - a secret whose latest version is not ENABLED is skipped entirely, not
    guessed at
  - a version already scheduled for delayed destruction is never selected
    again — a retry or next week's run must not re-issue destroy on it
  - nothing is actually destroyed unless the secret is in the write-enabled
    allowlist
  - one secret's failure (missing secret, a destroy conflict) never stops the
    others from being processed, but never fails silently either — any
    failure at all surfaces as a non-2xx response

Standing caveat, same as billing_function/test_main.py: these tests mock the
Secret Manager client, so they verify our selection logic and orchestration,
not GCP-side IAM or quota behavior. A green suite here is necessary, not
sufficient — the manual dry-run-then-canary-drill sequence in
docs/DEPLOYMENT.md is what catches the rest.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def pruner(monkeypatch):
    """Import main.py with env set. Module-level os.environ reads need this first."""
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("SECRET_IDS", "admin-emails,stripe-secret-key")
    monkeypatch.setenv("WRITE_ENABLED_SECRET_IDS", "")

    import main

    return importlib.reload(main)


@pytest.fixture(autouse=True)
def secret_manager_client(pruner):
    """prune_secret_versions constructs a real secretmanager.SecretManagerServiceClient()
    unconditionally, even in tests that only mock process_secret downstream of
    it — without this, that construction needs real GCP credentials, which
    don't exist in CI (only on a dev machine with `gcloud auth` cached),
    mirroring billing_function/test_main.py's storage_client fixture for the
    exact same reason. Patches the shared google.cloud.secretmanager module
    object, so it survives a test's own `importlib.reload(pruner)`. autouse,
    but a test can still override it with its own
    `monkeypatch.setattr(pruner, "secretmanager", ...)` for specific client
    behavior (e.g. the deleted-secret tests)."""
    client = MagicMock()
    with patch.object(pruner.secretmanager, "SecretManagerServiceClient", return_value=client):
        yield client


def _version(pruner, number: int, state: str, etag: str = "etag", secret_id: str = "test-secret", pending_destroy: bool = False):
    import datetime

    from google.cloud.secretmanager_v1.types import SecretVersion

    v = SecretVersion()
    v.name = f"projects/test-project/secrets/{secret_id}/versions/{number}"
    v.state = getattr(SecretVersion.State, state)
    v.etag = etag
    if pending_destroy:
        v.scheduled_destroy_time = datetime.datetime.now(datetime.timezone.utc)
    return v


def _info(pruner, number, state, etag="etag", pending_destroy=False):
    """A plain dict shaped like _version_info's output — for plan_destructions,
    which is pure and never touches a proto."""
    return {
        "number": number,
        "state": state,
        "etag": etag,
        "name": f"v{number}",
        "pending_destroy": pending_destroy,
    }


# ─── plan_destructions ────────────────────────────────────────────────────────


def test_single_enabled_version_is_kept(pruner):
    versions = [_info(pruner, 1, "ENABLED")]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert candidates == []
    assert anomaly is None


def test_keeps_newest_two_enabled_prunes_the_rest(pruner):
    versions = [_info(pruner, n, "ENABLED") for n in (1, 2, 3, 4, 5)]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert anomaly is None
    assert sorted(v["number"] for v in candidates) == [1, 2, 3]


def test_input_order_does_not_matter(pruner):
    versions = [_info(pruner, n, "ENABLED") for n in (5, 1, 3, 2, 4)]
    candidates, _ = pruner.plan_destructions(versions)
    assert sorted(v["number"] for v in candidates) == [1, 2, 3]


def test_disabled_version_newer_than_protected_pair_still_protects_the_floor(pruner):
    """v4 is DISABLED but newer than the two protected ENABLED versions (v5,
    v3) — it must not make v4 itself, or anything at/above the v3 floor, a
    candidate. Only things strictly below v3 are prunable."""
    versions = [
        _info(pruner, 5, "ENABLED"),
        _info(pruner, 4, "DISABLED"),
        _info(pruner, 3, "ENABLED"),
        _info(pruner, 2, "DISABLED"),
        _info(pruner, 1, "ENABLED"),
    ]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert anomaly is None
    assert sorted(v["number"] for v in candidates) == [1, 2]


def test_already_destroyed_versions_are_never_candidates(pruner):
    versions = [
        _info(pruner, 3, "ENABLED"),
        _info(pruner, 2, "ENABLED"),
        _info(pruner, 1, "DESTROYED"),
    ]
    candidates, _ = pruner.plan_destructions(versions)
    assert candidates == []


def test_latest_version_disabled_is_an_anomaly_and_prunes_nothing(pruner):
    versions = [
        _info(pruner, 3, "DISABLED"),
        _info(pruner, 2, "ENABLED"),
        _info(pruner, 1, "ENABLED"),
    ]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert candidates == []
    assert anomaly is not None
    assert "3" in anomaly


def test_no_versions_is_not_an_anomaly(pruner):
    """An empty list means the secret has no versions at all yet — not the
    same failure mode as a stuck rotation."""
    candidates, anomaly = pruner.plan_destructions([])
    assert candidates == []
    assert anomaly is None


def test_anomaly_clears_by_enabling_the_latest_version_itself(pruner):
    """Documented recovery path #1: the disabled latest version's value was
    actually fine, so the fix is to enable that exact version — not some
    other one. Disabling the already-disabled version again, or enabling an
    older one, would leave version 3 as the still-disabled numerical latest
    and never clear the anomaly; only version 3 itself becoming ENABLED does."""
    before = [_info(pruner, 3, "DISABLED"), _info(pruner, 2, "ENABLED"), _info(pruner, 1, "ENABLED")]
    _, anomaly_before = pruner.plan_destructions(before)
    assert anomaly_before is not None

    after_enabling_v3 = [_info(pruner, 3, "ENABLED"), _info(pruner, 2, "ENABLED"), _info(pruner, 1, "ENABLED")]
    candidates_after, anomaly_after = pruner.plan_destructions(after_enabling_v3)
    assert anomaly_after is None
    assert [v["number"] for v in candidates_after] == [1]


def test_anomaly_clears_by_rotating_a_new_version_on_top(pruner):
    """Documented recovery path #2: version 3's value was bad, so a fresh
    version 4 is added instead. Version 3 stays disabled — never re-enabled —
    but the anomaly clears because the numerically latest version (4) is now
    ENABLED, and version 3 stays protected (not pruned) since it's still at
    or above the new floor."""
    before = [_info(pruner, 3, "DISABLED"), _info(pruner, 2, "ENABLED"), _info(pruner, 1, "ENABLED")]
    _, anomaly_before = pruner.plan_destructions(before)
    assert anomaly_before is not None

    after_rotating_v4 = before + [_info(pruner, 4, "ENABLED")]
    candidates_after, anomaly_after = pruner.plan_destructions(after_rotating_v4)
    assert anomaly_after is None
    assert 3 not in [v["number"] for v in candidates_after]


def test_with_only_one_enabled_version_an_older_disabled_one_is_still_prunable(pruner):
    """No enabled predecessor exists to protect — "keep the newest 2 enabled"
    only ever protects versions that are actually enabled, so a disabled
    leftover below that floor is fair game."""
    versions = [_info(pruner, 2, "ENABLED"), _info(pruner, 1, "DISABLED")]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert [v["number"] for v in candidates] == [1]
    assert anomaly is None


def test_version_already_scheduled_for_destruction_is_never_a_candidate_again(pruner):
    """A prior successful destroy leaves the version DISABLED with a
    scheduled_destroy_time — a retry, a manual re-run, or next week's run
    landing before the 7-day TTL elapses must not re-select it."""
    versions = [
        _info(pruner, 3, "ENABLED"),
        _info(pruner, 2, "ENABLED"),
        _info(pruner, 1, "DISABLED", pending_destroy=True),
    ]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert candidates == []
    assert anomaly is None


def test_disabled_version_without_a_scheduled_destroy_is_still_a_candidate(pruner):
    """Only pending_destroy exempts a version — an ordinary disabled leftover
    (never destroyed, just disabled by hand) is still fair game below the
    floor. Guards against plan_destructions treating every DISABLED version
    as if it were already scheduled."""
    versions = [
        _info(pruner, 3, "ENABLED"),
        _info(pruner, 2, "ENABLED"),
        _info(pruner, 1, "DISABLED", pending_destroy=False),
    ]
    candidates, _ = pruner.plan_destructions(versions)
    assert [v["number"] for v in candidates] == [1]


def test_plan_destructions_does_not_reselect_after_a_successful_destroy_response(pruner):
    """End-to-end shape of the bug: run the planner, "destroy" the resulting
    candidate (flipping it to DISABLED + pending_destroy, the shape Secret
    Manager's own list response takes after a real destroy call succeeds),
    then run the planner again on that updated listing. It must come back
    empty, not re-select the same version."""
    versions = [_info(pruner, 3, "ENABLED"), _info(pruner, 2, "ENABLED"), _info(pruner, 1, "ENABLED")]
    candidates, _ = pruner.plan_destructions(versions)
    assert [v["number"] for v in candidates] == [1]

    versions_after_destroy = [
        _info(pruner, 3, "ENABLED"),
        _info(pruner, 2, "ENABLED"),
        _info(pruner, 1, "DISABLED", pending_destroy=True),
    ]
    candidates_again, _ = pruner.plan_destructions(versions_after_destroy)
    assert candidates_again == []


def test_version_info_reads_pending_destroy_from_the_real_proto(pruner):
    scheduled = pruner._version_info(_version(pruner, 1, "DISABLED", pending_destroy=True))
    unscheduled = pruner._version_info(_version(pruner, 2, "DISABLED", pending_destroy=False))
    assert scheduled["pending_destroy"] is True
    assert unscheduled["pending_destroy"] is False


# ─── process_secret ───────────────────────────────────────────────────────────


def _client_listing(pruner, versions, secret_path="projects/test-project/secrets/foo"):
    client = MagicMock()
    client.secret_path.return_value = secret_path
    client.list_secret_versions.return_value = versions
    return client


def test_process_secret_dry_run_reports_without_destroying(pruner):
    versions = [_version(pruner, n, "ENABLED") for n in (1, 2, 3)]
    client = _client_listing(pruner, versions)

    result = pruner.process_secret(client, "foo", write_enabled=False)

    client.destroy_secret_version.assert_not_called()
    assert result["dry_run_would_destroy"] == [1]


def test_process_secret_write_enabled_destroys_candidates(pruner):
    versions = [_version(pruner, n, "ENABLED") for n in (1, 2, 3)]
    client = _client_listing(pruner, versions)

    result = pruner.process_secret(client, "foo", write_enabled=True)

    client.destroy_secret_version.assert_called_once()
    assert result["destroyed"] == [1]
    assert result["errored"] == []


def test_process_secret_passes_the_versions_own_etag_on_destroy(pruner):
    versions = [_version(pruner, n, "ENABLED", etag=f"etag-{n}") for n in (1, 2, 3)]
    client = _client_listing(pruner, versions)

    pruner.process_secret(client, "foo", write_enabled=True)

    request = client.destroy_secret_version.call_args.kwargs["request"]
    assert request.etag == "etag-1"
    assert request.name.endswith("/versions/1")


def test_process_secret_isolates_one_destroy_failure_from_the_rest(pruner):
    """An etag conflict (or any other destroy failure) on one version must not
    stop the other candidates in the same secret from being destroyed."""
    versions = [_version(pruner, n, "ENABLED") for n in (1, 2, 3, 4)]
    client = _client_listing(pruner, versions)
    client.destroy_secret_version.side_effect = [Exception("etag mismatch"), None]

    result = pruner.process_secret(client, "foo", write_enabled=True)

    assert result["destroyed"] == [2]
    assert result["errored"] == [{"version": 1, "error": "etag mismatch"}]


def test_process_secret_anomaly_never_calls_destroy(pruner):
    versions = [_version(pruner, 2, "DISABLED"), _version(pruner, 1, "ENABLED")]
    client = _client_listing(pruner, versions)

    result = pruner.process_secret(client, "foo", write_enabled=True)

    client.destroy_secret_version.assert_not_called()
    assert "anomaly" in result


def test_process_secret_missing_secret_raises_it_is_not_a_benign_skip(pruner):
    """SECRET_IDS is built by Terraform to exclude anything not configured, so
    a NotFound here means real drift (an out-of-band deletion of a secret
    Terraform's config says should exist) — that must propagate like any
    other listing failure, not be swallowed as a normal outcome."""
    from google.api_core.exceptions import NotFound

    client = MagicMock()
    client.secret_path.return_value = "projects/test-project/secrets/gone"
    client.list_secret_versions.side_effect = NotFound("no such secret")

    with pytest.raises(NotFound):
        pruner.process_secret(client, "gone", write_enabled=True)


def test_entry_point_treats_a_deleted_configured_secret_as_a_hard_failure(pruner, monkeypatch, capsys):
    """End-to-end: a secret vanishing out from under a configured deployment
    must make the whole run report failure and log the error marker, not
    return 200 with a quiet "skipped" entry."""
    from google.api_core.exceptions import NotFound

    client = MagicMock()
    client.secret_path.return_value = "projects/test-project/secrets/admin-emails"

    def _list(parent):
        if "admin-emails" in parent:
            raise NotFound("no such secret")
        return []

    client.list_secret_versions.side_effect = _list
    monkeypatch.setattr(pruner, "secretmanager", MagicMock(SecretManagerServiceClient=lambda: client))

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 500
    assert "error" in body["admin-emails"]
    out = capsys.readouterr().out
    assert "SECRET_PRUNE_ERROR" in out
    assert "admin-emails" in out


def test_entry_point_logs_the_error_marker_for_a_failure_outside_the_per_secret_loop(pruner, monkeypatch, capsys):
    """secret_pruner.tf's Scheduler-execution-failure alert deliberately
    excludes any request the function actually ran and 500'd on, leaving
    that case to this policy's own SECRET_PRUNE_ERROR marker instead — so a
    failure before the per-secret loop even starts (env parsing, client
    construction) must still log the marker, or it would alert nowhere."""

    def _boom():
        raise RuntimeError("could not build a Secret Manager client")

    monkeypatch.setattr(pruner, "secretmanager", MagicMock(SecretManagerServiceClient=_boom))

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 500
    assert "error" in body
    out = capsys.readouterr().out
    assert "SECRET_PRUNE_ERROR" in out


def test_process_secret_logs_the_error_marker_on_a_destroy_failure(pruner, capsys):
    """The log-based alert condition in secret_pruner.tf matches this exact
    string — this must fire right where the failure happens, not just get
    swallowed into the returned "errored" list."""
    versions = [_version(pruner, n, "ENABLED") for n in (1, 2, 3)]
    client = _client_listing(pruner, versions)
    client.destroy_secret_version.side_effect = Exception("etag mismatch")

    pruner.process_secret(client, "foo", write_enabled=True)

    out = capsys.readouterr().out
    assert "SECRET_PRUNE_ERROR" in out
    assert "foo" in out


# ─── prune_secret_versions (entry point) ──────────────────────────────────────


def test_entry_point_all_secrets_succeed_returns_200(pruner, monkeypatch):
    monkeypatch.setattr(pruner, "process_secret", lambda client, sid, write_enabled: {"dry_run_would_destroy": []})

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 200
    assert set(body.keys()) == {"admin-emails", "stripe-secret-key"}


def test_entry_point_all_secrets_erroring_returns_500(pruner, monkeypatch):
    def _boom(client, sid, write_enabled):
        raise RuntimeError("boom")

    monkeypatch.setattr(pruner, "process_secret", _boom)

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 500
    assert all("error" in v for v in body.values())


def test_entry_point_partial_hard_error_still_returns_500(pruner, monkeypatch):
    """One secret erroring while another succeeds must still surface as a
    failure — otherwise a single secret stuck erroring forever hides behind
    the rest of the run succeeding, silently and forever."""

    def _mixed(client, sid, write_enabled):
        if sid == "admin-emails":
            raise RuntimeError("boom")
        return {"dry_run_would_destroy": []}

    monkeypatch.setattr(pruner, "process_secret", _mixed)

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 500
    assert "error" in body["admin-emails"]
    assert body["stripe-secret-key"] == {"dry_run_would_destroy": []}


def test_entry_point_a_destroy_error_without_a_raised_exception_still_returns_500(pruner, monkeypatch):
    """process_secret returning normally with a non-empty "errored" list (a
    per-version destroy failure that it already isolated) must still fail the
    run overall — this path never raises, so the 500 has to come from
    inspecting the result, not from a try/except around process_secret."""

    def _one_errored(client, sid, write_enabled):
        if sid == "admin-emails":
            return {"destroyed": [], "errored": [{"version": 1, "error": "etag mismatch"}]}
        return {"dry_run_would_destroy": []}

    monkeypatch.setattr(pruner, "process_secret", _one_errored)

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 500
    assert body["admin-emails"]["errored"]


def test_entry_point_logs_the_error_marker_for_a_hard_failure(pruner, monkeypatch, capsys):
    def _boom(client, sid, write_enabled):
        raise RuntimeError("boom")

    monkeypatch.setattr(pruner, "process_secret", _boom)
    pruner.prune_secret_versions(MagicMock())

    out = capsys.readouterr().out
    assert "SECRET_PRUNE_ERROR" in out


def test_entry_point_no_secrets_configured_returns_200(pruner, monkeypatch):
    monkeypatch.setenv("SECRET_IDS", "")
    reloaded = importlib.reload(pruner)

    body, status = reloaded.prune_secret_versions(MagicMock())

    assert status == 200
    assert body == {}


def test_entry_point_passes_write_enabled_flag_per_secret(pruner, monkeypatch):
    monkeypatch.setenv("WRITE_ENABLED_SECRET_IDS", "stripe-secret-key")
    reloaded = importlib.reload(pruner)

    seen = {}

    def _record(client, sid, write_enabled):
        seen[sid] = write_enabled
        return {}

    monkeypatch.setattr(reloaded, "process_secret", _record)
    reloaded.prune_secret_versions(MagicMock())

    assert seen == {"admin-emails": False, "stripe-secret-key": True}
