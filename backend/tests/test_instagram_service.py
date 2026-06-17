"""Tests for app/services/instagram.py.

The real Graph API is never called — httpx and Secret Manager are mocked at the
service layer. ``settings.is_dev`` is True by default in the test environment so
dev no-ops run without any mocking; prod paths explicitly override ``is_dev``.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from app.services import instagram as ig


@pytest.fixture(autouse=True)
def reset_token_cache():
    """Clear the in-process token cache between tests."""
    ig._token_cache["value"] = ""
    ig._token_cache["fetched_at"] = 0.0
    ig._sm_client = None
    yield
    ig._token_cache["value"] = ""
    ig._token_cache["fetched_at"] = 0.0
    ig._sm_client = None


# ── publish_image: dev no-op ──────────────────────────────────────────────────

class TestPublishImageDev:
    def test_returns_dev_no_op(self):
        result = ig.publish_image("https://example.com/img.jpg", "Hello")
        assert result["id"] == "dev-ig-media"
        assert "Dev mode" in result["note"]

    def test_skips_validation_in_dev(self):
        # Non-https URL is accepted without error in dev mode
        result = ig.publish_image("http://not-https.com/img.jpg", "Caption")
        assert result["id"] == "dev-ig-media"


# ── publish_image: prod ───────────────────────────────────────────────────────

class TestPublishImageProd:
    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="tok")
    @patch("app.services.instagram._graph_request")
    @patch("app.services.instagram.time")
    def test_create_poll_publish_permalink_sequence(
        self, mock_time, mock_req, _tok, mock_settings
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_user_id = "user123"
        mock_req.side_effect = [
            {"id": "ctr-id"},                                            # create container
            {"status_code": "FINISHED"},                                 # poll
            {"id": "media-id"},                                          # publish
            {"permalink": "https://www.instagram.com/p/xyz/"},          # permalink
        ]
        result = ig.publish_image("https://storage.googleapis.com/b/img.jpg", "Caption")
        assert result == {"id": "media-id", "permalink": "https://www.instagram.com/p/xyz/"}
        assert mock_req.call_count == 4

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="tok")
    @patch("app.services.instagram._graph_request")
    @patch("app.services.instagram.time")
    def test_in_progress_retries_until_finished(
        self, mock_time, mock_req, _tok, mock_settings
    ):
        mock_time.time.return_value = 0.0
        mock_settings.is_dev = False
        mock_settings.instagram_user_id = "user123"
        mock_req.side_effect = [
            {"id": "ctr-id"},
            {"status_code": "IN_PROGRESS"},
            {"status_code": "FINISHED"},
            {"id": "media-id"},
            {"permalink": ""},
        ]
        ig.publish_image("https://storage.googleapis.com/b/img.jpg")
        mock_time.sleep.assert_called_once_with(ig._POLL_DELAY_SECONDS)

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="tok")
    @patch("app.services.instagram._graph_request")
    @patch("app.services.instagram.time")
    def test_error_status_raises_instagram_error(
        self, mock_time, mock_req, _tok, mock_settings
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_user_id = "user123"
        mock_req.side_effect = [
            {"id": "ctr-id"},
            {"status_code": "ERROR"},
        ]
        with pytest.raises(ig.InstagramError, match="processing failed"):
            ig.publish_image("https://storage.googleapis.com/b/img.jpg")

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="")
    def test_missing_token_raises_value_error(self, _tok, mock_settings):
        mock_settings.is_dev = False
        mock_settings.instagram_user_id = "user123"
        with pytest.raises(ValueError, match="not configured"):
            ig.publish_image("https://example.com/img.jpg")

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="tok")
    def test_non_https_url_raises_value_error(self, _tok, mock_settings):
        mock_settings.is_dev = False
        mock_settings.instagram_user_id = "user123"
        with pytest.raises(ValueError, match="https"):
            ig.publish_image("http://not-https.com/img.jpg")

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="tok")
    def test_oversized_caption_raises_value_error(self, _tok, mock_settings):
        mock_settings.is_dev = False
        mock_settings.instagram_user_id = "user123"
        long_caption = "x" * (ig.MAX_CAPTION_CHARS + 1)
        with pytest.raises(ValueError, match="caption exceeds"):
            ig.publish_image("https://example.com/img.jpg", long_caption)


# ── refresh_token ─────────────────────────────────────────────────────────────

class TestRefreshToken:
    def test_dev_mode_is_no_op(self):
        result = ig.refresh_token()
        assert result["refreshed"] is False
        assert "Dev mode" in result["note"]

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="old-tok")
    @patch("app.services.instagram._graph_request")
    @patch("app.services.instagram._write_secret")
    def test_writes_new_secret_and_returns_expiry(
        self, mock_write, mock_req, _tok, mock_settings
    ):
        mock_settings.is_dev = False
        mock_settings.instagram_token_secret_id = "instagram-access-token"
        mock_req.return_value = {"access_token": "new-tok", "expires_in": 5184000}
        result = ig.refresh_token()
        assert result["refreshed"] is True
        assert result["expires_in_days"] == 60
        mock_write.assert_called_once_with("instagram-access-token", "new-tok")

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="old-tok")
    @patch("app.services.instagram._graph_request")
    @patch("app.services.instagram._write_secret")
    def test_refreshed_token_is_cached(self, mock_write, mock_req, _tok, mock_settings):
        mock_settings.is_dev = False
        mock_settings.instagram_token_secret_id = "instagram-access-token"
        mock_req.return_value = {"access_token": "new-tok", "expires_in": 5184000}
        ig.refresh_token()
        assert ig._token_cache["value"] == "new-tok"

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="")
    def test_no_current_token_raises_instagram_error(self, _tok, mock_settings):
        mock_settings.is_dev = False
        with pytest.raises(ig.InstagramError, match="No current"):
            ig.refresh_token()

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram.get_access_token", return_value="old-tok")
    @patch("app.services.instagram._graph_request", return_value={"no_token_here": True})
    def test_missing_new_token_in_response_raises(self, _req, _tok, mock_settings):
        mock_settings.is_dev = False
        with pytest.raises(ig.InstagramError, match="Refresh did not return"):
            ig.refresh_token()


# ── get_access_token caching ──────────────────────────────────────────────────

class TestGetAccessToken:
    def test_dev_returns_env_var(self):
        with patch("app.services.instagram.settings") as mock_settings:
            mock_settings.is_dev = True
            mock_settings.instagram_access_token = "dev-token"
            result = ig.get_access_token()
        assert result == "dev-token"

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram._read_secret", return_value="secret-tok")
    def test_prod_reads_from_secret_manager(self, mock_read, mock_settings):
        mock_settings.is_dev = False
        mock_settings.instagram_token_secret_id = "instagram-access-token"
        result = ig.get_access_token()
        assert result == "secret-tok"
        mock_read.assert_called_once_with("instagram-access-token")

    @patch("app.services.instagram.settings")
    @patch("app.services.instagram._read_secret", return_value="cached-tok")
    @patch("app.services.instagram.time")
    def test_prod_second_call_uses_cache(self, mock_time, mock_read, mock_settings):
        mock_settings.is_dev = False
        mock_settings.instagram_token_secret_id = "instagram-access-token"
        mock_time.time.return_value = 1000.0
        ig.get_access_token()
        ig.get_access_token()
        mock_read.assert_called_once()  # second call served from cache
