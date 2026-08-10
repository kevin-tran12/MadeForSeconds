import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

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
