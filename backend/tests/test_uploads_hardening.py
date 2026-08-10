"""Tests for upload content sniffing and filename sanitisation.

These cover the two ways a declared Content-Type can be abused:
  1. Claiming image/jpeg for content that is actually markup. The images
     bucket is world-readable, so a stored HTML file would be served back
     to visitors from a trusted origin.
  2. Smuggling path separators through the filename into the GCS blob key.
"""

from unittest.mock import patch

import pytest

from app.services import uploads

from conftest import (
    HEIC_BYTES,
    JPEG_BYTES,
    NOT_A_MEDIA_FILE,
    PDF_BYTES,
    PNG_BYTES,
    WEBP_BYTES,
)


# ── sniff_content_type ────────────────────────────────────────────────────────

class TestSniffContentType:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            (JPEG_BYTES, "image/jpeg"),
            (PNG_BYTES, "image/png"),
            (WEBP_BYTES, "image/webp"),
            (HEIC_BYTES, "image/heic"),
            (PDF_BYTES, "application/pdf"),
        ],
    )
    def test_identifies_known_formats(self, payload, expected):
        assert uploads.sniff_content_type(payload) == expected

    def test_rejects_html_masquerading_as_image(self):
        assert uploads.sniff_content_type(NOT_A_MEDIA_FILE) is None

    def test_rejects_too_short_input(self):
        # Under 12 bytes there is not enough to match any signature.
        assert uploads.sniff_content_type(b"\xff\xd8\xff") is None

    def test_rejects_empty_input(self):
        assert uploads.sniff_content_type(b"") is None

    def test_riff_without_webp_marker_is_not_an_image(self):
        # A RIFF container holding WAVE audio must not pass as image/webp.
        assert uploads.sniff_content_type(b"RIFF\x00\x00\x00\x00WAVEfmt ") is None


# ── verify_upload_type ────────────────────────────────────────────────────────

class TestVerifyUploadType:
    def test_returns_sniffed_type_when_allowed(self):
        assert uploads.verify_upload_type(PNG_BYTES, uploads.ALLOWED_IMAGE_TYPES) == "image/png"

    def test_raises_when_format_unrecognised(self):
        with pytest.raises(ValueError, match="Unrecognised file format"):
            uploads.verify_upload_type(NOT_A_MEDIA_FILE, uploads.ALLOWED_IMAGE_TYPES)

    def test_raises_when_recognised_but_not_permitted(self):
        # A PDF is a valid receipt but never a valid recipe image.
        with pytest.raises(ValueError, match="not permitted here"):
            uploads.verify_upload_type(PDF_BYTES, uploads.ALLOWED_IMAGE_TYPES)

    def test_pdf_is_permitted_for_receipts(self):
        assert uploads.verify_upload_type(PDF_BYTES, uploads.ALLOWED_RECEIPT_TYPES) == "application/pdf"


# ── sanitize_filename ─────────────────────────────────────────────────────────

class TestSanitizeFilename:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("../../etc/passwd", "passwd"),
            ("..\\..\\windows\\system32", "system32"),
            ("nested/path/photo.jpg", "photo.jpg"),
            ("photo.jpg", "photo.jpg"),
            ("my photo (1).jpg", "my_photo__1_.jpg"),
        ],
    )
    def test_strips_paths_and_unsafe_characters(self, raw, expected):
        assert uploads.sanitize_filename(raw) == expected

    def test_falls_back_when_nothing_usable_remains(self):
        assert uploads.sanitize_filename("") == "upload"
        assert uploads.sanitize_filename("/") == "upload"

    def test_caps_length(self):
        assert len(uploads.sanitize_filename("a" * 500)) == 100


# ── End-to-end through the routes ─────────────────────────────────────────────

class TestUploadRoutesRejectDisguisedContent:
    def test_image_route_rejects_html_declared_as_jpeg(self, authenticated_client):
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            response = authenticated_client.post(
                "/api/admin/upload-image",
                files={"file": ("photo.jpg", NOT_A_MEDIA_FILE, "image/jpeg")},
            )
        assert response.status_code == 400
        assert "Unrecognised file format" in response.json()["detail"]

    def test_image_route_rejects_pdf_declared_as_jpeg(self, authenticated_client):
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            response = authenticated_client.post(
                "/api/admin/upload-image",
                files={"file": ("photo.jpg", PDF_BYTES, "image/jpeg")},
            )
        assert response.status_code == 400
        assert "not permitted here" in response.json()["detail"]

    def test_expense_receipt_route_rejects_html_declared_as_pdf(self, totp_authenticated_client):
        with patch("app.routes.expenses.settings") as mock_settings:
            mock_settings.is_dev = True
            response = totp_authenticated_client.post(
                "/api/admin/expenses/upload-receipt",
                files={"file": ("receipt.pdf", NOT_A_MEDIA_FILE, "application/pdf")},
            )
        assert response.status_code == 400

    def test_traversal_in_filename_does_not_reach_the_blob_key(self, authenticated_client):
        """A ../ filename must not survive into the stored object name."""
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            response = authenticated_client.post(
                "/api/admin/upload-image",
                files={"file": ("../../evil.jpg", JPEG_BYTES, "image/jpeg")},
            )
        assert response.status_code == 200
        url = response.json()["url"]
        assert ".." not in url
        assert "evil.jpg" in url

    def test_expense_receipt_echoes_sanitised_filename(self, totp_authenticated_client):
        with patch("app.routes.expenses.settings") as mock_settings:
            mock_settings.is_dev = True
            response = totp_authenticated_client.post(
                "/api/admin/expenses/upload-receipt",
                files={"file": ("../../../secret.pdf", PDF_BYTES, "application/pdf")},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["receipt_filename"] == "secret.pdf"
        assert ".." not in body["receipt_url"]

    def test_stored_content_type_comes_from_bytes_not_the_client(self, authenticated_client):
        """Declaring image/webp for PNG bytes stores image/png, not the lie."""
        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "test-bucket"
            response = authenticated_client.post(
                "/api/admin/upload-image",
                files={"file": ("x.webp", PNG_BYTES, "image/webp")},
            )
            assert response.status_code == 200
            blob = mock_storage.Client.return_value.bucket.return_value.blob.return_value
            _, kwargs = blob.upload_from_string.call_args
            assert kwargs["content_type"] == "image/png"
