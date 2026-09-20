"""Tests for social token rotation (app/services/social.py) and its internal route."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import social
from app.services.instagram import InstagramError

NOW = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)


def _chain_db():
    """A Firestore mock whose builder calls all return the same object.

    order_by/limit are chained too: without them a query mock returns a fresh
    MagicMock whose .stream() is not the iterator the test queued, and the
    caller silently sees no documents rather than a failure it can read.
    """
    db = MagicMock()
    db.collection.return_value = db
    db.document.return_value = db
    db.order_by.return_value = db
    db.limit.return_value = db
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


# ── record_post / recent_posts (S14 publish history) ──────────────────────────

def test_record_post_stores_a_caption_preview_and_length_never_the_caption():
    """The caption is the operator's own copy. History needs enough to
    recognise a post, not the whole text — same reasoning as _MAX_ERROR_CHARS."""
    db = _chain_db()
    caption = "A" * 300

    social.record_post(db, "instagram", {"ok": True, "media_id": "m1", "caption": caption}, now=NOW)

    written = db.set.call_args_list[0].args[0]
    assert written["caption_chars"] == 300
    assert written["caption_preview"] == "A" * 80
    assert "caption" not in written
    assert written["platform"] == "instagram" and written["at"] == NOW


def test_record_post_updates_last_post_fields_on_success():
    db = _chain_db()
    social.record_post(
        db, "instagram", {"ok": True, "media_id": "m1", "permalink": "https://ig/p/1"}, now=NOW
    )
    merged = [c for c in db.set.call_args_list if c.kwargs.get("merge")]
    assert merged, "a successful post must merge last_post_* onto config/social"
    entry = merged[0].args[0]["instagram"]
    assert entry["last_post_media_id"] == "m1"
    assert entry["last_post_permalink"] == "https://ig/p/1"
    assert entry["last_post_at"] == NOW


def test_record_post_does_not_touch_last_post_fields_on_failure():
    """A failed attempt belongs in the history, but must not overwrite the
    record of the last post that actually went out."""
    db = _chain_db()
    social.record_post(db, "instagram", {"ok": False, "error": "rate limited"}, now=NOW)
    assert db.set.call_count == 1
    assert not [c for c in db.set.call_args_list if c.kwargs.get("merge")]


def test_record_post_survives_a_firestore_failure(caplog):
    """An unrecorded post is a gap in the log; an exception here would be a lie
    about what happened, since the post already reached Instagram."""
    db = _chain_db()
    db.set.side_effect = RuntimeError("firestore down")
    social.record_post(db, "instagram", {"ok": True, "media_id": "m1"}, now=NOW)
    assert "could not record" in caplog.text


def test_recent_posts_returns_newest_first_and_is_json_safe():
    db = _chain_db()
    doc = MagicMock()
    doc.to_dict.return_value = {"ok": True, "media_id": "m1", "at": NOW}
    db.stream.return_value = iter([doc])

    posts = social.recent_posts(db, limit=5)

    assert posts == [{"ok": True, "media_id": "m1", "at": NOW.isoformat()}]
    db.order_by.assert_called_once_with("at", direction="DESCENDING")
    db.limit.assert_called_once_with(5)


def test_recent_posts_returns_empty_rather_than_breaking_status():
    """social_status must still report token health when the history is
    unreadable — the history is the least important thing it carries."""
    db = _chain_db()
    db.stream.side_effect = RuntimeError("no index")
    assert social.recent_posts(db) == []


def test_status_still_returns_only_platform_keys():
    """Publish history is a sibling of the platform mapping, not an entry in
    it: a "recent_posts" key here would read like another platform."""
    db = _chain_db()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"instagram": {"last_error": None}}
    db.get.return_value = snap
    with patch("app.services.social.settings", _configured(True)):
        assert set(social.status(db)) == {"instagram"}
