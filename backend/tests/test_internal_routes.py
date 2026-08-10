"""Tests for app/routes/internal.py.

The refresh endpoint is protected by OIDC verification in production. Tests
cover: dev-mode bypass, missing token, unconfigured invoker, invalid token,
email mismatch, and a valid caller.
"""

from unittest.mock import patch

import pytest


REFRESH_URL = "/api/internal/instagram/refresh-token"
_INVOKER = "mfs-backend@project.iam.gserviceaccount.com"
_AUDIENCE = "https://backend.example.run.app/api/internal/instagram/refresh-token"


# ── dev mode (default test environment) ──────────────────────────────────────

def test_dev_mode_no_auth_required(client):
    with patch("app.routes.internal.instagram.refresh_token") as mock_refresh:
        mock_refresh.return_value = {"refreshed": False, "note": "Dev mode"}
        response = client.post(REFRESH_URL)
    assert response.status_code == 200
    assert response.json()["refreshed"] is False


# ── prod mode OIDC gate ───────────────────────────────────────────────────────

def test_prod_no_invoker_configured_returns_403(client):
    with patch("app.routes.internal.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = ""
        response = client.post(REFRESH_URL)
    assert response.status_code == 403


def test_prod_no_audience_configured_returns_503(client):
    with patch("app.routes.internal.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.instagram_refresh_audience = ""
        response = client.post(REFRESH_URL, headers={"Authorization": "Bearer some-token"})
    assert response.status_code == 503


def test_prod_missing_bearer_returns_401(client):
    with patch("app.routes.internal.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.instagram_refresh_audience = _AUDIENCE
        response = client.post(REFRESH_URL)
    assert response.status_code == 401


def test_prod_invalid_oidc_token_returns_403(client):
    with (
        patch("app.routes.internal.settings") as mock_settings,
        patch(
            "app.routes.internal.id_token.verify_oauth2_token",
            side_effect=Exception("signature verification failed"),
        ),
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.instagram_refresh_audience = _AUDIENCE
        response = client.post(
            REFRESH_URL, headers={"Authorization": "Bearer tampered-token"}
        )
    assert response.status_code == 403


def test_prod_wrong_email_returns_403(client):
    claims = {"email": "attacker@evil.com", "email_verified": True}
    with (
        patch("app.routes.internal.settings") as mock_settings,
        patch(
            "app.routes.internal.id_token.verify_oauth2_token", return_value=claims
        ),
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.instagram_refresh_audience = _AUDIENCE
        response = client.post(
            REFRESH_URL, headers={"Authorization": "Bearer wrong-email-token"}
        )
    assert response.status_code == 403


def test_prod_unverified_email_returns_403(client):
    claims = {"email": _INVOKER, "email_verified": False}
    with (
        patch("app.routes.internal.settings") as mock_settings,
        patch(
            "app.routes.internal.id_token.verify_oauth2_token", return_value=claims
        ),
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.instagram_refresh_audience = _AUDIENCE
        response = client.post(
            REFRESH_URL, headers={"Authorization": "Bearer unverified-email-token"}
        )
    assert response.status_code == 403


def test_prod_valid_oidc_returns_200(client):
    claims = {"email": _INVOKER, "email_verified": True}
    with (
        patch("app.routes.internal.settings") as mock_settings,
        patch(
            "app.routes.internal.id_token.verify_oauth2_token", return_value=claims
        ),
        patch("app.routes.internal.instagram.refresh_token") as mock_refresh,
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.instagram_refresh_audience = _AUDIENCE
        mock_refresh.return_value = {"refreshed": True, "expires_in_days": 60}
        response = client.post(
            REFRESH_URL, headers={"Authorization": f"Bearer valid-oidc-token"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["refreshed"] is True
    assert body["expires_in_days"] == 60


# ── weekly usage report ────────────────────────────────────────────────────

USAGE_REPORT_URL = "/api/internal/usage/weekly-report"
_USAGE_AUDIENCE = "https://backend.example.run.app/api/internal/usage/weekly-report"
_SUMMARY = {
    "window_days": 7,
    "total_requests": 42,
    "distinct_visitors": 5,
    "error_count": 1,
    "top_paths": [{"path": "/api/recipes", "count": 20}],
}


def test_usage_report_dev_mode_no_auth_required(client):
    with (
        patch("app.routes.internal.usage_stats.get_weekly_summary", return_value=_SUMMARY),
        patch("app.routes.internal.send_email") as mock_send,
    ):
        response = client.post(USAGE_REPORT_URL)
    assert response.status_code == 200
    assert response.json()["total_requests"] == 42
    mock_send.assert_called_once()


def test_usage_report_prod_no_invoker_configured_returns_403(client):
    with patch("app.routes.internal.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = ""
        response = client.post(USAGE_REPORT_URL)
    assert response.status_code == 403


def test_usage_report_prod_valid_oidc_sends_email(client):
    claims = {"email": _INVOKER, "email_verified": True}
    with (
        patch("app.routes.internal.settings") as mock_settings,
        patch(
            "app.routes.internal.id_token.verify_oauth2_token", return_value=claims
        ),
        patch("app.routes.internal.usage_stats.get_weekly_summary", return_value=_SUMMARY),
        patch("app.routes.internal.send_email") as mock_send,
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = _INVOKER
        mock_settings.usage_report_audience = _USAGE_AUDIENCE
        mock_settings.alert_email = "owner@example.com"
        response = client.post(
            USAGE_REPORT_URL, headers={"Authorization": "Bearer valid-oidc-token"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["total_requests"] == 42
    assert body["distinct_visitors"] == 5
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    assert args[0] == "owner@example.com"
    assert "/api/recipes" in args[2]
