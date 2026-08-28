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
  - nothing is actually destroyed unless the secret is in the write-enabled
    allowlist
  - one secret's failure (missing secret, a destroy conflict) never stops the
    others from being processed

Standing caveat, same as billing_function/test_main.py: these tests mock the
Secret Manager client, so they verify our selection logic and orchestration,
not GCP-side IAM or quota behavior. A green suite here is necessary, not
sufficient — the manual dry-run-then-canary-drill sequence in
docs/DEPLOYMENT.md is what catches the rest.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

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


def _version(pruner, number: int, state: str, etag: str = "etag", secret_id: str = "test-secret"):
    from google.cloud.secretmanager_v1.types import SecretVersion

    v = SecretVersion()
    v.name = f"projects/test-project/secrets/{secret_id}/versions/{number}"
    v.state = getattr(SecretVersion.State, state)
    v.etag = etag
    return v


def _info(pruner, number, state, etag="etag"):
    """A plain dict shaped like _version_info's output — for plan_destructions,
    which is pure and never touches a proto."""
    return {"number": number, "state": state, "etag": etag, "name": f"v{number}"}


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


def test_with_only_one_enabled_version_an_older_disabled_one_is_still_prunable(pruner):
    """No enabled predecessor exists to protect — "keep the newest 2 enabled"
    only ever protects versions that are actually enabled, so a disabled
    leftover below that floor is fair game."""
    versions = [_info(pruner, 2, "ENABLED"), _info(pruner, 1, "DISABLED")]
    candidates, anomaly = pruner.plan_destructions(versions)
    assert [v["number"] for v in candidates] == [1]
    assert anomaly is None


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


def test_process_secret_missing_secret_is_skipped_not_raised(pruner):
    from google.api_core.exceptions import NotFound

    client = MagicMock()
    client.secret_path.return_value = "projects/test-project/secrets/gone"
    client.list_secret_versions.side_effect = NotFound("no such secret")

    result = pruner.process_secret(client, "gone", write_enabled=True)

    assert result == {"skipped": "secret not found"}


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


def test_entry_point_partial_failure_still_returns_200(pruner, monkeypatch):
    """One secret erroring while another succeeds is real progress — a
    scheduler retry would just repeat the part that already worked."""

    def _mixed(client, sid, write_enabled):
        if sid == "admin-emails":
            raise RuntimeError("boom")
        return {"dry_run_would_destroy": []}

    monkeypatch.setattr(pruner, "process_secret", _mixed)

    body, status = pruner.prune_secret_versions(MagicMock())

    assert status == 200
    assert "error" in body["admin-emails"]
    assert body["stripe-secret-key"] == {"dry_run_would_destroy": []}


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
