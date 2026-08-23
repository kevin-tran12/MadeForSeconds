"""Tests for the budget circuit breaker.

This is the one component whose whole job is to stop runaway spend, so the
properties pinned here are the ones that cost real money if they regress:

  - it does NOT trip early (a forecast notification must not take the site down)
  - it DOES revoke public access when actual spend crosses the budget
  - a malformed payload cannot trip it, and cannot raise into a redelivery loop
  - the monthly reset restores access, and both paths are idempotent

Standing caveat, learned the hard way: these tests mock the Cloud Run client, so
they verify *our* logic and nothing about IAM or GCP-side semantics. Two real
bugs slipped past a green suite here — missing IAM grants, and Cloud Run
reinterpreting max_instance_count = 0 as "unset". Only a live trip catches that
class of failure. A green run here is necessary, not sufficient.
"""

import base64
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def billing(monkeypatch):
    """Import main.py with env set. Module-level os.environ reads need this first."""
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("GCP_REGION", "us-central1")
    monkeypatch.setenv("CLOUD_RUN_SERVICE", "mfs-backend")
    monkeypatch.setenv("STATUS_BUCKET", "test-project-images")

    import main

    return importlib.reload(main)


@pytest.fixture(autouse=True)
def storage_client(billing):
    """Patches billing.storage.Client so status.json writes/deletes hit a mock
    in every test — kill_cloud_run/reset_cloud_run now call these unconditionally,
    and without this every existing IAM-focused test below would also attempt a
    real (if caught) GCS client construction. autouse, but still requestable by
    name for tests that want to assert on the upload/delete calls."""
    client = MagicMock()
    with patch.object(billing.storage, "Client", return_value=client):
        yield client


def _uploaded_payload(storage_client) -> dict:
    """The JSON body of whatever was uploaded as status.json, if anything."""
    blob = storage_client.bucket.return_value.blob.return_value
    (body,) = blob.upload_from_string.call_args.args
    return json.loads(body)


def _event(payload: dict):
    """Build a CloudEvent shaped like a Pub/Sub budget notification."""
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    event = MagicMock()
    event.data = {"message": {"data": encoded}}
    return event


def _client_with(public: bool, extra_members=()):
    """A mocked ServicesClient returning a REAL google.iam.v1 Policy proto.

    Deliberately not a MagicMock policy: the real proto enforces field types and
    repeated-field semantics, so these tests fail if the binding manipulation is
    not actually valid against the IAM API's shape.
    """
    from google.iam.v1 import policy_pb2

    policy = policy_pb2.Policy()
    members = list(extra_members)
    if public:
        members.append("allUsers")
    if members:
        binding = policy.bindings.add()
        binding.role = "roles/run.invoker"
        binding.members.extend(members)

    client = MagicMock()
    # Must be a real string: the IAM request protos reject a MagicMock resource.
    client.service_path.return_value = (
        "projects/test-project/locations/us-central1/services/mfs-backend"
    )
    client.get_iam_policy.return_value = policy
    return client, policy


def _members_after(client):
    """The invoker members in the policy that was written back."""
    written = client.set_iam_policy.call_args.kwargs["request"].policy
    return [m for b in written.bindings if b.role == "roles/run.invoker" for m in b.members]


# ─── kill_cloud_run ───────────────────────────────────────────────────────────


def test_under_budget_does_not_trip(billing):
    """The common case — budget notifications arrive every ~20 min all month."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 4.20, "budgetAmount": 15}))

    client.set_iam_policy.assert_not_called()


def test_over_budget_revokes_public_access(billing):
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 15.01, "budgetAmount": 15}))

    client.set_iam_policy.assert_called_once()
    assert "allUsers" not in _members_after(client)


def test_exactly_at_budget_trips(billing):
    """cost == budget is over the cap, not under it."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 15, "budgetAmount": 15}))

    client.set_iam_policy.assert_called_once()
    assert "allUsers" not in _members_after(client)


def test_trip_preserves_other_invokers(billing):
    """Only allUsers is revoked — service-to-service callers must keep working."""
    client, _ = _client_with(public=True, extra_members=["serviceAccount:sched@x.iam"])

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))

    assert _members_after(client) == ["serviceAccount:sched@x.iam"]


def test_trip_drops_binding_left_empty(billing):
    """setIamPolicy rejects a binding with no members."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))

    written = client.set_iam_policy.call_args.kwargs["request"].policy
    assert all(b.members for b in written.bindings)


def test_trip_is_idempotent_when_already_private(billing):
    """Eventarc redelivers for as long as the budget stays over."""
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))

    client.set_iam_policy.assert_not_called()


def test_trip_writes_the_status_file(billing, storage_client):
    """src/lib/site-status.ts reads this to confirm a deliberate cost-cap pause."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))

    storage_client.bucket.assert_called_with("test-project-images")
    storage_client.bucket.return_value.blob.assert_called_with("status.json")
    assert _uploaded_payload(storage_client)["status"] == "budget_cap"


def test_trip_writes_the_status_file_even_when_already_tripped(billing, storage_client):
    """Self-heals a prior best-effort write failure: Eventarc keeps redelivering
    as long as the budget stays over, so this is the retry mechanism."""
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))

    assert _uploaded_payload(storage_client)["status"] == "budget_cap"


def test_status_file_write_failure_does_not_raise(billing, storage_client):
    """The IAM revoke is the real safety mechanism; a GCS hiccup must not block it."""
    storage_client.bucket.return_value.blob.return_value.upload_from_string.side_effect = Exception("boom")
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))  # must not raise

    client.set_iam_policy.assert_called_once()


def test_forecast_notification_does_not_trip(billing):
    """Pins the safety property behind the FORECASTED_SPEND threshold rule.

    Forecast alerts fire while actual spend is still low. If they tripped the
    breaker, the early-warning threshold would take the site down days early.
    """
    client, _ = _client_with(public=True)
    forecast_payload = {
        "costAmount": 6.50,
        "budgetAmount": 15,
        "alertThresholdExceeded": 1.0,
        "forecastThresholdExceeded": 1.0,
    }

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event(forecast_payload))

    client.set_iam_policy.assert_not_called()


def test_tripping_logs_the_alert_marker(billing, capsys):
    """The log-based alert policy in billing.tf matches this exact string."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 99, "budgetAmount": 15}))

    assert "BUDGET_BREAKER_TRIPPED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [
        {},                                              # no fields at all
        {"costAmount": 99},                              # no budgetAmount
        {"costAmount": "abc", "budgetAmount": 15},       # unparseable
        {"costAmount": None, "budgetAmount": None},      # explicit nulls
        {"costAmount": 99, "budgetAmount": 0},           # zero budget
    ],
)
def test_malformed_payload_never_trips_and_never_raises(billing, payload):
    """A bad message must not take the site down, and must not raise.

    The Eventarc trigger uses RETRY_POLICY_RETRY, so an exception here would be
    redelivered indefinitely.
    """
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event(payload))

    client.set_iam_policy.assert_not_called()


# ─── reset_cloud_run ──────────────────────────────────────────────────────────


def test_reset_restores_public_access(billing):
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        _, status = billing.reset_cloud_run(MagicMock())

    assert status == 200
    client.set_iam_policy.assert_called_once()
    assert "allUsers" in _members_after(client)


def test_reset_recreates_binding_when_absent(billing):
    """The trip drops the whole binding when allUsers was its only member."""
    client, policy = _client_with(public=False)
    assert not policy.bindings  # nothing to append to

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.reset_cloud_run(MagicMock())

    assert _members_after(client) == ["allUsers"]


def test_reset_preserves_other_invokers(billing):
    client, _ = _client_with(public=False, extra_members=["serviceAccount:sched@x.iam"])

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.reset_cloud_run(MagicMock())

    assert set(_members_after(client)) == {"allUsers", "serviceAccount:sched@x.iam"}


def test_reset_is_idempotent_when_not_tripped(billing):
    """Runs every month — must not rewrite the policy when nothing tripped."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        _, status = billing.reset_cloud_run(MagicMock())

    assert status == 200
    client.set_iam_policy.assert_not_called()


def test_reset_deletes_the_status_file(billing, storage_client):
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.reset_cloud_run(MagicMock())

    storage_client.bucket.assert_called_with("test-project-images")
    storage_client.bucket.return_value.blob.assert_called_with("status.json")
    storage_client.bucket.return_value.blob.return_value.delete.assert_called_once()


def test_reset_deletes_the_status_file_even_when_not_tripped(billing, storage_client):
    """Self-heals a prior best-effort delete failure — otherwise a stale status
    file could keep reporting a cost-cap pause after the site is already back."""
    client, _ = _client_with(public=True)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.reset_cloud_run(MagicMock())

    storage_client.bucket.return_value.blob.return_value.delete.assert_called_once()


def test_reset_tolerates_status_file_already_absent(billing, storage_client):
    """The common case: no trip happened, so there was never a file to delete."""
    from google.api_core.exceptions import NotFound

    storage_client.bucket.return_value.blob.return_value.delete.side_effect = NotFound("no such object")
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        _, status = billing.reset_cloud_run(MagicMock())  # must not raise

    assert status == 200


def test_status_file_delete_failure_does_not_raise(billing, storage_client):
    storage_client.bucket.return_value.blob.return_value.delete.side_effect = Exception("boom")
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        _, status = billing.reset_cloud_run(MagicMock())  # must not raise

    assert status == 200


def test_reset_logs_the_marker_only_when_it_acts(billing, capsys):
    client, _ = _client_with(public=False)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.reset_cloud_run(MagicMock())

    assert "BUDGET_BREAKER_RESET" in capsys.readouterr().out


def test_service_name_is_env_driven(billing, monkeypatch):
    """Kill and reset must target the same service the Terraform config names."""
    monkeypatch.setenv("CLOUD_RUN_SERVICE", "some-other-service")
    reloaded = importlib.reload(billing)

    client, _ = _client_with(public=False)
    with patch.object(reloaded.run_v2, "ServicesClient", return_value=client):
        reloaded.reset_cloud_run(MagicMock())

    client.service_path.assert_called_with("test-project", "us-central1", "some-other-service")
