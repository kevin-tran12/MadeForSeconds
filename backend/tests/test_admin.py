import pytest
from unittest.mock import MagicMock

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
        "created_at": "2026-03-14T00:00:00Z",
        "updated_at": "2026-03-14T00:00:00Z",
        "rating": None
    }
    mock_query.return_value = iter([mock_doc])
    
    response = authenticated_client.get("/api/admin/recipes")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test Recipe"

def test_admin_create_recipe(authenticated_client, mock_db):
    """Verifies that the admin can create a new recipe."""
    payload = {
        "title": "New Recipe",
        "description": "New Desc",
        "ingredients": [{"item": "Water", "amount": "1", "unit": "cup"}],
        "instructions": [{"step": 1, "text": "Boil"}],
        "prep_time_minutes": 5,
        "cook_time_minutes": 5,
        "servings": 1,
        "difficulty": "easy",
        "categories": ["test"],
        "image_url": None,
        "published": True,
        "rating": None
    }
    
    response = authenticated_client.post("/api/admin/recipes", json=payload)
    assert response.status_code == 201
    assert response.json()["title"] == "New Recipe"
    assert "slug" in response.json()

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
