import pytest

def test_health_check(client):
    """Verifies the health check endpoint returns 200."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_list_recipes_empty(client, mock_db):
    """Verifies that an empty recipe list is handled correctly."""
    # Mock Firestore query
    mock_query = mock_db.collection.return_value.where.return_value.order_by.return_value.limit.return_value
    mock_query.stream.return_value = iter([])
    
    response = client.get("/api/recipes")
    assert response.status_code == 200
    assert response.json() == []

def test_list_categories_empty(client, mock_db):
    """Verifies that an empty category list is handled correctly."""
    mock_query = mock_db.collection.return_value.where.return_value.order_by.return_value.limit.return_value.select.return_value
    mock_query.stream.return_value = iter([])
    
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == []
