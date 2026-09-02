"""Tests for social token rotation (app/services/social.py) and its internal route."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import social
from app.services.instagram import InstagramError

NOW = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)


def _chain_db():
    db = MagicMock()
    db.collection.return_value = db
    db.document.return_value = db
    return db


def _configured(value: bool):
    s = MagicMock()
    s.instagram_configured = value
    return s


# ── refresh_all ───────────────────────────────────────────────────────────────

def test_refresh_all_records_expiry_on_success():
    db = _chain_db()
    with patch("app.services.social.settings", _configured(True)), \
         patch("app.services.social.instagram.refresh_token", return_value={"refreshed": True, "expires_in_days": 60}):
        result = social.refresh_all(db, NOW)
    assert result["failed"] == []
    assert result["results"]["instagram"]["refreshed"] is True
    args, kwargs = db.set.call_args
    assert kwargs == {"merge": True}
    entry = args[0]["instagram"]
    assert entry["last_refresh_at"] == NOW and entry["last_error"] is None
    assert entry["expires_at"] == NOW + timedelta(days=60)


def test_refresh_all_logs_marker_and_records_error_on_failure(caplog):
    db = _chain_db()
    caplog.set_level("ERROR", logger="app.services.social")
    with patch("app.services.social.settings", _configured(True)), \
         patch("app.services.social.instagram.refresh_token",
               side_effect=InstagramError("Instagram auth error: Session has expired on Sunday, 16-Aug-26", auth=True)):
        result = social.refresh_all(db, NOW)
    assert result["failed"] == ["instagram"]
    assert "Session has expired" in result["results"]["instagram"]["error"]
    assert any("SOCIAL_REFRESH_FAILED platform=instagram" in r.getMessage() for r in caplog.records)
    entry = db.set.call_args[0][0]["instagram"]
    assert entry["last_failed_at"] == NOW and "Session has expired" in entry["last_error"]


def test_refresh_all_skips_unconfigured_platforms_without_touching_firestore():
    db = _chain_db()
    with patch("app.services.social.settings", _configured(False)):
        result = social.refresh_all(db, NOW)
    assert result == {"results": {"instagram": {"skipped": "not configured"}}, "failed": [], "at": NOW.isoformat()}
    db.set.assert_not_called()


def test_refresh_all_survives_a_status_write_failure():
    db = _chain_db()
    db.set.side_effect = RuntimeError("firestore down")
    with patch("app.services.social.settings", _configured(True)), \
         patch("app.services.social.instagram.refresh_token", return_value={"refreshed": True, "expires_in_days": 60}):
        result = social.refresh_all(db, NOW)
    assert result["failed"] == []


def test_status_merges_configuration_with_the_recorded_outcome():
    db = _chain_db()
    db.get.return_value.exists = True
    db.get.return_value.to_dict.return_value = {"instagram": {"last_refresh_at": NOW, "expires_at": NOW + timedelta(days=60), "last_error": None}}
    with patch("app.services.social.settings", _configured(True)):
        out = social.status(db)
    assert out["instagram"]["configured"] is True
    assert out["instagram"]["expires_at"] == (NOW + timedelta(days=60)).isoformat()
    db.get.return_value.exists = False
    with patch("app.services.social.settings", _configured(False)):
        assert social.status(db) == {"instagram": {"configured": False}}


# ── route ─────────────────────────────────────────────────────────────────────

REFRESH_URL = "/api/internal/social/refresh-tokens"


def test_route_returns_per_platform_results(client, mock_db):
    with patch("app.services.social.settings", _configured(True)), \
         patch("app.services.social.instagram.refresh_token", return_value={"refreshed": True, "expires_in_days": 60}):
        response = client.post(REFRESH_URL)
    assert response.status_code == 200
    assert response.json()["results"]["instagram"]["refreshed"] is True
    assert response.json()["failed"] == []


def test_route_500s_when_a_platform_fails_so_scheduler_retries(client, mock_db):
    with patch("app.services.social.settings", _configured(True)), \
         patch("app.services.social.instagram.refresh_token", side_effect=InstagramError("expired", auth=True)):
        response = client.post(REFRESH_URL)
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "social_refresh_failed" and detail["failed"] == ["instagram"]


def test_route_is_oidc_gated_in_production(client, mock_db):
    with patch("app.routes.internal.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.instagram_refresh_invoker_email = "mfs-backend@project.iam.gserviceaccount.com"
        mock_settings.social_refresh_audience = "https://backend.example.run.app/api/internal/social/refresh-tokens"
        assert client.post(REFRESH_URL).status_code == 401
