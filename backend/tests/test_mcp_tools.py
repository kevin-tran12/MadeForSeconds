"""Tests for the MCP tool surface (app/mcp_server.py).

Tools are called directly as functions — FastMCP's @mcp.tool() registers and
returns the original callable, and _tool_errors translates domain errors into
structured dicts.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import mcp_server


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

            result = mcp_server.request_image_upload("my photo.jpg", "image/jpeg")

        assert result["final_url"].startswith("https://storage.googleapis.com/img-bucket/")
        assert result["final_url"].endswith("-my_photo.jpg")
        assert "curl -X PUT" in result["curl_example"]
        assert "x-goog-content-length-range" in result["curl_example"]
        blob_name = signer.call_args[0][1]
        assert blob_name.endswith("-my_photo.jpg")

    def test_production_receipt_goes_to_private_bucket(self):
        signed = {"upload_url": "u", "method": "PUT", "required_headers": {}, "expires_in_seconds": 900}
        with (
            patch("app.mcp_server.settings") as mock_settings,
            patch("app.services.uploads.signed_put_url", return_value=signed),
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"

            result = mcp_server.request_image_upload("r.pdf", "application/pdf", kind="receipt")

        assert result["final_url"].startswith("gs://receipts-bucket/receipts/")


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
        written = db.set.call_args_list[0][0][0]
        assert written["receipt_filename"] == "receipt.pdf"
        assert written["receipt_content_type"] == "application/pdf"

    def test_no_receipt_is_fine(self, db):
        result = mcp_server.create_expense(**self._BASE)
        assert result["receipt_uploaded"] is False
        assert result["item_count"] == 1
