"""Unit tests for GCS upload helpers and Cloud Run-safe signed URLs."""

from unittest.mock import MagicMock, patch

import pytest
from google.auth import credentials as google_auth_credentials

from app.services import uploads


# ── sanitize_filename ─────────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_plain_name_unchanged(self):
        assert uploads.sanitize_filename("photo.jpg") == "photo.jpg"

    def test_strips_unix_path_components(self):
        assert uploads.sanitize_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_path_components(self):
        assert uploads.sanitize_filename("C:\\Users\\kevin\\photo.jpg") == "photo.jpg"

    def test_replaces_unsafe_characters(self):
        assert uploads.sanitize_filename("my photo (1).png") == "my_photo__1_.png"

    def test_caps_length(self):
        assert len(uploads.sanitize_filename("a" * 300 + ".jpg")) <= 100

    def test_empty_falls_back(self):
        assert uploads.sanitize_filename("") == "upload"
        assert uploads.sanitize_filename("///") == "upload"


# ── _signing_kwargs ───────────────────────────────────────────────────────────

class TestSigningKwargs:
    def test_key_file_credentials_need_no_extras(self):
        creds = MagicMock(spec=google_auth_credentials.Signing)
        with patch("google.auth.default", return_value=(creds, "proj")):
            assert uploads._signing_kwargs() == {}

    def test_metadata_credentials_route_through_iam(self):
        creds = MagicMock()
        creds.service_account_email = "mfs-backend@proj.iam.gserviceaccount.com"
        creds.token = "access-token-123"
        with patch("google.auth.default", return_value=(creds, "proj")):
            kwargs = uploads._signing_kwargs()

        creds.refresh.assert_called_once()
        assert kwargs == {
            "service_account_email": "mfs-backend@proj.iam.gserviceaccount.com",
            "access_token": "access-token-123",
        }

    def test_unresolved_default_email_falls_back(self):
        creds = MagicMock()
        creds.service_account_email = "default"
        with patch("google.auth.default", return_value=(creds, "proj")):
            assert uploads._signing_kwargs() == {}


# ── signed URLs ───────────────────────────────────────────────────────────────

_IAM_KWARGS = {"service_account_email": "sa@p.iam", "access_token": "tok"}


class TestSignedUrls:
    def test_signed_get_url_uses_iam_kwargs(self):
        with (
            patch("app.services.uploads.storage") as mock_storage,
            patch("app.services.uploads._signing_kwargs", return_value=_IAM_KWARGS),
        ):
            blob = mock_storage.Client.return_value.bucket.return_value.blob.return_value
            blob.generate_signed_url.return_value = "https://signed.example/get"

            url = uploads.signed_get_url("my-bucket", "receipts/r.pdf")

        assert url == "https://signed.example/get"
        call = blob.generate_signed_url.call_args
        assert call.kwargs["version"] == "v4"
        assert call.kwargs["method"] == "GET"
        assert call.kwargs["service_account_email"] == "sa@p.iam"
        assert call.kwargs["access_token"] == "tok"

    def test_signed_put_url_enforces_size_and_content_type(self):
        with (
            patch("app.services.uploads.storage") as mock_storage,
            patch("app.services.uploads._signing_kwargs", return_value={}),
        ):
            blob = mock_storage.Client.return_value.bucket.return_value.blob.return_value
            blob.generate_signed_url.return_value = "https://signed.example/put"

            result = uploads.signed_put_url("my-bucket", "uuid-photo.jpg", "image/jpeg")

        call = blob.generate_signed_url.call_args
        assert call.kwargs["method"] == "PUT"
        assert call.kwargs["content_type"] == "image/jpeg"
        assert call.kwargs["headers"] == {"x-goog-content-length-range": "0,10485760"}
        assert result["upload_url"] == "https://signed.example/put"
        assert result["method"] == "PUT"
        assert result["required_headers"]["Content-Type"] == "image/jpeg"
        assert result["required_headers"]["x-goog-content-length-range"] == "0,10485760"
        assert result["expires_in_seconds"] == 900


# ── fetch_image_to_gcs (SSRF guards) ──────────────────────────────────────────

_PUBLIC_ADDR = [(2, 1, 6, "", ("93.184.216.34", 443))]


def _mock_response(mock_httpx, status=200, content_type="image/jpeg", chunks=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    resp.iter_bytes.return_value = chunks if chunks is not None else [b"image-bytes"]
    client = mock_httpx.Client.return_value.__enter__.return_value
    client.stream.return_value.__enter__.return_value = resp
    return resp


class TestFetchImageToGcs:
    def test_rejects_http_scheme(self):
        with pytest.raises(ValueError, match="https"):
            uploads.fetch_image_to_gcs("http://example.com/x.jpg")

    def test_rejects_missing_hostname(self):
        with pytest.raises(ValueError):
            uploads.fetch_image_to_gcs("https:///x.jpg")

    def test_rejects_private_address(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 443))]):
            with pytest.raises(ValueError, match="non-public"):
                uploads.fetch_image_to_gcs("https://internal.example/x.jpg")

    def test_rejects_loopback(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with pytest.raises(ValueError, match="non-public"):
                uploads.fetch_image_to_gcs("https://localhost/x.jpg")

    def test_rejects_metadata_server(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
            with pytest.raises(ValueError, match="non-public"):
                uploads.fetch_image_to_gcs("https://metadata.google.internal/x.jpg")

    def test_rejects_redirects_and_errors(self):
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
        ):
            _mock_response(mock_httpx, status=302)
            with pytest.raises(ValueError, match="HTTP 302"):
                uploads.fetch_image_to_gcs("https://example.com/x.jpg")

    def test_rejects_non_image_content_type(self):
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
        ):
            _mock_response(mock_httpx, content_type="text/html")
            with pytest.raises(ValueError, match="content type"):
                uploads.fetch_image_to_gcs("https://example.com/x.jpg")

    def test_rejects_oversized_body(self):
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
        ):
            _mock_response(mock_httpx, chunks=[b"x" * (1024 * 1024)] * 11)
            with pytest.raises(ValueError, match="10MB"):
                uploads.fetch_image_to_gcs("https://example.com/huge.jpg")

    def test_uploads_to_images_bucket_in_production(self):
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
            patch("app.services.uploads.settings") as mock_settings,
            patch("app.services.uploads.storage") as mock_storage,
        ):
            _mock_response(mock_httpx)
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"

            url = uploads.fetch_image_to_gcs("https://example.com/photos/dish.jpg")

        assert url.startswith("https://storage.googleapis.com/img-bucket/")
        assert url.endswith("-dish.jpg")
        blob = mock_storage.Client.return_value.bucket.return_value.blob.return_value
        blob.upload_from_string.assert_called_once_with(b"image-bytes", content_type="image/jpeg")

    def test_dev_mode_returns_placeholder(self):
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
        ):
            _mock_response(mock_httpx)
            url = uploads.fetch_image_to_gcs("https://example.com/x.jpg")

        assert "placehold.co" in url


# ── blob URL helpers (bucket-aware wrappers) ──────────────────────────────────

class TestBlobWrappers:
    def test_image_wrapper_uses_images_bucket(self):
        with (
            patch("app.services.uploads.settings") as mock_settings,
            patch("app.services.uploads.storage") as mock_storage,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            uploads.delete_recipe_image_blob("https://storage.googleapis.com/img-bucket/x.jpg")

        mock_storage.Client.return_value.bucket.assert_called_with("img-bucket")

    def test_image_wrapper_ignores_foreign_urls(self):
        with (
            patch("app.services.uploads.settings") as mock_settings,
            patch("app.services.uploads.storage") as mock_storage,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            uploads.delete_recipe_image_blob("https://placehold.co/800x400?text=x.jpg")
            uploads.delete_recipe_image_blob(None)

        mock_storage.Client.assert_not_called()
