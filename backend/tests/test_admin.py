import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.services import uploads

from conftest import JPEG_BYTES, NOT_A_MEDIA_FILE, PDF_BYTES

def test_admin_list_recipes(authenticated_client, mock_db):
    """Verifies that the admin can list all recipes."""
    mock_query = mock_db.collection.return_value.order_by.return_value.stream
    mock_doc = MagicMock()
    mock_doc.id = "test-id"
    mock_doc.to_dict.return_value = {
        "title": "Test Recipe",
        "slug": "test-recipe",
        "description": "Desc",
        "ingredients": [],
        "instructions": [],
        "prep_time_minutes": 10,
        "cook_time_minutes": 20,
        "servings": 4,
        "difficulty": "easy",
        "categories": [],
        "image_url": None,
        "published": True,
        "created_at": datetime(2026, 3, 14),
        "updated_at": datetime(2026, 3, 14),
    }
    mock_query.return_value = iter([mock_doc])
    
    response = authenticated_client.get("/api/admin/recipes")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test Recipe"

def test_admin_create_recipe(authenticated_client, mock_db):
    """Verifies that the admin can create a new recipe."""
    mock_db.collection.return_value.document.return_value.id = "new-test-id"

    payload = {
        "title": "New Recipe",
        "description": "New Desc",
        "ingredients": [{"item": "Water", "amount": "1", "unit": "cup", "group": "main"}],
        "instructions": [{"step": 1, "text": "Boil"}],
        "prep_time_minutes": 5,
        "cook_time_minutes": 5,
        "servings": 1,
        "difficulty": "easy",
        "categories": ["test"],
        "image_url": None,
        "published": True,
    }

    response = authenticated_client.post("/api/admin/recipes", json=payload)
    assert response.status_code == 201
    assert response.json()["title"] == "New Recipe"
    assert response.json()["id"] == "new-test-id"
    assert response.json()["slug"] == "new-recipe"

def test_admin_create_recipe_duplicate_slug_returns_409(authenticated_client, mock_db):
    """Re-creating a recipe whose title slugifies to an existing slug returns 409."""
    existing = MagicMock()
    existing.id = "existing-id"
    existing.to_dict.return_value = {
        "slug": "new-recipe",
        "title": "New Recipe",
        "published": True,
        "updated_at": datetime(2026, 1, 1),
    }
    mock_db.stream.return_value = iter([existing])

    response = authenticated_client.post("/api/admin/recipes", json={"title": "New Recipe"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert "existing-id" in response.json()["detail"]
    mock_db.set.assert_not_called()


def test_admin_create_recipe_sanitization_failure_returns_422(authenticated_client, mock_db):
    """A recipe attached to an image we could not sanitize must not be saved
    — this is the route-layer half of the fail-open fix in recipes.py."""
    mock_db.stream.return_value = iter([])  # no slug conflict
    with patch(
        "app.services.uploads.sanitize_recipe_image",
        side_effect=uploads.ImageSanitizationError("could not write x.jpg"),
    ):
        response = authenticated_client.post(
            "/api/admin/recipes",
            json={"title": "New Recipe", "image_url": "https://x/img.jpg"},
        )

    assert response.status_code == 422
    assert "could not write x.jpg" in response.json()["detail"]
    mock_db.set.assert_not_called()


def test_admin_update_recipe(authenticated_client, mock_db, sample_recipe_doc):
    """Verifies that the admin can update an existing recipe."""
    mock_doc = sample_recipe_doc(id="test-id", title="Old Title")
    updated_doc = sample_recipe_doc(id="test-id", title="New Title")
    
    # Mocking doc_ref.get() which is called twice in the route
    mock_db.collection.return_value.document.return_value.get.side_effect = [mock_doc, updated_doc]
    
    payload = {"title": "New Title"}
    response = authenticated_client.put("/api/admin/recipes/test-id", json=payload)
    
    assert response.status_code == 200
    assert response.json()["title"] == "New Title"

def test_admin_update_recipe_not_found(authenticated_client, mock_db):
    """Verifies 404 for nonexistent ID."""
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = authenticated_client.put("/api/admin/recipes/ghost", json={"title": "New"})
    assert response.status_code == 404

def test_admin_update_recipe_sanitization_failure_returns_422(authenticated_client, mock_db, sample_recipe_doc):
    mock_doc = sample_recipe_doc(id="test-id", image_url="https://storage.googleapis.com/b/old.jpg")
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    with patch(
        "app.services.uploads.sanitize_recipe_image",
        side_effect=uploads.ImageSanitizationError("could not write new.jpg"),
    ), patch("app.services.uploads.delete_recipe_image_blob") as deleter:
        response = authenticated_client.put(
            "/api/admin/recipes/test-id",
            json={"image_url": "https://storage.googleapis.com/b/new.jpg"},
        )

    assert response.status_code == 422
    assert "could not write new.jpg" in response.json()["detail"]
    mock_db.update.assert_not_called()
    deleter.assert_not_called()

def test_admin_delete_recipe(authenticated_client, mock_db):
    """Verifies that the admin can delete a recipe."""
    mock_doc = mock_db.collection.return_value.document.return_value.get.return_value
    mock_doc.exists = True
    
    response = authenticated_client.delete("/api/admin/recipes/test-id")
    assert response.status_code == 204

def test_admin_delete_recipe_not_found(authenticated_client, mock_db):
    """Verifies 404 when deleting non-existent recipe."""
    mock_doc = mock_db.collection.return_value.document.return_value.get.return_value
    mock_doc.exists = False
    
    response = authenticated_client.delete("/api/admin/recipes/invalid-id")
    assert response.status_code == 404

def test_admin_unauthenticated_returns_401(client):
    """Verifies that requests without auth fail with 401."""
    response = client.get("/api/admin/recipes")
    assert response.status_code == 401

def test_admin_upload_image_dev_mode(authenticated_client):
    """Verifies mock URL returned in dev mode."""
    with patch("app.routes.admin.settings") as mock_settings:
        mock_settings.is_dev = True
        file_data = {"file": ("test.jpg", JPEG_BYTES, "image/jpeg")}
        response = authenticated_client.post("/api/admin/upload-image", files=file_data)
        assert response.status_code == 200
        assert "placehold.co" in response.json()["url"]

def test_admin_upload_image_fails_closed_when_unconfigured_in_production(authenticated_client):
    """The placeholder response is reserved for is_dev. Cloud Build
    auto-deploys the backend on every push to main while Terraform (which
    creates the bucket and wires GCS_BUCKET_NAME) is applied manually and
    separately — a revision that reaches production ahead of that apply
    must fail loudly, not silently report a fake upload success that could
    get saved as a recipe's real image_url."""
    with patch("app.routes.admin.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.gcs_bucket_name = None
        file_data = {"file": ("test.jpg", JPEG_BYTES, "image/jpeg")}
        response = authenticated_client.post("/api/admin/upload-image", files=file_data)
        assert response.status_code == 500
        assert "GCS_BUCKET_NAME" in response.json()["detail"]
        assert "placehold.co" not in response.text

def test_admin_upload_receipt_fails_closed_when_unconfigured_in_production(authenticated_client):
    with patch("app.routes.admin.settings") as mock_settings:
        mock_settings.is_dev = False
        mock_settings.gcs_receipts_bucket_name = None
        file_data = {"file": ("r.pdf", PDF_BYTES, "application/pdf")}
        response = authenticated_client.post("/api/admin/upload-receipt", files=file_data)
        assert response.status_code == 500
        assert "GCS_RECEIPTS_BUCKET_NAME" in response.json()["detail"]

def test_admin_upload_image_rejects_oversize(authenticated_client):
    """Uploads over 10MB are rejected before touching storage."""
    with patch("app.routes.admin.settings") as mock_settings:
        mock_settings.is_dev = True
        big = b"x" * (10 * 1024 * 1024 + 1)
        response = authenticated_client.post(
            "/api/admin/upload-image", files={"file": ("big.jpg", big, "image/jpeg")}
        )
    assert response.status_code == 413

def test_admin_upload_receipt_rejects_oversize(authenticated_client):
    """Recipe receipt uploads over 10MB are rejected."""
    with patch("app.routes.admin.settings") as mock_settings:
        mock_settings.is_dev = True
        big = b"x" * (10 * 1024 * 1024 + 1)
        response = authenticated_client.post(
            "/api/admin/upload-receipt", files={"file": ("big.pdf", big, "application/pdf")}
        )
    assert response.status_code == 413


# ── Supporter moderation: toggle-name / public_listing ──────────────────────

def test_toggle_name_invalid_collection_rejected(authenticated_client):
    response = authenticated_client.post("/api/admin/supporters/recipes/doc1/toggle-name")
    assert response.status_code == 400


def test_toggle_name_not_found(authenticated_client, mock_db):
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = authenticated_client.post("/api/admin/supporters/subscribers/doc1/toggle-name")
    assert response.status_code == 404


def test_toggle_name_off_sets_public_listing_false(authenticated_client, mock_db):
    """A supporter with a display name currently listed (name_enabled
    defaults True) gets hidden: name_enabled flips off, and public_listing
    — the denormalised query gate — flips with it in the same write."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"display_name": "Alex", "name_enabled": True}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = authenticated_client.post("/api/admin/supporters/subscribers/doc1/toggle-name")
    assert response.status_code == 200
    assert response.json()["name_enabled"] is False

    update_call = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert update_call["name_enabled"] is False
    assert update_call["public_listing"] is False


def test_toggle_name_on_with_display_name_sets_public_listing_true(authenticated_client, mock_db):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"display_name": "Alex", "name_enabled": False}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = authenticated_client.post("/api/admin/supporters/donations/doc2/toggle-name")
    assert response.status_code == 200
    assert response.json()["name_enabled"] is True

    update_call = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert update_call["public_listing"] is True


def test_toggle_name_on_without_display_name_keeps_public_listing_false(authenticated_client, mock_db):
    """Flipping name_enabled back on doesn't fabricate a listing for a
    supporter who never set a display name in the first place."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"display_name": None, "name_enabled": False}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    response = authenticated_client.post("/api/admin/supporters/subscribers/doc3/toggle-name")
    assert response.status_code == 200
    assert response.json()["name_enabled"] is True

    update_call = mock_db.collection.return_value.document.return_value.update.call_args[0][0]
    assert update_call["public_listing"] is False


def test_admin_recipes_round_trip_sous_chef_notes(authenticated_client, mock_db):
    """Admin routes return the owner's view, including the assistant notes."""
    mock_doc = MagicMock()
    mock_doc.id = "r1"
    mock_doc.to_dict.return_value = {
        "title": "Fried Rice", "slug": "fried-rice", "description": "", "ingredients": [],
        "instructions": [], "prep_time_minutes": 0, "cook_time_minutes": 0, "servings": 2,
        "difficulty": "easy", "categories": [], "image_url": None, "published": False,
        "created_at": datetime(2026, 3, 14), "updated_at": datetime(2026, 3, 14),
        "sous_chef_notes": "use day-old rice",
    }
    mock_db.collection.return_value.order_by.return_value.stream.return_value = iter([mock_doc])
    listed = authenticated_client.get("/api/admin/recipes").json()
    assert listed[0]["sous_chef_notes"] == "use day-old rice"

    mock_db.collection.return_value.document.return_value.id = "new-id"
    mock_db.stream.return_value = iter([])
    created = authenticated_client.post(
        "/api/admin/recipes",
        json={"title": "Laksa", "ingredients": [{"item": "noodles", "amount": "1", "unit": "pack"}],
              "instructions": [{"step": 1, "text": "Cook"}], "sous_chef_notes": "toast the rempah"},
    )
    assert created.status_code == 201
    assert created.json()["sous_chef_notes"] == "toast the rempah"
    assert mock_db.set.call_args[0][0]["sous_chef_notes"] == "toast the rempah"
