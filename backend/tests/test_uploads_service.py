"""Unit tests for GCS upload helpers and Cloud Run-safe signed URLs."""

from unittest.mock import MagicMock, patch

import pytest
from google.auth import credentials as google_auth_credentials

from app.services import uploads

from conftest import _gps_tag_count, _image_with_metadata


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
        original = _image_with_metadata("JPEG")
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
            patch("app.services.uploads.settings") as mock_settings,
            patch("app.services.uploads.storage") as mock_storage,
        ):
            _mock_response(mock_httpx, chunks=[original])
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"

            url = uploads.fetch_image_to_gcs("https://example.com/photos/dish.jpg")

        assert url.startswith("https://storage.googleapis.com/img-bucket/")
        assert url.endswith("-dish.jpg")
        blob = mock_storage.Client.return_value.bucket.return_value.blob.return_value
        blob.upload_from_string.assert_called_once()
        uploaded, kwargs = blob.upload_from_string.call_args
        assert kwargs["content_type"] == "image/jpeg"
        # The point of this fix: fetched bytes are sanitized before upload,
        # not passed through as-fetched — the raw response body carried GPS.
        assert uploaded[0] != original
        assert _gps_tag_count(uploaded[0]) == 0

    def test_raises_when_fetched_image_unparseable(self):
        """A declared image/jpeg Content-Type is attacker-controlled — the
        same principle sniff_content_type/verify_upload_type already apply to
        the backend-mediated upload routes. Bytes that don't actually parse
        as an image must not reach the public bucket."""
        with (
            patch("socket.getaddrinfo", return_value=_PUBLIC_ADDR),
            patch("app.services.uploads.httpx") as mock_httpx,
            patch("app.services.uploads.settings") as mock_settings,
            patch("app.services.uploads.storage") as mock_storage,
        ):
            # Valid JPEG signature, truncated — sniffs as image/jpeg, then
            # fails to parse as a real one.
            _mock_response(mock_httpx, chunks=[b"\xff\xd8\xff\xe0" + b"\x00" * 16])
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"

            with pytest.raises(ValueError, match="could not be processed"):
                uploads.fetch_image_to_gcs("https://example.com/broken.jpg")

        mock_storage.Client.assert_not_called()

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


# ── sanitize_public_image_blob / sanitize_recipe_image ─────────────────────────
# https://storage.googleapis.com/{bucket}/{blob} is the URL shape gcs_blob_name
# parses; the fixtures below build it to match img-bucket.

def _mock_blob(data: bytes, cache_control=None):
    blob = MagicMock()
    blob.download_as_bytes.return_value = data
    blob.cache_control = cache_control
    return blob


class TestSanitizePublicImageBlob:
    def test_noop_in_dev_mode(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = True
            mock_settings.gcs_bucket_name = "img-bucket"
            assert uploads.sanitize_public_image_blob("x.jpg") is False
        mock_storage.Client.assert_not_called()

    def test_noop_when_bucket_not_configured(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = ""
            assert uploads.sanitize_public_image_blob("x.jpg") is False
        mock_storage.Client.assert_not_called()

    def test_raises_when_object_does_not_exist(self):
        """A blob name that should be ours but isn't there is a broken
        reference, not a silent no-op — the old behaviour returned False and
        the caller had no way to tell "nothing to do" from "something's wrong".
        Staging explicitly unconfigured here, so this exercises the "nothing
        to promote either" fallthrough deterministically rather than by luck
        of an unset mock attribute being truthy."""
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = None
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = None

            with pytest.raises(uploads.ImageSanitizationError, match="does not exist"):
                uploads.sanitize_public_image_blob("missing.jpg")

    def test_raises_when_get_blob_errors(self):
        """A permission error (e.g. the SA lacking storage.objects.get/update)
        must not be swallowed — the recipe save has to know sanitization
        failed rather than silently publishing the unstripped image."""
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_storage.Client.return_value.bucket.return_value.get_blob.side_effect = (
                Exception("403 Forbidden")
            )

            with pytest.raises(uploads.ImageSanitizationError, match="could not reach GCS"):
                uploads.sanitize_public_image_blob("x.jpg")

    def test_raises_when_upload_back_errors(self):
        """The overwrite step — the one that actually needs delete/update
        permission, not just objectCreator. If this fails the object is left
        exactly as it was: still public, still carrying its metadata."""
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            blob = _mock_blob(_image_with_metadata("JPEG"))
            blob.upload_from_string.side_effect = Exception("403 Forbidden")
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = blob

            with pytest.raises(uploads.ImageSanitizationError, match="could not write"):
                uploads.sanitize_public_image_blob("x.jpg")

    def test_raises_on_unparseable_bytes(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            # Valid JPEG signature, but truncated — sniffs as image/jpeg, then
            # fails to parse as a real one.
            blob = _mock_blob(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = blob

            with pytest.raises(uploads.ImageSanitizationError, match="could not parse"):
                uploads.sanitize_public_image_blob("x.jpg")

    def test_returns_false_for_unstrippable_type_without_raising(self):
        """HEIC/PDF aren't allowed recipe-image types, so finding one here is
        surprising but not itself a sanitization failure — nothing claimed it
        would be cleaned."""
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            blob = _mock_blob(b"%PDF-1.4\n" + b"\x00" * 16)
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = blob

            assert uploads.sanitize_public_image_blob("x.pdf") is False
            blob.upload_from_string.assert_not_called()

    def test_rewrites_when_metadata_present(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            blob = _mock_blob(_image_with_metadata("JPEG"))
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = blob

            assert uploads.sanitize_public_image_blob("x.jpg") is True
            blob.upload_from_string.assert_called_once()
            assert blob.cache_control == uploads.PUBLIC_IMAGE_CACHE_CONTROL

    def test_returns_false_when_already_clean(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            clean = uploads.strip_image_metadata(_image_with_metadata("JPEG"), "image/jpeg")
            blob = _mock_blob(clean, cache_control=uploads.PUBLIC_IMAGE_CACHE_CONTROL)
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = blob

            assert uploads.sanitize_public_image_blob("x.jpg") is False
            blob.upload_from_string.assert_not_called()


# ── Promotion from the private staging bucket ──────────────────────────────────
# The signed-PUT recipe-image flow lands bytes in a private staging bucket the
# backend never sees at upload time — sanitize_public_image_blob's "blob is
# None" branch is what promotes them into the public bucket on attach. These
# tests need a mock that distinguishes which bucket .bucket(name) was called
# with, unlike the plain shared mock above, since promotion genuinely talks to
# two different buckets in one call.

def _two_bucket_client(mock_storage, *, public_blob=None, staging_blob=None):
    """Wire mock_storage.Client() so .bucket("img-bucket") and
    .bucket("staging-bucket") return independently controllable get_blob
    results, matching how the real client is keyed by bucket name."""
    buckets = {"img-bucket": MagicMock(), "staging-bucket": MagicMock()}
    buckets["img-bucket"].get_blob.return_value = public_blob
    buckets["staging-bucket"].get_blob.return_value = staging_blob
    mock_storage.Client.return_value.bucket.side_effect = lambda name: buckets[name]
    return buckets


class TestPromoteStagedImage:
    def test_promotes_and_deletes_staged_copy(self):
        staged = _mock_blob(_image_with_metadata("JPEG"))
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"
            buckets = _two_bucket_client(mock_storage, public_blob=None, staging_blob=staged)

            assert uploads.sanitize_public_image_blob("x.jpg") is True

        public_blob = buckets["img-bucket"].blob.return_value
        public_blob.upload_from_string.assert_called_once()
        uploaded, kwargs = public_blob.upload_from_string.call_args
        assert kwargs["content_type"] == "image/jpeg"
        assert _gps_tag_count(uploaded[0]) == 0
        assert public_blob.cache_control == uploads.PUBLIC_IMAGE_CACHE_CONTROL
        staged.delete.assert_called_once()

    def test_falls_through_to_not_found_when_staging_not_configured(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = None
            _two_bucket_client(mock_storage, public_blob=None, staging_blob=None)

            with pytest.raises(uploads.ImageSanitizationError, match="does not exist"):
                uploads.sanitize_public_image_blob("x.jpg")

    def test_falls_through_to_not_found_when_staged_object_missing_too(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"
            _two_bucket_client(mock_storage, public_blob=None, staging_blob=None)

            with pytest.raises(uploads.ImageSanitizationError, match="does not exist in img-bucket or in staging"):
                uploads.sanitize_public_image_blob("x.jpg")

    def test_raises_when_staged_content_is_wrong_type(self):
        """The signed PUT's declared Content-Type is not verified against the
        actual bytes by GCS — sniffing at promotion time is the only backstop
        against a spoofed header landing arbitrary bytes in a public bucket."""
        staged = _mock_blob(b"%PDF-1.4\n" + b"\x00" * 16)
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"
            buckets = _two_bucket_client(mock_storage, public_blob=None, staging_blob=staged)

            with pytest.raises(uploads.ImageSanitizationError, match="not a recognised recipe-image type"):
                uploads.sanitize_public_image_blob("x.jpg")

        buckets["img-bucket"].blob.return_value.upload_from_string.assert_not_called()

    def test_raises_when_staged_bytes_unparseable(self):
        staged = _mock_blob(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"
            _two_bucket_client(mock_storage, public_blob=None, staging_blob=staged)

            with pytest.raises(uploads.ImageSanitizationError, match="could not parse staged"):
                uploads.sanitize_public_image_blob("x.jpg")

    def test_delete_failure_after_promotion_does_not_fail_the_call(self):
        """The public write already succeeded — a stray staged copy is the
        lifecycle rule's problem, not an attachment failure."""
        staged = _mock_blob(_image_with_metadata("JPEG"))
        staged.delete.side_effect = Exception("403 Forbidden")
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"
            buckets = _two_bucket_client(mock_storage, public_blob=None, staging_blob=staged)

            assert uploads.sanitize_public_image_blob("x.jpg") is True

        buckets["img-bucket"].blob.return_value.upload_from_string.assert_called_once()

    def test_recheck_public_bucket_closes_promotion_race(self):
        """Two update_recipe calls can race on the same freshly-staged
        image_url. If a concurrent call already promoted (and deleted the
        staged copy of) this blob_name between our first get_blob and now,
        the recheck must find it and return False rather than raise."""
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"
            buckets = _two_bucket_client(mock_storage, public_blob=None, staging_blob=None)
            # First two calls (initial check, then promotion's own lookup)
            # see nothing; the recheck call is the one that finds the
            # concurrently-promoted object.
            already_promoted = _mock_blob(b"irrelevant", cache_control=uploads.PUBLIC_IMAGE_CACHE_CONTROL)
            buckets["img-bucket"].get_blob.side_effect = [None, already_promoted]

            assert uploads.sanitize_public_image_blob("x.jpg") is False

        buckets["img-bucket"].blob.return_value.upload_from_string.assert_not_called()


class TestSanitizeRecipeImagePropagation:
    def test_propagates_sanitization_error_for_own_bucket_url(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_storage.Client.return_value.bucket.return_value.get_blob.return_value = None

            with pytest.raises(uploads.ImageSanitizationError):
                uploads.sanitize_recipe_image("https://storage.googleapis.com/img-bucket/missing.jpg")

    def test_foreign_url_never_reaches_gcs(self):
        with patch("app.services.uploads.settings") as mock_settings, \
             patch("app.services.uploads.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            assert uploads.sanitize_recipe_image("https://placehold.co/x.jpg") is False
            assert uploads.sanitize_recipe_image(None) is False

        mock_storage.Client.assert_not_called()
