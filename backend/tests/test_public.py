import pytest
from datetime import datetime
from unittest.mock import MagicMock

def test_health_check(client):
    """Verifies the health check endpoint returns 200."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_list_recipes_empty(client, mock_db, mock_cache):
    """Verifies that an empty recipe list is handled correctly."""
    mock_cache.get.return_value = None
    mock_db.stream.return_value = iter([])
    
    response = client.get("/api/recipes")
    assert response.status_code == 200
    assert response.json() == {"recipes": [], "next_cursor": None}

def test_list_recipes_with_data(client, mock_db, mock_cache, sample_recipe_doc):
    """Verifies that recipes are returned with all fields populated."""
    mock_cache.get.return_value = None
    doc = sample_recipe_doc(id="recipe-1", title="Carbonara", categories=["Italian"])
    mock_db.stream.return_value = iter([doc])

    response = client.get("/api/recipes")
    assert response.status_code == 200
    data = response.json()["recipes"]
    assert len(data) == 1
    assert data[0]["title"] == "Carbonara"
    assert data[0]["id"] == "recipe-1"

def test_list_recipes_search_filter(client, mock_db, mock_cache, sample_recipe_doc):
    """Verifies that search filters correctly in Python."""
    mock_cache.get.return_value = None
    doc1 = sample_recipe_doc(id="1", title="Carbonara")
    doc2 = sample_recipe_doc(id="2", title="Pesto")
    mock_db.stream.return_value = iter([doc1, doc2])

    response = client.get("/api/recipes?search=carbonara")
    assert response.status_code == 200
    data = response.json()["recipes"]
    assert len(data) == 1
    assert data[0]["title"] == "Carbonara"

def test_list_recipes_category_filter(client, mock_db, mock_cache, sample_recipe_doc):
    """Verifies that category filter uses Firestore where."""
    mock_cache.get.return_value = None
    doc = sample_recipe_doc(id="1", categories=["Italian"])
    mock_db.stream.return_value = iter([doc])

    response = client.get("/api/recipes?category=Italian")
    assert response.status_code == 200
    assert len(response.json()["recipes"]) == 1

def test_list_recipes_combined_filters(client, mock_db, mock_cache, sample_recipe_doc):
    """Verifies search + category together."""
    mock_cache.get.return_value = None
    doc = sample_recipe_doc(id="1", title="Carbonara", categories=["Italian"])
    mock_db.stream.return_value = iter([doc])

    response = client.get("/api/recipes?category=Italian&search=carbonara")
    assert response.status_code == 200
    assert len(response.json()["recipes"]) == 1

def test_list_recipes_search_by_ingredient(client, mock_db, mock_cache, sample_recipe_doc):
    """Verifies ?search_by=ingredient path."""
    mock_cache.get.return_value = None
    doc = sample_recipe_doc(id="1", title="Dish", ingredients=[{"item": "egg", "amount": "1", "unit": "", "group": ""}])
    mock_db.stream.return_value = iter([doc])

    response = client.get("/api/recipes?search=egg&search_by=ingredient")
    assert response.status_code == 200
    assert len(response.json()["recipes"]) == 1

def test_get_recipe_by_slug(client, mock_db, mock_cache, sample_recipe_doc):
    """Verifies getting a single recipe by slug."""
    mock_cache.get.return_value = None
    doc = sample_recipe_doc(id="1", slug="carbonara", title="Carbonara")
    mock_db.stream.return_value = iter([doc])
    
    response = client.get("/api/recipes/carbonara")
    assert response.status_code == 200
    assert response.json()["title"] == "Carbonara"

def test_get_recipe_not_found(client, mock_db, mock_cache):
    """Verifies 404 for nonexistent slug."""
    mock_cache.get.return_value = None
    mock_db.stream.return_value = iter([])
    
    response = client.get("/api/recipes/ghost")
    assert response.status_code == 404

def test_list_categories_no_config(client, mock_db, mock_cache):
    """Verifies empty list when config/categories doc does not exist."""
    mock_cache.get.return_value = None
    config_doc = MagicMock()
    config_doc.exists = False
    mock_db.get.return_value = config_doc

    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == []

def test_list_categories_returns_from_config(client, mock_db, mock_cache):
    """Verifies categories are returned sorted from the config document."""
    mock_cache.get.return_value = None
    config_doc = MagicMock()
    config_doc.exists = True
    config_doc.to_dict.return_value = {"list": ["soup", "breakfast", "vegan"]}
    mock_db.get.return_value = config_doc

    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == ["breakfast", "soup", "vegan"]

def test_sitemap_xml(client, mock_db, sample_recipe_doc):
    """Verifies sitemap returns valid XML."""
    doc = sample_recipe_doc(slug="test", updated_at=datetime(2024, 1, 1))
    mock_db.stream.return_value = iter([doc])
    
    response = client.get("/api/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["Content-Type"]
    assert "/recipes/test" in response.text
    assert "2024-01-01" in response.text

def test_feed_xml(client, mock_db, sample_recipe_doc):
    """Verifies RSS feed returns valid XML."""
    doc = sample_recipe_doc(title="Test Recipe", description="Test Desc", created_at=datetime(2024, 1, 1))
    mock_db.stream.return_value = iter([doc])
    
    response = client.get("/api/feed.xml")
    assert response.status_code == 200
    assert "application/rss+xml" in response.headers["Content-Type"]
    assert "Test Recipe" in response.text
    assert "Test Desc" in response.text

def test_sitemap_urls_use_frontend_host_and_trailing_slashes(client, mock_db):
    """Sitemap entries point at the SPA's canonical (trailing-slash) URLs."""
    doc = MagicMock()
    doc.to_dict.return_value = {"slug": "tom-yum", "updated_at": datetime(2026, 1, 2)}
    mock_db.stream.return_value = iter([doc])

    response = client.get("/api/sitemap.xml")

    assert response.status_code == 200
    assert "xml" in response.headers["content-type"]
    body = response.text
    assert "<loc>http://localhost:5173/recipes/</loc>" in body
    assert "<loc>http://localhost:5173/recipes/tom-yum/</loc>" in body
    assert "<lastmod>2026-01-02</lastmod>" in body

def test_feed_self_link_points_at_api_host(client, mock_db, sample_recipe_doc):
    """The RSS self link must reference the backend host (frontend has no /api)."""
    mock_db.stream.return_value = iter([sample_recipe_doc(id="r1", title="Pho")])

    response = client.get("/api/feed.xml")

    assert response.status_code == 200
    body = response.text
    assert 'href="http://testserver/api/feed.xml" rel="self"' in body
    assert "<link>http://localhost:5173/recipes/test-recipe/</link>" in body
