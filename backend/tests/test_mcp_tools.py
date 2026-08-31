"""Tests for the MCP tool surface (app/mcp_server.py).

Tools are called directly as functions — FastMCP's @mcp.tool() registers and
returns the original callable, and _tool_errors translates domain errors into
structured dicts.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import mcp_server
from app.services import uploads


def _chain_db():
    mock = MagicMock()
    mock.collection.return_value = mock
    mock.document.return_value = mock
    mock.where.return_value = mock
    mock.order_by.return_value = mock
    mock.limit.return_value = mock
    mock.select.return_value = mock
    return mock


def _recipe_data(**over):
    data = {
        "title": "Test Recipe",
        "slug": "test-recipe",
        "description": "Desc",
        "ingredients": [{"item": "Water", "amount": "1", "unit": "cup"}],
        "instructions": [{"step": 1, "text": "Boil"}],
        "prep_time_minutes": 5,
        "cook_time_minutes": 5,
        "servings": 2,
        "difficulty": "easy",
        "categories": ["mains"],
        "image_url": "https://storage.googleapis.com/b/img.jpg",
        "published": False,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    data.update(over)
    return data


def _doc(id="doc-id", exists=True, **data):
    doc = MagicMock()
    doc.id = id
    doc.exists = exists
    doc.to_dict.return_value = _recipe_data(**data)
    return doc


@pytest.fixture
def db():
    mock = _chain_db()
    with (
        patch("app.mcp_server.get_db", return_value=mock),
        patch("app.services.recipes.cache"),
    ):
        yield mock


# ── create_recipe ─────────────────────────────────────────────────────────────

class TestCreateRecipeTool:
    def test_creates_draft(self, db):
        db.stream.return_value = iter([])
        db.id = "new-id"

        result = mcp_server.create_recipe(title="New Recipe")

        assert result["id"] == "new-id"
        assert result["slug"] == "new-recipe"
        written = db.set.call_args[0][0]
        assert written["created_via"] == "mcp"
        assert written["published"] is False

    def test_bad_ingredient_returns_field_errors(self, db):
        result = mcp_server.create_recipe(
            title="X", ingredients=[{"amount": "1", "unit": "cup"}]  # missing "item"
        )

        assert result["error"] == "validation_error"
        fields = [e["field"] for e in result["field_errors"]]
        assert "ingredients.0.item" in fields
        db.set.assert_not_called()

    def test_bad_difficulty_returns_field_error(self, db):
        result = mcp_server.create_recipe(title="X", difficulty="expert")

        assert result["error"] == "validation_error"
        assert any(e["field"] == "difficulty" for e in result["field_errors"])

    def test_slug_conflict_returns_pointer_not_duplicate(self, db):
        db.stream.return_value = iter([_doc(id="existing-id")])

        result = mcp_server.create_recipe(title="Test Recipe")

        assert result["error"] == "slug_conflict"
        assert result["existing"]["id"] == "existing-id"
        assert "update_recipe" in result["hint"]
        db.set.assert_not_called()

    def test_invalid_categories_lists_valid_ones(self, db):
        config_doc = MagicMock()
        config_doc.exists = True
        config_doc.to_dict.return_value = {"list": ["mains", "sides"]}
        db.get.return_value = config_doc

        result = mcp_server.create_recipe(title="X", categories=["desserts"])

        assert result["error"] == "invalid_categories"
        assert result["invalid"] == ["desserts"]
        assert result["valid_categories"] == ["mains", "sides"]


# ── update_recipe ─────────────────────────────────────────────────────────────

class TestUpdateRecipeTool:
    def test_no_fields_rejected(self, db):
        result = mcp_server.update_recipe(recipe_id="doc-id")
        assert result["error"] == "invalid_request"

    def test_updates_only_provided_fields(self, db):
        db.get.side_effect = [_doc(), _doc(title="New Title")]

        result = mcp_server.update_recipe(recipe_id="doc-id", title="New Title")

        assert result["updated_fields"] == ["title"]
        updates = db.update.call_args[0][0]
        assert updates["title"] == "New Title"
        assert updates["updated_via"] == "mcp"
        assert "published" not in updates
        assert "slug" not in updates

    def test_published_is_not_a_parameter(self):
        import inspect

        params = inspect.signature(mcp_server.update_recipe).parameters
        assert "published" not in params

    def test_invalid_clear_field_rejected(self, db):
        result = mcp_server.update_recipe(recipe_id="doc-id", clear_fields=["slug"])
        assert result["error"] == "invalid_request"
        assert "about" in result["message"]

    def test_clear_fields_nulls_optional_field(self, db):
        db.get.side_effect = [_doc(), _doc(image_url=None)]

        result = mcp_server.update_recipe(recipe_id="doc-id", clear_fields=["image_url"])

        assert "image_url" in result["updated_fields"]
        assert db.update.call_args[0][0]["image_url"] is None

    def test_not_found(self, db):
        db.get.return_value = _doc(exists=False)
        result = mcp_server.update_recipe(recipe_id="ghost", title="X")
        assert result["error"] == "not_found"


# ── publish / unpublish ───────────────────────────────────────────────────────

class TestPublishTools:
    def test_publish_blocks_incomplete_recipe(self, db):
        db.get.return_value = _doc(ingredients=[], instructions=[], components=None)

        result = mcp_server.publish_recipe(recipe_id="doc-id")

        assert result["error"] == "not_publishable"
        assert result["problems"]
        db.update.assert_not_called()

    def test_publish_returns_public_url_and_warnings(self, db):
        db.get.side_effect = [
            _doc(image_url=None),
            _doc(published=True, image_url=None),
        ]

        result = mcp_server.publish_recipe(recipe_id="doc-id")

        assert result["published"] is True
        assert result["public_url"].endswith("/recipes/test-recipe/")
        assert "Recipe has no image" in result["warnings"]

    def test_unpublish(self, db):
        db.get.side_effect = [_doc(published=True), _doc(published=False)]

        result = mcp_server.unpublish_recipe(recipe_id="doc-id")

        assert result["published"] is False


# ── delete_recipe ─────────────────────────────────────────────────────────────

class TestDeleteRecipeTool:
    def test_wrong_confirm_title_rejected(self, db):
        db.get.return_value = _doc()

        result = mcp_server.delete_recipe(recipe_id="doc-id", confirm_title="Wrong Title")

        assert result["error"] == "confirm_title_mismatch"
        assert result["expected_title"] == "Test Recipe"
        db.delete.assert_not_called()

    def test_published_recipe_refused(self, db):
        db.get.return_value = _doc(published=True)

        result = mcp_server.delete_recipe(recipe_id="doc-id", confirm_title="Test Recipe")

        assert result["error"] == "invalid_request"
        assert "unpublish" in result["message"]
        db.delete.assert_not_called()

    def test_draft_deleted_with_matching_title(self, db):
        db.get.return_value = _doc(published=False)

        result = mcp_server.delete_recipe(recipe_id="doc-id", confirm_title="Test Recipe")

        assert result["deleted"] is True
        db.delete.assert_called_once()


# ── list / get tools ──────────────────────────────────────────────────────────

class TestListAndGetTools:
    def test_list_categories(self, db):
        config_doc = MagicMock()
        config_doc.exists = True
        config_doc.to_dict.return_value = {"list": ["mains", "appetizers"]}
        db.get.return_value = config_doc

        assert mcp_server.list_categories() == {"categories": ["appetizers", "mains"]}

    def test_list_recipes_lightweight_summaries(self, db):
        db.stream.return_value = iter([_doc(id="a"), _doc(id="b", title="Pho", image_url=None)])

        result = mcp_server.list_recipes()

        assert result["count"] == 2
        assert result["recipes"][0]["id"] == "a"
        assert result["recipes"][0]["has_image"] is True
        assert result["recipes"][1]["has_image"] is False
        assert result["recipes"][0]["updated_at"] == "2026-01-01T00:00:00+00:00"

    def test_list_recipes_search_filters_by_title(self, db):
        db.stream.return_value = iter([_doc(id="a", title="Tom Yum"), _doc(id="b", title="Pho")])

        result = mcp_server.list_recipes(search="pho")

        assert result["count"] == 1
        assert result["recipes"][0]["id"] == "b"

    def test_get_recipe_by_id(self, db):
        db.get.return_value = _doc()
        result = mcp_server.get_recipe(recipe_id="doc-id")
        assert result["title"] == "Test Recipe"

    def test_get_recipe_by_slug(self, db):
        db.stream.return_value = iter([_doc()])
        result = mcp_server.get_recipe(slug="test-recipe")
        assert result["slug"] == "test-recipe"

    def test_get_recipe_requires_id_or_slug(self, db):
        result = mcp_server.get_recipe()
        assert result["error"] == "invalid_request"

    def test_get_recipe_not_found(self, db):
        db.get.return_value = _doc(exists=False)
        result = mcp_server.get_recipe(recipe_id="ghost")
        assert result["error"] == "not_found"


# ── request_image_upload ──────────────────────────────────────────────────────

class TestRequestImageUpload:
    def test_invalid_kind_rejected(self):
        result = mcp_server.request_image_upload("x.jpg", "image/jpeg", kind="document")
        assert result["error"] == "invalid_request"

    def test_invalid_content_type_rejected(self):
        result = mcp_server.request_image_upload("x.gif", "image/gif")
        assert result["error"] == "invalid_request"
        assert "image/jpeg" in result["message"]

    def test_pdf_allowed_for_receipts_only(self):
        rejected = mcp_server.request_image_upload("r.pdf", "application/pdf", kind="recipe_image")
        assert rejected["error"] == "invalid_request"

        accepted = mcp_server.request_image_upload("r.pdf", "application/pdf", kind="receipt")
        assert "error" not in accepted

    def test_dev_mode_returns_placeholder(self):
        result = mcp_server.request_image_upload("photo.jpg", "image/jpeg")

        assert result["upload_url"] == "dev://noop"
        assert "placehold.co" in result["final_url"]

    def test_production_returns_signed_url_and_curl(self):
        """The signed PUT must target the private staging bucket while
        final_url keeps pointing at the public one — a single shared bucket
        variable here would silently break either the upload or the
        eventual sanitize-on-attach lookup (gcs_blob_name matches final_url
        against the PUBLIC bucket name)."""
        signed = {
            "upload_url": "https://storage.googleapis.com/signed-put",
            "method": "PUT",
            "required_headers": {
                "Content-Type": "image/jpeg",
                "x-goog-content-length-range": "0,10485760",
            },
            "expires_in_seconds": 900,
        }
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("app.services.uploads.signed_put_url", return_value=signed) as signer,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = "staging-bucket"

            result = mcp_server.request_image_upload("my photo.jpg", "image/jpeg")

        assert result["final_url"].startswith("https://storage.googleapis.com/img-bucket/")
        assert result["final_url"].endswith("-my_photo.jpg")
        assert "curl -X PUT" in result["curl_example"]
        assert "x-goog-content-length-range" in result["curl_example"]
        bucket_arg, blob_name = signer.call_args[0][0], signer.call_args[0][1]
        assert bucket_arg == "staging-bucket"
        assert blob_name.endswith("-my_photo.jpg")

    def test_raises_in_production_when_staging_not_configured(self):
        """The public bucket alone being set is not enough for recipe_image.
        Signing a PUT against a None staging bucket must never happen — and
        this must not silently fall back to the dev-mode placeholder either,
        which would report a fake upload as if it succeeded. Cloud Build
        auto-deploys the backend on every push to main while Terraform is
        applied manually and separately, so a revision can genuinely reach
        production with this unset."""
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("app.services.uploads.signed_put_url") as signer,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "img-bucket"
            mock_settings.gcs_staging_bucket_name = None

            result = mcp_server.request_image_upload("photo.jpg", "image/jpeg")

        assert result["error"] == "internal"
        assert "upload_url" not in result  # not the dev-mode shape either
        signer.assert_not_called()

    def test_raises_in_production_when_public_bucket_not_configured(self):
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("app.services.uploads.signed_put_url") as signer,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = None
            mock_settings.gcs_staging_bucket_name = "staging-bucket"

            result = mcp_server.request_image_upload("photo.jpg", "image/jpeg")

        assert result["error"] == "internal"
        signer.assert_not_called()

    def test_raises_in_production_when_receipts_bucket_not_configured(self):
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("app.services.uploads.signed_put_url") as signer,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = None

            result = mcp_server.request_image_upload("r.pdf", "application/pdf", kind="receipt")

        assert result["error"] == "internal"
        signer.assert_not_called()

    def test_dev_mode_still_returns_placeholder_regardless_of_bucket_config(self):
        """is_dev is the only thing that should ever produce the placeholder
        response — confirmed here with buckets unset, which used to also
        trigger it via the old `is_dev or missing_bucket` check."""
        # settings.is_dev is True in the test environment by default
        result = mcp_server.request_image_upload("photo.jpg", "image/jpeg")

        assert result["upload_url"] == "dev://noop"
        assert "placehold.co" in result["final_url"]

    def test_production_receipt_goes_to_private_bucket(self):
        signed = {"upload_url": "u", "method": "PUT", "required_headers": {}, "expires_in_seconds": 900}
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("app.services.uploads.signed_put_url", return_value=signed) as signer,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"
            # Deliberately not set — receipts must never reference staging.
            mock_settings.gcs_staging_bucket_name = None

            result = mcp_server.request_image_upload("r.pdf", "application/pdf", kind="receipt")

        assert result["final_url"].startswith("gs://receipts-bucket/receipts/")
        assert signer.call_args[0][0] == "receipts-bucket"


# ── upload_image_from_url ─────────────────────────────────────────────────────

class TestUploadImageFromUrl:
    def test_returns_image_url(self):
        with patch(
            "app.services.uploads.fetch_image_to_gcs",
            return_value="https://storage.googleapis.com/b/uuid-x.jpg",
        ):
            result = mcp_server.upload_image_from_url("https://example.com/x.jpg")

        assert result == {"image_url": "https://storage.googleapis.com/b/uuid-x.jpg"}

    def test_fetch_errors_surface_as_invalid_request(self):
        with patch(
            "app.services.uploads.fetch_image_to_gcs",
            side_effect=ValueError("Only https:// URLs are allowed"),
        ):
            result = mcp_server.upload_image_from_url("http://example.com/x.jpg")

        assert result["error"] == "invalid_request"
        assert "https" in result["message"]

    def test_storage_misconfiguration_surfaces_as_internal_not_invalid_request(self):
        """A missing bucket is a server problem, not something the caller
        could fix by adjusting its input — distinct from the ValueError case
        above, which _tool_errors reports as invalid_request."""
        with patch(
            "app.services.uploads.fetch_image_to_gcs",
            side_effect=uploads.StorageNotConfiguredError("GCS_BUCKET_NAME is not configured"),
        ):
            result = mcp_server.upload_image_from_url("https://example.com/x.jpg")

        assert result["error"] == "internal"


# ── create_expense receipt_url ────────────────────────────────────────────────

class TestCreateExpenseReceiptUrl:
    _BASE = dict(
        date="2026-03-08",
        vendor="Test Market",
        items=[{"name": "Chicken", "quantity": 1, "unit_price": 1000, "total_price": 1000}],
        raw_subtotal=1000,
        raw_tax=80,
        raw_total=1080,
    )

    def test_invalid_category_rejected(self, db):
        result = mcp_server.create_expense(**self._BASE, category="snacks")
        assert result["error"] == "invalid_request"

    def test_non_gcs_receipt_url_rejected(self, db):
        with patch("app.mcp_server.settings") as mock_settings:
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"

            result = mcp_server.create_expense(
                **self._BASE, receipt_url="https://evil.example/r.pdf"
            )

        assert result["error"] == "invalid_request"
        assert "request_image_upload" in result["message"]
        db.set.assert_not_called()
        db.transaction.return_value.set.assert_not_called()

    def test_missing_blob_rejected(self, db):
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("google.cloud.storage.Client") as mock_client,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"
            mock_client.return_value.bucket.return_value.get_blob.return_value = None

            result = mcp_server.create_expense(
                **self._BASE, receipt_url="gs://receipts-bucket/receipts/uuid-r.pdf"
            )

        assert result["error"] == "invalid_request"
        assert "PUT" in result["message"]

    def test_valid_receipt_url_attached(self, db):
        blob = MagicMock()
        blob.content_type = "application/pdf"
        uuid_name = "receipts/123e4567-e89b-42d3-a456-426614174000-receipt.pdf"
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("google.cloud.storage.Client") as mock_client,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"
            mock_client.return_value.bucket.return_value.get_blob.return_value = blob

            result = mcp_server.create_expense(
                **self._BASE, receipt_url=f"gs://receipts-bucket/{uuid_name}"
            )

        assert result["receipt_uploaded"] is True
        # The expense doc + its first revision now commit inside one
        # Firestore transaction (transaction.set(doc_ref, data), then the
        # revision's own transaction.set(...) inside
        # _write_revision_in_transaction) — db.transaction() is a fresh
        # mock, distinct from db itself, so the write lands on
        # db.transaction.return_value.set, not db.set. First call is the
        # expense doc (transaction.set(doc_ref, data) — data is positional
        # arg index 1); the revision write is the second call.
        written = db.transaction.return_value.set.call_args_list[0][0][1]
        assert written["receipt_filename"] == "receipt.pdf"
        assert written["receipt_content_type"] == "application/pdf"

    def test_no_receipt_is_fine(self, db):
        result = mcp_server.create_expense(**self._BASE)
        assert result["receipt_uploaded"] is False
        assert result["item_count"] == 1


# ── publish_instagram_post ────────────────────────────────────────────────────

class TestPublishInstagramPost:
    def test_dev_mode_returns_no_op(self):
        # settings.is_dev is True in the test environment
        result = mcp_server.publish_instagram_post(
            "https://storage.googleapis.com/b/img.jpg", "Caption"
        )
        assert result["id"] == "dev-ig-media"
        assert result["message"] == "Posted to Instagram."

    def test_instagram_error_maps_to_instagram_dict(self):
        with patch("app.mcp_server.instagram.publish_image") as mock_pub:
            mock_pub.side_effect = mcp_server.instagram.InstagramError("API failure")
            result = mcp_server.publish_instagram_post("https://example.com/img.jpg")
        assert result["error"] == "instagram"
        assert "API failure" in result["message"]

    def test_instagram_auth_error_maps_to_instagram_auth_dict(self):
        with patch("app.mcp_server.instagram.publish_image") as mock_pub:
            mock_pub.side_effect = mcp_server.instagram.InstagramError(
                "bad token", auth=True
            )
            result = mcp_server.publish_instagram_post("https://example.com/img.jpg")
        assert result["error"] == "instagram_auth"

    def test_value_error_maps_to_invalid_request(self):
        with patch("app.mcp_server.instagram.publish_image") as mock_pub:
            mock_pub.side_effect = ValueError("image_url must be a public https URL")
            result = mcp_server.publish_instagram_post("http://not-https.com/img.jpg")
        assert result["error"] == "invalid_request"
        assert "https" in result["message"]


# ── publish_recipe_to_instagram ───────────────────────────────────────────────

class TestPublishRecipeToInstagram:
    def test_recipe_with_image_returns_permalink(self, db):
        db.stream.return_value = iter([_doc()])
        with patch("app.mcp_server.instagram.publish_image") as mock_pub:
            mock_pub.return_value = {
                "id": "ig-123",
                "permalink": "https://www.instagram.com/p/abc/",
            }
            result = mcp_server.publish_recipe_to_instagram(slug="test-recipe")
        assert result["id"] == "ig-123"
        assert result["slug"] == "test-recipe"
        assert result["title"] == "Test Recipe"
        assert result["message"] == "Posted to Instagram."

    def test_auto_caption_contains_title_and_link(self, db):
        db.stream.return_value = iter([_doc()])
        with (
            patch("app.mcp_server.instagram.publish_image") as mock_pub,
            patch("app.mcp_server.settings") as mock_settings,
        ):
            mock_settings.frontend_url = "https://madeforseconds.com"
            mock_pub.return_value = {"id": "ig-123", "permalink": ""}
            mcp_server.publish_recipe_to_instagram(slug="test-recipe")
        caption = mock_pub.call_args[0][1]
        sections = caption.split("\n\n")
        assert sections[0] == "Test Recipe"
        assert sections[2] == "Full recipe: https://madeforseconds.com/recipes/test-recipe/"
        assert sections[3] == "#madeforseconds #mains"

    def test_explicit_caption_overrides_auto_caption(self, db):
        db.stream.return_value = iter([_doc()])
        with patch("app.mcp_server.instagram.publish_image") as mock_pub:
            mock_pub.return_value = {"id": "ig-123", "permalink": ""}
            mcp_server.publish_recipe_to_instagram(
                slug="test-recipe", caption="My custom caption"
            )
        caption = mock_pub.call_args[0][1]
        assert caption == "My custom caption"

    def test_recipe_without_image_returns_invalid_request(self, db):
        db.stream.return_value = iter([_doc(image_url=None)])
        result = mcp_server.publish_recipe_to_instagram(slug="test-recipe")
        assert result["error"] == "invalid_request"
        assert "image" in result["message"]

    def test_unknown_slug_returns_not_found(self, db):
        db.stream.return_value = iter([])
        result = mcp_server.publish_recipe_to_instagram(slug="nonexistent")
        assert result["error"] == "not_found"
