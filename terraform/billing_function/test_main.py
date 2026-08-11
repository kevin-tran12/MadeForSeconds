"""Tests for the budget circuit breaker.

This is the one component whose whole job is to stop runaway spend, so the
properties pinned here are the ones that cost real money if they regress:

  - it does NOT trip early (a forecast notification must not take the site down)
  - it DOES trip when actual spend crosses the budget
  - a malformed payload cannot trip it, and cannot raise into a redelivery loop
  - the monthly reset restores service and is idempotent
"""

import base64
import importlib
import json
import os
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

    import main

    return importlib.reload(main)


def _event(payload: dict):
    """Build a CloudEvent shaped like a Pub/Sub budget notification."""
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    event = MagicMock()
    event.data = {"message": {"data": encoded}}
    return event


def _client_at(max_instances: int):
    """A mocked ServicesClient returning a REAL run_v2.Service proto.

    Deliberately not a MagicMock service: the real proto rejects invalid field
    paths, so these tests fail if the scaling attribute names ever drift from
    the google-cloud-run API.
    """
    from google.cloud import run_v2

    service = run_v2.Service()
    service.template.scaling.max_instance_count = max_instances

    client = MagicMock()
    client.get_service.return_value = service
    client.update_service.return_value.result.return_value.latest_ready_revision = "rev-1"
    return client, service


# ─── kill_cloud_run ───────────────────────────────────────────────────────────


def test_under_budget_does_not_kill(billing):
    """The common case — budget notifications arrive every ~20 min all month."""
    client, _ = _client_at(1)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 4.20, "budgetAmount": 15}))

    client.update_service.assert_not_called()


def test_over_budget_scales_to_zero(billing):
    client, service = _client_at(1)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 15.01, "budgetAmount": 15}))

    client.update_service.assert_called_once()
    assert service.template.scaling.max_instance_count == 0
    assert service.template.scaling.min_instance_count == 0


def test_exactly_at_budget_kills(billing):
    """cost == budget is over the cap, not under it."""
    client, service = _client_at(1)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event({"costAmount": 15, "budgetAmount": 15}))

    client.update_service.assert_called_once()
    assert service.template.scaling.max_instance_count == 0


def test_forecast_notification_does_not_kill(billing):
    """Pins the safety property behind the FORECASTED_SPEND threshold rule.

    Forecast alerts fire while actual spend is still low. If they killed the
    service, the early-warning threshold would take the site down days early.
    """
    client, _ = _client_at(1)
    forecast_payload = {
        "costAmount": 6.50,
        "budgetAmount": 15,
        "alertThresholdExceeded": 1.0,
        "forecastThresholdExceeded": 1.0,
    }

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event(forecast_payload))

    client.update_service.assert_not_called()


def test_tripping_logs_the_alert_marker(billing, capsys):
    """The log-based alert policy in billing.tf matches this exact string."""
    client, _ = _client_at(1)

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
def test_malformed_payload_never_kills_and_never_raises(billing, payload):
    """A bad message must not take the site down, and must not raise.

    The Eventarc trigger uses RETRY_POLICY_RETRY, so an exception here would be
    redelivered indefinitely.
    """
    client, _ = _client_at(1)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.kill_cloud_run(_event(payload))

    client.update_service.assert_not_called()


# ─── reset_cloud_run ──────────────────────────────────────────────────────────


def test_reset_restores_service_when_tripped(billing):
    client, service = _client_at(0)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        _, status = billing.reset_cloud_run(MagicMock())

    assert status == 200
    client.update_service.assert_called_once()
    assert service.template.scaling.max_instance_count == 1
    assert service.template.scaling.min_instance_count == 0


def test_reset_is_idempotent_when_not_tripped(billing):
    """Runs every month — must not churn a new revision when nothing tripped."""
    client, _ = _client_at(1)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        _, status = billing.reset_cloud_run(MagicMock())

    assert status == 200
    client.update_service.assert_not_called()


def test_reset_logs_the_marker_only_when_it_acts(billing, capsys):
    client, _ = _client_at(0)

    with patch.object(billing.run_v2, "ServicesClient", return_value=client):
        billing.reset_cloud_run(MagicMock())

    assert "BUDGET_BREAKER_RESET" in capsys.readouterr().out


def test_service_name_is_env_driven(billing, monkeypatch):
    """Kill and reset must target the same service the Terraform config names."""
    monkeypatch.setenv("CLOUD_RUN_SERVICE", "some-other-service")
    reloaded = importlib.reload(billing)

    client, _ = _client_at(0)
    with patch.object(reloaded.run_v2, "ServicesClient", return_value=client):
        reloaded.reset_cloud_run(MagicMock())

    client.service_path.assert_called_with("test-project", "us-central1", "some-other-service")
