"""Tests for new recipe fields: about, secrets, prep_steps."""

from datetime import datetime
from unittest.mock import MagicMock


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_doc(id="recipe-id", **overrides):
    doc = MagicMock()
    doc.id = id
    doc.exists = True
    payload = {
        "title": "Test Recipe",
        "slug": "test-recipe",
        "description": "A test",
        "about": None,
        "ingredients": [],
        "prep_steps": [],
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
        "nutrition": [],
        "components": None,
        "secrets": [],
        "labels": [],
        "receipt_urls": [],
    }
    payload.update(overrides)
    doc.to_dict.return_value = payload
    return doc


# ── Create tests ──────────────────────────────────────────────────────────────


def test_create_recipe_with_about(authenticated_client, mock_db):
    """about field is persisted on create and returned in response."""
    mock_db.collection.return_value.document.return_value.id = "new-id"

    # category validation doc
    cat_doc = MagicMock()
    cat_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = cat_doc

    payload = {
        "title": "Carbonara",
        "description": "Classic Roman pasta.",
        "about": "Carbonara has ancient Roman roots.",
        "ingredients": [],
        "instructions": [],
        "prep_time_minutes": 10,
        "cook_time_minutes": 20,
        "servings": 2,
        "difficulty": "easy",
        "categories": [],
        "published": False,
    }
    response = authenticated_client.post("/api/admin/recipes", json=payload)
    assert response.status_code == 201
    assert response.json()["about"] == "Carbonara has ancient Roman roots."


def test_create_recipe_with_prep_steps(authenticated_client, mock_db):
    """prep_steps are persisted on create and returned in response."""
    mock_db.collection.return_value.document.return_value.id = "new-id"

    cat_doc = MagicMock()
    cat_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = cat_doc

    payload = {
        "title": "Ramen",
        "description": "Pork bone broth.",
        "ingredients": [],
        "prep_steps": [
            {"step": 1, "text": "Blanch pork bones for 10 minutes.", "tip": "Rinse well."},
            {"step": 2, "text": "Slice ginger and crush garlic."},
        ],
        "instructions": [{"step": 1, "text": "Boil broth for 4 hours."}],
        "prep_time_minutes": 30,
        "cook_time_minutes": 240,
        "servings": 4,
        "difficulty": "hard",
        "categories": [],
        "published": False,
    }
    response = authenticated_client.post("/api/admin/recipes", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert len(data["prep_steps"]) == 2
    assert data["prep_steps"][0]["text"] == "Blanch pork bones for 10 minutes."
    assert data["prep_steps"][0]["tip"] == "Rinse well."
    assert data["prep_steps"][1].get("tip") is None


def test_create_recipe_with_secrets(authenticated_client, mock_db):
    """secrets are persisted on create and returned in response."""
    mock_db.collection.return_value.document.return_value.id = "new-id"

    cat_doc = MagicMock()
    cat_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = cat_doc

    payload = {
        "title": "Carbonara",
        "description": "Classic.",
        "ingredients": [],
        "instructions": [],
        "prep_time_minutes": 5,
        "cook_time_minutes": 15,
        "servings": 2,
        "difficulty": "medium",
        "categories": [],
        "published": False,
        "secrets": [
            {"title": "The Emulsification Window", "body": "Pull off heat before adding eggs."},
            {"title": "Why Guanciale", "body": "Higher fat ratio than pancetta."},
        ],
    }
    response = authenticated_client.post("/api/admin/recipes", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert len(data["secrets"]) == 2
    assert data["secrets"][0]["title"] == "The Emulsification Window"
    assert data["secrets"][1]["body"] == "Higher fat ratio than pancetta."


def test_create_recipe_all_new_fields_together(authenticated_client, mock_db):
    """about, prep_steps, and secrets can all be provided together."""
    mock_db.collection.return_value.document.return_value.id = "new-id"

    cat_doc = MagicMock()
    cat_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = cat_doc

    payload = {
        "title": "Tonkotsu Ramen",
        "description": "Rich milky broth.",
        "about": "Tonkotsu originated in Fukuoka, Japan.",
        "prep_steps": [{"step": 1, "text": "Blanch bones."}],
        "secrets": [{"title": "The White Broth", "body": "Boil hard to emulsify fat."}],
        "ingredients": [],
        "instructions": [{"step": 1, "text": "Boil bones 4 hours."}],
        "prep_time_minutes": 60,
        "cook_time_minutes": 240,
        "servings": 4,
        "difficulty": "hard",
        "categories": [],
        "published": False,
    }
    response = authenticated_client.post("/api/admin/recipes", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["about"] == "Tonkotsu originated in Fukuoka, Japan."
    assert len(data["prep_steps"]) == 1
    assert len(data["secrets"]) == 1


# ── Update tests ──────────────────────────────────────────────────────────────


def test_update_recipe_sets_about(authenticated_client, mock_db):
    """PUT can set about on an existing recipe that had none."""
    before = _make_doc(id="r1", about=None)
    after = _make_doc(id="r1", about="Updated about text.")
    mock_db.collection.return_value.document.return_value.get.side_effect = [before, after]

    response = authenticated_client.put("/api/admin/recipes/r1", json={"about": "Updated about text."})
    assert response.status_code == 200
    assert response.json()["about"] == "Updated about text."


def test_update_recipe_sets_prep_steps(authenticated_client, mock_db):
    """PUT can add prep_steps to a recipe that had none."""
    before = _make_doc(id="r1", prep_steps=[])
    after = _make_doc(id="r1", prep_steps=[{"step": 1, "text": "Toast spices.", "tip": None}])
    mock_db.collection.return_value.document.return_value.get.side_effect = [before, after]

    response = authenticated_client.put(
        "/api/admin/recipes/r1",
        json={"prep_steps": [{"step": 1, "text": "Toast spices."}]},
    )
    assert response.status_code == 200
    assert response.json()["prep_steps"][0]["text"] == "Toast spices."


def test_update_recipe_clears_secrets(authenticated_client, mock_db):
    """PUT with empty secrets list clears existing secrets."""
    before = _make_doc(id="r1", secrets=[{"title": "Old Secret", "body": "Body."}])
    after = _make_doc(id="r1", secrets=[])
    mock_db.collection.return_value.document.return_value.get.side_effect = [before, after]

    response = authenticated_client.put("/api/admin/recipes/r1", json={"secrets": []})
    assert response.status_code == 200
    assert response.json()["secrets"] == []


# ── Legacy recipe defaults ────────────────────────────────────────────────────


def test_legacy_recipe_missing_new_fields_defaults(authenticated_client, mock_db):
    """A Firestore doc without about/prep_steps/secrets returns safe defaults."""
    # Simulate a legacy document that predates the new fields
    legacy_doc = MagicMock()
    legacy_doc.id = "legacy-id"
    legacy_doc.exists = True
    legacy_doc.to_dict.return_value = {
        "title": "Legacy Recipe",
        "slug": "legacy-recipe",
        "description": "Old recipe without new fields.",
        # No about, prep_steps, secrets, labels, receipt_urls
        "ingredients": [],
        "instructions": [],
        "prep_time_minutes": 10,
        "cook_time_minutes": 20,
        "servings": 2,
        "difficulty": "easy",
        "categories": [],
        "image_url": None,
        "published": True,
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
        "nutrition": [],
        "components": None,
    }
    mock_db.collection.return_value.stream.return_value = iter([legacy_doc])

    response = authenticated_client.get("/api/admin/recipes")
    assert response.status_code == 200
    recipes = response.json()
    assert len(recipes) == 1
    r = recipes[0]
    assert r["about"] is None
    assert r["prep_steps"] == []
    assert r["secrets"] == []
