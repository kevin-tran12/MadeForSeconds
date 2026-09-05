"""Tests for the MCP tool surface (app/mcp_server/).

Tools are called directly as functions — the mcp SDK 2.x's @mcp.tool() registers
and returns the original callable, and wrapper.mcp_tool translates domain
errors into structured dicts.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import mcp_server
from app.mcp_server.tools import expenses as expenses_tools
from app.services import instagram, uploads


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
def db(mcp_db):
    """The pre-split fixture name, kept so every test below reads unchanged.

    mcp_db (conftest.py) patches get_db in each of the four tools/*.py
    modules that call it, plus the recipe and ingredient services' own
    cache — the same combination this fixture's own single
    app.mcp_server.get_db patch provided before the mcp_server package
    split.
    """
    return mcp_db


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


# ── list_recipes cursor pagination (S7) ─────────────────────────────────────

class TestListRecipesPagination:
    def test_first_page_without_cursor_sets_next_cursor_when_more_exist(self, db):
        # limit=2 -> fetch_limit=3; 3 docs returned means a 3rd page exists.
        docs = [
            _doc(id=f"r{i}", created_at=datetime(2026, 1, 10 - i, tzinfo=timezone.utc))
            for i in range(3)
        ]
        db.stream.return_value = iter(docs)

        result = mcp_server.list_recipes(limit=2)

        assert [r["id"] for r in result["recipes"]] == ["r0", "r1"]
        assert result["exhausted"] is False
        assert result["next_cursor"] == "2026-01-09T00:00:00+00:00"  # r1's created_at

    def test_a_two_page_walk_yields_disjoint_ids_and_ends_with_no_cursor(self, db):
        page1 = [_doc(id=f"r{i}", created_at=datetime(2026, 1, 10 - i, tzinfo=timezone.utc)) for i in range(3)]
        page2 = [_doc(id="r3", created_at=datetime(2026, 1, 6, tzinfo=timezone.utc))]
        db.stream.side_effect = [iter(page1), iter(page2)]

        first = mcp_server.list_recipes(limit=2)
        assert [r["id"] for r in first["recipes"]] == ["r0", "r1"]
        assert first["next_cursor"] is not None

        second = mcp_server.list_recipes(limit=2, cursor=first["next_cursor"])
        assert [r["id"] for r in second["recipes"]] == ["r3"]
        assert second["next_cursor"] is None
        assert second["exhausted"] is True

        first_ids = {r["id"] for r in first["recipes"]}
        second_ids = {r["id"] for r in second["recipes"]}
        assert first_ids.isdisjoint(second_ids)

    def test_invalid_cursor_is_rejected_before_any_query(self, db):
        result = mcp_server.list_recipes(cursor="not-a-real-cursor")

        assert result["error"] == "invalid_request"
        db.stream.assert_not_called()

    def test_search_finds_a_match_only_on_the_second_scanned_page(self, db):
        # limit=2 -> page_fetch_limit = min(2*3, 100) = 6. A full, non-matching
        # first page must not stop the scan — it should continue to page 2.
        page1 = [
            _doc(id=f"a{i}", title=f"Tom Yum {i}", created_at=datetime(2026, 1, 20 - i, tzinfo=timezone.utc))
            for i in range(6)
        ]
        page2 = [_doc(id="b0", title="Pho", created_at=datetime(2026, 1, 13, tzinfo=timezone.utc))]
        db.stream.side_effect = [iter(page1), iter(page2)]

        result = mcp_server.list_recipes(search="pho", limit=2)

        assert result["count"] == 1
        assert result["recipes"][0]["id"] == "b0"
        assert db.stream.call_count == 2

    def test_search_marks_exhausted_when_the_scanned_page_is_short(self, db):
        docs = [_doc(id="a0", title="Pho", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))]
        db.stream.return_value = iter(docs)  # fewer than page_fetch_limit -> exhausted

        result = mcp_server.list_recipes(search="pho", limit=5)

        assert result["exhausted"] is True
        assert result["next_cursor"] is None


# ── _resolve_recipe_slugs chunking (S7) ─────────────────────────────────────

class TestResolveRecipeSlugsChunking:
    def test_31_slugs_issues_two_where_calls(self, db):
        db.stream.side_effect = [iter([]), iter([])]

        expenses_tools._resolve_recipe_slugs([f"slug-{i}" for i in range(31)])

        assert db.where.call_count == 2

    def test_more_than_100_distinct_slugs_is_rejected(self, db):
        with pytest.raises(ValueError, match="too many distinct recipe_slug"):
            expenses_tools._resolve_recipe_slugs([f"slug-{i}" for i in range(101)])
        db.where.assert_not_called()

    def test_duplicate_slugs_are_deduplicated_before_chunking(self, db):
        db.stream.return_value = iter([])

        expenses_tools._resolve_recipe_slugs(["same-slug"] * 50)

        # 50 duplicates collapse to 1 distinct slug -> a single chunk.
        assert db.where.call_count == 1

    def test_results_from_every_chunk_are_merged(self, db):
        chunk1_doc = _doc(id="r1", slug="slug-0")
        chunk2_doc = _doc(id="r2", slug="slug-30")
        db.stream.side_effect = [iter([chunk1_doc]), iter([chunk2_doc])]

        result = expenses_tools._resolve_recipe_slugs(
            [f"slug-{i}" for i in range(30)] + ["slug-30"]
        )

        assert result["slug-0"] == ("r1", "Test Recipe")
        assert result["slug-30"] == ("r2", "Test Recipe")

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
            patch("app.mcp_server.tools.images.settings") as mock_settings,
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
            patch("app.mcp_server.tools.images.settings") as mock_settings,
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
            patch("app.mcp_server.tools.images.settings") as mock_settings,
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
            patch("app.mcp_server.tools.images.settings") as mock_settings,
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
            patch("app.mcp_server.tools.images.settings") as mock_settings,
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
        above, which mcp_tool reports as invalid_request."""
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
        # resolve_receipt_url now lives in services/uploads.py (shared with
        # the HTTP route), so its own `settings` binding is what needs
        # patching — app.mcp_server.settings would no longer reach it.
        with patch("app.services.uploads.settings") as mock_settings:
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"

            result = mcp_server.create_expense(
                **self._BASE, receipt_url="https://evil.example/r.pdf"
            )

        assert result["error"] == "invalid_request"
        assert "receipt_url" in result["message"]
        db.set.assert_not_called()
        db.transaction.return_value.set.assert_not_called()

    def test_missing_blob_rejected(self, db):
        with (
            patch("app.services.uploads.settings") as mock_settings,
            patch("google.cloud.storage.Client") as mock_client,
        ):
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "receipts-bucket"
            mock_client.return_value.bucket.return_value.get_blob.return_value = None

            result = mcp_server.create_expense(
                **self._BASE, receipt_url="gs://receipts-bucket/receipts/uuid-r.pdf"
            )

        assert result["error"] == "invalid_request"
        assert "upload" in result["message"]

    def test_valid_receipt_url_attached(self, db):
        blob = MagicMock()
        blob.content_type = "application/pdf"
        uuid_name = "receipts/123e4567-e89b-42d3-a456-426614174000-receipt.pdf"
        with (
            patch("app.services.uploads.settings") as mock_settings,
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

    def test_changed_by_defaults_to_mcp_without_a_client_id(self, db):
        """S8: no OAuth context in this test environment, matching dev
        mode's own unauthenticated MCP server — changed_by falls back to
        the bare "mcp" literal, not a crash or an empty string."""
        mcp_server.create_expense(**self._BASE)
        revision = db.transaction.return_value.set.call_args_list[1][0][1]
        assert revision["changed_by"] == "mcp"

    def test_changed_by_carries_the_client_id_when_authenticated(self, db):
        from types import SimpleNamespace
        with patch(
            "app.mcp_server.wrapper.get_access_token",
            return_value=SimpleNamespace(client_id="claude-code", subject=None),
        ):
            mcp_server.create_expense(**self._BASE)
        revision = db.transaction.return_value.set.call_args_list[1][0][1]
        assert revision["changed_by"] == "mcp:claude-code"


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
        with patch("app.services.instagram.publish_image") as mock_pub:
            mock_pub.side_effect = instagram.InstagramError("API failure")
            result = mcp_server.publish_instagram_post("https://example.com/img.jpg")
        assert result["error"] == "instagram"
        assert "API failure" in result["message"]

    def test_instagram_auth_error_maps_to_instagram_auth_dict(self):
        with patch("app.services.instagram.publish_image") as mock_pub:
            mock_pub.side_effect = instagram.InstagramError(
                "bad token", auth=True
            )
            result = mcp_server.publish_instagram_post("https://example.com/img.jpg")
        assert result["error"] == "instagram_auth"

    def test_value_error_maps_to_invalid_request(self):
        with patch("app.services.instagram.publish_image") as mock_pub:
            mock_pub.side_effect = ValueError("image_url must be a public https URL")
            result = mcp_server.publish_instagram_post("http://not-https.com/img.jpg")
        assert result["error"] == "invalid_request"
        assert "https" in result["message"]


# ── publish_recipe_to_instagram ───────────────────────────────────────────────

class TestPublishRecipeToInstagram:
    def test_recipe_with_image_returns_permalink(self, db):
        db.stream.return_value = iter([_doc()])
        with patch("app.services.instagram.publish_image") as mock_pub:
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
            patch("app.services.instagram.publish_image") as mock_pub,
            patch("app.mcp_server.tools.social.settings") as mock_settings,
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
        with patch("app.services.instagram.publish_image") as mock_pub:
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


# ── sous_chef_notes via MCP ───────────────────────────────────────────────────

class TestSousChefNotesTools:
    def test_create_stores_notes(self, db):
        db.stream.return_value = iter([])
        db.id = "new-id"
        mcp_server.create_recipe(title="Laksa", sous_chef_notes="toast the rempah")
        assert db.set.call_args[0][0]["sous_chef_notes"] == "toast the rempah"

    def test_update_sets_and_clears_notes(self, db):
        db.get.return_value = _doc()
        result = mcp_server.update_recipe(recipe_id="doc-id", sous_chef_notes="new")
        assert "sous_chef_notes" in result["updated_fields"]
        assert db.update.call_args[0][0]["sous_chef_notes"] == "new"
        mcp_server.update_recipe(recipe_id="doc-id", clear_fields=["sous_chef_notes"])
        assert db.update.call_args[0][0]["sous_chef_notes"] is None

    def test_get_recipe_returns_the_owner_view(self, db):
        db.get.return_value = _doc(sous_chef_notes="use day-old rice")
        assert mcp_server.get_recipe(recipe_id="doc-id")["sous_chef_notes"] == "use day-old rice"

# ── Social kit ────────────────────────────────────────────────────────────────

def _pages_doc(exists=True, **data):
    doc = MagicMock()
    doc.exists = exists
    doc.to_dict.return_value = data
    return doc


class TestSocialKit:
    def test_defaults_apply_when_no_social_page_exists(self, db):
        db.get.side_effect = [_doc(id="r1", published=True, categories=["Mains"], labels=["Chicken Rice"]), _pages_doc(exists=False)]
        with patch("app.mcp_server.tools.social.settings") as s:
            s.frontend_url = "https://madeforseconds.com/"
            kit = mcp_server.get_social_kit(recipe_id="r1")
        assert kit["recipe"]["url"] == "https://madeforseconds.com/recipes/test-recipe/"
        assert kit["recipe"]["key_ingredients"] == ["Water"]
        assert kit["hashtags"]["brand"][0] == "madeforseconds"
        assert kit["hashtags"]["recipe"] == ["mains", "chickenrice"]
        assert "Authentic" in kit["brand_voice"]["tone"]
        assert kit["platforms"]["instagram"]["max_hashtags"] == 30
        assert kit["platforms"]["tiktok"]["note"].startswith("Draft only")
        assert any("approval" in step for step in kit["workflow"])

    def test_owner_overrides_from_the_social_page_win_and_tags_are_normalised(self, db):
        db.get.side_effect = [
            _doc(id="r1", published=True),
            _pages_doc(tone="Cheeky and warm", hashtags_brand="MadeForSeconds, #Home Cooking, madeforseconds, ", do=""),
        ]
        with patch("app.mcp_server.tools.social.settings") as s:
            s.frontend_url = "https://madeforseconds.com"
            kit = mcp_server.get_social_kit(slug="test-recipe") if False else mcp_server.get_social_kit(recipe_id="r1")
        assert kit["brand_voice"]["tone"] == "Cheeky and warm"
        assert kit["brand_voice"]["do"].startswith("Lead with the dish")  # blank override falls back
        assert kit["hashtags"]["brand"] == ["madeforseconds", "homecooking"]

    def test_unknown_recipe_is_a_structured_error(self, db):
        db.get.return_value = _doc(exists=False)
        result = mcp_server.get_social_kit(recipe_id="ghost")
        assert "error" in result

    def test_social_status_passes_through_the_refresh_record(self, db):
        with patch("app.services.social.status", return_value={"instagram": {"configured": True, "expires_at": "2026-11-01T00:00:00+00:00"}}):
            result = mcp_server.social_status()
        assert result["platforms"]["instagram"]["expires_at"].startswith("2026-11-01")
        assert "1st and the 15th" in result["refresh_schedule"]


# ── Ingredient knowledge tools ──────────────────────────────────────────────

def _profile_doc(slug, name, exists=True, **over):
    doc = MagicMock()
    doc.id = slug
    doc.exists = exists
    data = {
        "name": name, "aliases": [], "what_it_is": "x", "role": "", "substitutions": "",
        "buying": "", "storage": "", "mistakes": "", "allergens": "",
    }
    data.update(over)
    doc.to_dict.return_value = data
    return doc


def _published_recipe_doc(slug, title, ingredient_items):
    doc = MagicMock()
    doc.id = slug
    doc.to_dict.return_value = {
        "slug": slug, "title": title, "published": True,
        "ingredients": [{"item": item} for item in ingredient_items],
        "components": [], "secrets": [], "about": "", "sous_chef_notes": "",
        "created_at": None, "updated_at": None,
    }
    return doc


class TestIngredientTools:
    @pytest.mark.parametrize("tool_call", [
        lambda: mcp_server.get_ingredient(slug="pork/belly"),
        lambda: mcp_server.upsert_ingredient(name="X", slug="pork/belly", what_it_is="y"),
        lambda: mcp_server.delete_ingredient("pork/belly"),
    ], ids=["get_ingredient", "upsert_ingredient", "delete_ingredient"])
    def test_every_slug_taking_tool_rejects_a_path_injection_shaped_slug(self, db, tool_call):
        """services/ingredients.py's _require_safe_slug guard (PR #128) fires
        before any Firestore call — proving it protects these tools too,
        not just direct service callers, since a slug here comes straight
        from the MCP caller's own arguments."""
        result = tool_call()
        assert result["error"] == "invalid_request"
        db.set.assert_not_called()
        db.delete.assert_not_called()

    def test_list_ingredients_missing_by_default(self, db):
        recipe_docs = [_published_recipe_doc("ramen", "Tonkotsu Ramen", ["pork belly, skin-on", "garlic cloves"])]
        profile_docs = [_profile_doc("garlic", "Garlic")]
        # list_ingredients streams recipes (get_all_published_docs) first,
        # then profiles (list_profiles) — see its own comment on the order.
        db.stream.side_effect = [iter(recipe_docs), iter(profile_docs)]

        result = mcp_server.list_ingredients()

        keys = {row["key"] for row in result["ingredients"]}
        assert keys == {"pork belly"}  # garlic is covered, excluded from "missing"
        assert result["total_count"] == 2
        assert result["covered_count"] == 1

    def test_list_ingredients_all_shows_covered_and_via(self, db):
        recipe_docs = [_published_recipe_doc("ramen", "Tonkotsu Ramen", ["garlic"])]
        profile_docs = [_profile_doc("garlic", "Garlic")]
        db.stream.side_effect = [iter(recipe_docs), iter(profile_docs)]

        result = mcp_server.list_ingredients(coverage="all")

        assert result["ingredients"][0]["covered"] is True
        assert result["ingredients"][0]["via"] == "exact"

    def test_list_ingredients_search_filters_by_key(self, db):
        recipe_docs = [_published_recipe_doc("ramen", "Tonkotsu Ramen", ["garlic", "salt"])]
        db.stream.side_effect = [iter(recipe_docs), iter([])]

        result = mcp_server.list_ingredients(coverage="all", search="gar")

        assert [row["key"] for row in result["ingredients"]] == ["garlic"]

    def test_list_ingredients_rejects_a_bad_coverage_value(self, db):
        result = mcp_server.list_ingredients(coverage="whatever")
        assert result["error"] == "invalid_request"

    def test_get_ingredient_by_slug(self, db):
        db.get.return_value = _profile_doc("garlic", "Garlic")
        result = mcp_server.get_ingredient(slug="garlic")
        assert result["name"] == "Garlic"

    def test_get_ingredient_by_slug_not_found(self, db):
        db.get.return_value = _profile_doc("ghost", "Ghost", exists=False)
        result = mcp_server.get_ingredient(slug="ghost")
        assert result["error"] == "not_found"

    def test_get_ingredient_resolves_by_alias(self, db):
        db.stream.return_value = iter([_profile_doc("garlic", "Garlic", aliases=["garlic cloves"])])
        result = mcp_server.get_ingredient(name="garlic cloves")
        assert result["name"] == "Garlic"

    def test_get_ingredient_unresolved_name_is_not_found(self, db):
        db.stream.return_value = iter([_profile_doc("garlic", "Garlic")])
        result = mcp_server.get_ingredient(name="dragonfruit")
        assert result["error"] == "not_found"

    def test_get_ingredient_requires_slug_or_name(self, db):
        result = mcp_server.get_ingredient()
        assert result["error"] == "invalid_request"

    def test_upsert_ingredient_creates(self, db):
        db.stream.return_value = iter([])  # no existing profiles for the conflict check
        db.get.return_value = _profile_doc("pork-belly", "Pork Belly", exists=False)

        result = mcp_server.upsert_ingredient(name="Pork Belly", what_it_is="A fatty cut.")

        assert result["created"] is True
        assert result["slug"] == "pork-belly"
        written = db.set.call_args[0][0]
        assert written["name"] == "Pork Belly"
        assert written["what_it_is"] == "A fatty cut."

    def test_upsert_ingredient_merges_only_provided_fields(self, db):
        existing = _profile_doc("pork-belly", "Pork Belly", what_it_is="A fatty cut.", role="fat")
        db.stream.return_value = iter([existing])
        db.get.return_value = existing

        result = mcp_server.upsert_ingredient(name="Pork Belly", storage="Fridge 3 days.")

        # name is a required parameter (unlike update_recipe's optional title),
        # so it is always part of the write, whatever value the caller passes.
        assert result["updated_fields"] == ["name", "storage"]
        written = db.set.call_args[0][0]
        assert written["role"] == "fat"  # untouched field preserved
        assert written["storage"] == "Fridge 3 days."

    def test_upsert_ingredient_over_cap_is_a_validation_error(self, db):
        db.stream.return_value = iter([])
        db.get.return_value = _profile_doc("garlic", "Garlic", exists=False)

        result = mcp_server.upsert_ingredient(
            name="Garlic", what_it_is="x" * 300, role="x" * 200, substitutions="x" * 400, buying="x" * 101,
        )

        assert result["error"] == "validation_error"
        db.set.assert_not_called()

    def test_upsert_ingredient_alias_conflict(self, db):
        db.stream.return_value = iter([_profile_doc("garlic", "Garlic")])
        db.get.return_value = _profile_doc("garlic-powder", "Garlic Powder", exists=False)

        result = mcp_server.upsert_ingredient(name="Garlic Powder", aliases=["garlic"], what_it_is="Dried, ground.")

        assert result["error"] == "alias_conflict"
        assert result["existing_slug"] == "garlic"
        db.set.assert_not_called()

    def test_delete_ingredient(self, db):
        db.get.return_value = _profile_doc("garlic", "Garlic")
        result = mcp_server.delete_ingredient("garlic")
        assert result == {"deleted": True, "slug": "garlic"}
        db.delete.assert_called_once()

    def test_delete_ingredient_not_found(self, db):
        db.get.return_value = _profile_doc("ghost", "Ghost", exists=False)
        result = mcp_server.delete_ingredient("ghost")
        assert result["error"] == "not_found"
        db.delete.assert_not_called()
