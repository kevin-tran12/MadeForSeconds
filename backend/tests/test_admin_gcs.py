"""Tests for GCS image lifecycle and recipe receipt management.

Covers:
- _gcs_blob_name helper
- Image replacement on recipe update (old GCS blob deleted)
- GCS cleanup on recipe delete (image + all receipt_urls)
- upload-receipt endpoint
- delete receipt endpoint
- receipt_urls field on Recipe model
"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.routes.admin import _gcs_blob_name, _delete_gcs_blob


def _delete_with_json(client, url, payload):
    """Helper: send DELETE with a JSON body (TestClient.delete() doesn't accept json=)."""
    return client.request(
        "DELETE",
        url,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


# ── _gcs_blob_name unit tests ─────────────────────────────────────────────────

class TestGcsBlobName:
    def test_extracts_blob_name_from_gcs_url(self):
        url = "https://storage.googleapis.com/my-bucket/uuid-photo.jpg"
        assert _gcs_blob_name(url, "my-bucket") == "uuid-photo.jpg"

    def test_extracts_nested_blob_name(self):
        url = "https://storage.googleapis.com/my-bucket/prefix/uuid-photo.jpg"
        assert _gcs_blob_name(url, "my-bucket") == "prefix/uuid-photo.jpg"

    def test_returns_none_for_dev_placeholder(self):
        url = "https://placehold.co/800x400?text=test.jpg"
        assert _gcs_blob_name(url, "my-bucket") is None

    def test_returns_none_for_different_bucket(self):
        url = "https://storage.googleapis.com/other-bucket/photo.jpg"
        assert _gcs_blob_name(url, "my-bucket") is None

    def test_returns_none_for_empty_url(self):
        assert _gcs_blob_name("", "my-bucket") is None

    def test_returns_none_for_none_url(self):
        assert _gcs_blob_name(None, "my-bucket") is None  # type: ignore

    def test_returns_none_for_empty_bucket(self):
        assert _gcs_blob_name("https://storage.googleapis.com/my-bucket/photo.jpg", "") is None

    def test_returns_none_for_none_bucket(self):
        assert _gcs_blob_name("https://storage.googleapis.com/my-bucket/photo.jpg", None) is None  # type: ignore


# ── _delete_gcs_blob unit tests ───────────────────────────────────────────────

class TestDeleteGcsBlob:
    def test_no_op_in_dev_mode(self):
        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = True
            _delete_gcs_blob("my-bucket", "photo.jpg")
            mock_storage.Client.assert_not_called()

    def test_no_op_when_bucket_empty(self):
        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            _delete_gcs_blob("", "photo.jpg")
            mock_storage.Client.assert_not_called()

    def test_no_op_when_blob_name_empty(self):
        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            _delete_gcs_blob("my-bucket", "")
            mock_storage.Client.assert_not_called()

    def test_deletes_blob_in_production(self):
        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_blob = MagicMock()
            mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

            _delete_gcs_blob("my-bucket", "photo.jpg")

            mock_storage.Client.return_value.bucket.assert_called_with("my-bucket")
            mock_storage.Client.return_value.bucket.return_value.blob.assert_called_with("photo.jpg")
            mock_blob.delete.assert_called_once()

    def test_silently_ignores_gcs_errors(self):
        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_storage.Client.return_value.bucket.return_value.blob.return_value.delete.side_effect = Exception("GCS error")
            # Should not raise
            _delete_gcs_blob("my-bucket", "photo.jpg")


# ── Image replacement on update ───────────────────────────────────────────────

_RECIPE_DATA = {
    "title": "Test Recipe",
    "slug": "test-recipe",
    "description": "Desc",
    "ingredients": [],
    "instructions": [],
    "prep_time_minutes": 0,
    "cook_time_minutes": 0,
    "servings": 2,
    "difficulty": "easy",
    "categories": [],
    "image_url": "https://storage.googleapis.com/test-bucket/old-uuid.jpg",
    "published": False,
    "created_at": datetime(2026, 1, 1),
    "updated_at": datetime(2026, 1, 1),
    "nutrition": [],
    "components": None,
    "receipt_urls": [],
}


class TestUpdateRecipeImageReplacement:
    def test_deletes_old_gcs_image_when_image_changes(
        self, authenticated_client, mock_db, mock_cache
    ):
        old_url = "https://storage.googleapis.com/test-bucket/old-uuid.jpg"
        new_url = "https://storage.googleapis.com/test-bucket/new-uuid.jpg"

        old_doc = MagicMock()
        old_doc.exists = True
        old_doc.to_dict.return_value = {**_RECIPE_DATA, "image_url": old_url}

        updated_doc = MagicMock()
        updated_doc.id = "test-id"
        updated_doc.to_dict.return_value = {**_RECIPE_DATA, "image_url": new_url, "id": "test-id"}

        mock_db.collection.return_value.document.return_value.get.side_effect = [old_doc, updated_doc]

        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "test-bucket"
            mock_settings.gcs_receipts_bucket_name = "test-receipts-bucket"
            mock_blob = MagicMock()
            mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

            response = authenticated_client.put(
                "/api/admin/recipes/test-id", json={"image_url": new_url}
            )

        assert response.status_code == 200
        mock_storage.Client.return_value.bucket.assert_called_with("test-bucket")
        mock_storage.Client.return_value.bucket.return_value.blob.assert_called_with("old-uuid.jpg")
        mock_blob.delete.assert_called_once()

    def test_no_gcs_delete_when_image_not_in_update(
        self, authenticated_client, mock_db, mock_cache
    ):
        """Omitting image_url from the update body should NOT delete anything."""
        existing_doc = MagicMock()
        existing_doc.exists = True
        existing_doc.to_dict.return_value = {
            **_RECIPE_DATA,
            "image_url": "https://storage.googleapis.com/test-bucket/old-uuid.jpg",
        }
        updated_doc = MagicMock()
        updated_doc.id = "test-id"
        updated_doc.to_dict.return_value = {**_RECIPE_DATA, "id": "test-id"}
        mock_db.collection.return_value.document.return_value.get.side_effect = [
            existing_doc, updated_doc
        ]

        with patch("app.routes.admin.storage") as mock_storage:
            response = authenticated_client.put(
                "/api/admin/recipes/test-id", json={"title": "Updated Title"}
            )

        assert response.status_code == 200
        mock_storage.Client.assert_not_called()

    def test_no_gcs_delete_when_image_unchanged(
        self, authenticated_client, mock_db, mock_cache
    ):
        """Sending the same image_url value should not trigger deletion."""
        same_url = "https://storage.googleapis.com/test-bucket/same.jpg"
        existing_doc = MagicMock()
        existing_doc.exists = True
        existing_doc.to_dict.return_value = {**_RECIPE_DATA, "image_url": same_url}
        updated_doc = MagicMock()
        updated_doc.id = "test-id"
        updated_doc.to_dict.return_value = {**_RECIPE_DATA, "image_url": same_url, "id": "test-id"}
        mock_db.collection.return_value.document.return_value.get.side_effect = [
            existing_doc, updated_doc
        ]

        with patch("app.routes.admin.storage") as mock_storage:
            response = authenticated_client.put(
                "/api/admin/recipes/test-id", json={"image_url": same_url}
            )

        assert response.status_code == 200
        mock_storage.Client.assert_not_called()


# ── Delete recipe cascades to GCS ─────────────────────────────────────────────

class TestDeleteRecipeGcsCascade:
    def test_deletes_gcs_image_on_recipe_delete(
        self, authenticated_client, mock_db, mock_cache
    ):
        image_url = "https://storage.googleapis.com/test-bucket/photo.jpg"
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {**_RECIPE_DATA, "image_url": image_url, "receipt_urls": []}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "test-bucket"
            mock_settings.gcs_receipts_bucket_name = "test-receipts-bucket"
            mock_blob = MagicMock()
            mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

            response = authenticated_client.delete("/api/admin/recipes/test-id")

        assert response.status_code == 204
        mock_storage.Client.return_value.bucket.assert_called_with("test-bucket")
        mock_storage.Client.return_value.bucket.return_value.blob.assert_called_with("photo.jpg")
        mock_blob.delete.assert_called_once()

    def test_deletes_all_receipt_urls_on_recipe_delete(
        self, authenticated_client, mock_db, mock_cache
    ):
        receipt1 = "https://storage.googleapis.com/test-receipts/r1.jpg"
        receipt2 = "https://storage.googleapis.com/test-receipts/r2.pdf"
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            **_RECIPE_DATA,
            "image_url": None,
            "receipt_urls": [receipt1, receipt2],
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_bucket_name = "test-bucket"
            mock_settings.gcs_receipts_bucket_name = "test-receipts"
            mock_blob = MagicMock()
            mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

            response = authenticated_client.delete("/api/admin/recipes/test-id")

        assert response.status_code == 204
        # Both receipt blobs should be deleted
        assert mock_blob.delete.call_count == 2

    def test_no_gcs_calls_when_no_image_or_receipts(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {**_RECIPE_DATA, "image_url": None, "receipt_urls": []}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("app.routes.admin.storage") as mock_storage:
            response = authenticated_client.delete("/api/admin/recipes/test-id")

        assert response.status_code == 204
        mock_storage.Client.assert_not_called()


# ── upload-receipt endpoint ───────────────────────────────────────────────────

class TestUploadReceipt:
    def test_returns_placeholder_url_in_dev_mode(self, authenticated_client):
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            mock_settings.gcs_receipts_bucket_name = None
            file_data = {"file": ("receipt.jpg", b"fake-content", "image/jpeg")}
            response = authenticated_client.post("/api/admin/upload-receipt", files=file_data)

        assert response.status_code == 200
        assert "placehold.co" in response.json()["url"]

    def test_accepts_pdf_file(self, authenticated_client):
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            file_data = {"file": ("receipt.pdf", b"fake-pdf-content", "application/pdf")}
            response = authenticated_client.post("/api/admin/upload-receipt", files=file_data)

        assert response.status_code == 200

    def test_accepts_image_types(self, authenticated_client):
        for mime in ["image/jpeg", "image/png", "image/webp"]:
            with patch("app.routes.admin.settings") as mock_settings:
                mock_settings.is_dev = True
                file_data = {"file": ("r.img", b"data", mime)}
                response = authenticated_client.post("/api/admin/upload-receipt", files=file_data)
            assert response.status_code == 200, f"Failed for {mime}"

    def test_rejects_invalid_content_type(self, authenticated_client):
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            file_data = {"file": ("data.csv", b"a,b,c", "text/csv")}
            response = authenticated_client.post("/api/admin/upload-receipt", files=file_data)

        assert response.status_code == 400
        assert "Receipt must be" in response.json()["detail"]

    def test_rejects_text_plain(self, authenticated_client):
        with patch("app.routes.admin.settings") as mock_settings:
            mock_settings.is_dev = True
            file_data = {"file": ("note.txt", b"hello", "text/plain")}
            response = authenticated_client.post("/api/admin/upload-receipt", files=file_data)

        assert response.status_code == 400


# ── delete receipt endpoint ───────────────────────────────────────────────────

class TestDeleteReceipt:
    def test_removes_url_from_recipe_and_deletes_gcs_blob(
        self, authenticated_client, mock_db, mock_cache
    ):
        receipt_url = "https://storage.googleapis.com/test-receipts/r1.jpg"
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {**_RECIPE_DATA, "receipt_urls": [receipt_url]}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("app.routes.admin.settings") as mock_settings, \
             patch("app.routes.admin.storage") as mock_storage:
            mock_settings.is_dev = False
            mock_settings.gcs_receipts_bucket_name = "test-receipts"
            mock_blob = MagicMock()
            mock_storage.Client.return_value.bucket.return_value.blob.return_value = mock_blob

            response = _delete_with_json(
                authenticated_client,
                "/api/admin/recipes/test-id/receipts",
                {"url": receipt_url},
            )

        assert response.status_code == 204
        # Firestore updated to remove the URL
        mock_db.collection.return_value.document.return_value.update.assert_called_once_with(
            {"receipt_urls": []}
        )
        # GCS blob deleted
        mock_blob.delete.assert_called_once()

    def test_returns_404_when_url_not_on_recipe(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {**_RECIPE_DATA, "receipt_urls": ["https://other.example.com/r.jpg"]}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        response = _delete_with_json(
            authenticated_client,
            "/api/admin/recipes/test-id/receipts",
            {"url": "https://storage.googleapis.com/test-receipts/missing.jpg"},
        )

        assert response.status_code == 404

    def test_returns_404_when_recipe_not_found(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        response = _delete_with_json(
            authenticated_client,
            "/api/admin/recipes/ghost/receipts",
            {"url": "https://storage.googleapis.com/test-receipts/r.jpg"},
        )

        assert response.status_code == 404

    def test_returns_400_when_url_missing(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {**_RECIPE_DATA, "receipt_urls": []}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        response = _delete_with_json(
            authenticated_client,
            "/api/admin/recipes/test-id/receipts",
            {},
        )

        assert response.status_code == 400


# ── receipt_urls on Recipe model ──────────────────────────────────────────────

class TestReceiptUrlsOnRecipe:
    def test_create_recipe_stores_receipt_urls(
        self, authenticated_client, mock_db, mock_cache
    ):
        mock_db.collection.return_value.document.return_value.id = "new-id"
        payload = {
            "title": "My Recipe",
            "receipt_urls": [
                "https://placehold.co/400x300?text=r1.jpg",
                "https://placehold.co/400x300?text=r2.jpg",
            ],
        }
        response = authenticated_client.post("/api/admin/recipes", json=payload)

        assert response.status_code == 201
        assert response.json()["receipt_urls"] == payload["receipt_urls"]

    def test_recipe_without_receipt_urls_defaults_to_empty_list(
        self, authenticated_client, mock_db
    ):
        """Legacy recipe docs without receipt_urls should return an empty list."""
        mock_query = mock_db.collection.return_value.order_by.return_value.stream
        mock_doc = MagicMock()
        mock_doc.id = "legacy-id"
        # Simulate a legacy doc that has no receipt_urls key at all
        data = {
            "title": "Legacy Recipe",
            "slug": "legacy-recipe",
            "description": "",
            "ingredients": [],
            "instructions": [],
            "prep_time_minutes": 0,
            "cook_time_minutes": 0,
            "servings": 1,
            "difficulty": "easy",
            "categories": [],
            "image_url": None,
            "published": False,
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
            # receipt_urls intentionally absent
        }
        mock_doc.to_dict.return_value = data
        mock_query.return_value = iter([mock_doc])

        response = authenticated_client.get("/api/admin/recipes")

        assert response.status_code == 200
        assert response.json()[0]["receipt_urls"] == []

    def test_update_recipe_can_set_receipt_urls(
        self, authenticated_client, mock_db, mock_cache
    ):
        existing = MagicMock()
        existing.exists = True
        existing.to_dict.return_value = {**_RECIPE_DATA, "receipt_urls": []}

        urls = ["https://placehold.co/r1.jpg"]
        updated = MagicMock()
        updated.id = "test-id"
        updated.to_dict.return_value = {**_RECIPE_DATA, "id": "test-id", "receipt_urls": urls}

        mock_db.collection.return_value.document.return_value.get.side_effect = [existing, updated]

        response = authenticated_client.put(
            "/api/admin/recipes/test-id", json={"receipt_urls": urls}
        )

        assert response.status_code == 200
        assert response.json()["receipt_urls"] == urls
