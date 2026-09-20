"""Tests for the admin ingredient-profile routes (app/routes/admin.py).

The MCP tools are the primary authoring path (see test_mcp_tools.py's
TestIngredientTools) — this covers the admin-UI equivalent, both backed by
the same services/ingredients.py.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def db(mock_db):
    """mock_db (conftest.py) already patches app.routes.admin.get_db; the
    ingredient service also owns its own `cache` binding (see
    services/ingredients.py), which needs patching separately so
    upsert/delete's cache.clear() doesn't touch the real cache."""
    with patch("app.services.ingredients.cache") as mock_cache:
        yield mock_db, mock_cache


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


class TestUnauthenticated:
    @pytest.mark.parametrize("method, path", [
        ("get", "/api/admin/ingredients/coverage"),
        ("get", "/api/admin/ingredients"),
        ("get", "/api/admin/ingredients/garlic"),
        ("put", "/api/admin/ingredients/garlic"),
        ("delete", "/api/admin/ingredients/garlic"),
    ])
    def test_every_route_requires_admin(self, client, method, path):
        kwargs = {"json": {}} if method == "put" else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401


class TestCoverage:
    def test_coverage_lists_gaps_sorted_by_recipe_count(self, authenticated_client, db):
        mock_db, _ = db
        recipe_docs = [_published_recipe_doc("ramen", "Tonkotsu Ramen", ["garlic", "salt"])]
        mock_db.stream.side_effect = [iter(recipe_docs), iter([])]

        response = authenticated_client.get("/api/admin/ingredients/coverage")

        assert response.status_code == 200
        rows = response.json()
        assert {row["key"] for row in rows} == {"garlic", "salt"}
        assert all(row["covered"] is False for row in rows)


class TestListAndGet:
    def test_list_ingredients_returns_every_profile(self, authenticated_client, db):
        mock_db, _ = db
        mock_db.stream.return_value = iter([_profile_doc("garlic", "Garlic")])

        response = authenticated_client.get("/api/admin/ingredients")

        assert response.status_code == 200
        assert response.json()[0]["slug"] == "garlic"

    def test_get_ingredient_found(self, authenticated_client, db):
        mock_db, _ = db
        mock_db.get.return_value = _profile_doc("garlic", "Garlic")

        response = authenticated_client.get("/api/admin/ingredients/garlic")

        assert response.status_code == 200
        assert response.json()["name"] == "Garlic"

    def test_get_ingredient_not_found(self, authenticated_client, db):
        mock_db, _ = db
        mock_db.get.return_value = _profile_doc("ghost", "Ghost", exists=False)

        response = authenticated_client.get("/api/admin/ingredients/ghost")

        assert response.status_code == 404

    def test_get_ingredient_rejects_an_unsafe_slug(self, authenticated_client, db):
        # An embedded "/" (even %2F-encoded) never reaches this route at all —
        # Starlette's router splits on it and 404s before the handler runs,
        # which is a stronger guarantee than the service's own guard. Use a
        # value that routes fine as one segment but still isn't a real slug
        # (generate_slug() never produces uppercase or underscores) to
        # actually exercise services/ingredients.py's _require_safe_slug.
        response = authenticated_client.get("/api/admin/ingredients/Pork_Belly")
        assert response.status_code == 422


class TestUpsert:
    def test_creates_and_returns_201(self, authenticated_client, db):
        mock_db, mock_cache = db
        mock_db.stream.return_value = iter([])  # no existing profiles for the conflict check
        mock_db.get.return_value = _profile_doc("garlic", "Garlic", exists=False)

        response = authenticated_client.put(
            "/api/admin/ingredients/garlic",
            json={"name": "Garlic", "what_it_is": "An allium used across the site."},
        )

        assert response.status_code == 201
        assert response.json()["name"] == "Garlic"
        mock_cache.clear.assert_called_once()

    def test_updating_the_same_profile_twice_returns_200_the_second_time(self, authenticated_client, db):
        mock_db, mock_cache = db
        existing = _profile_doc("garlic", "Garlic")
        mock_db.stream.return_value = iter([existing])
        mock_db.get.return_value = existing

        response = authenticated_client.put(
            "/api/admin/ingredients/garlic",
            json={"name": "Garlic", "what_it_is": "An allium, updated."},
        )

        assert response.status_code == 200
        assert mock_cache.clear.call_count == 1

    def test_over_cap_prose_is_422(self, authenticated_client, db):
        mock_db, mock_cache = db
        mock_db.stream.return_value = iter([])
        mock_db.get.return_value = _profile_doc("garlic", "Garlic", exists=False)

        response = authenticated_client.put(
            "/api/admin/ingredients/garlic",
            json={
                "name": "Garlic", "what_it_is": "x" * 300, "role": "x" * 200,
                "substitutions": "x" * 400, "buying": "x" * 101,
            },
        )

        assert response.status_code == 422
        mock_cache.clear.assert_not_called()

    def test_alias_conflict_is_409(self, authenticated_client, db):
        mock_db, mock_cache = db
        mock_db.stream.return_value = iter([_profile_doc("garlic", "Garlic")])
        mock_db.get.return_value = _profile_doc("garlic-powder", "Garlic Powder", exists=False)

        response = authenticated_client.put(
            "/api/admin/ingredients/garlic-powder",
            json={"name": "Garlic Powder", "aliases": ["garlic"], "what_it_is": "Dried, ground garlic."},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["existing_slug"] == "garlic"
        mock_cache.clear.assert_not_called()

    def test_unsafe_slug_is_422(self, authenticated_client, db):
        # See TestListAndGet.test_get_ingredient_rejects_an_unsafe_slug for
        # why this uses a routable-but-not-a-real-slug value rather than an
        # embedded "/", which never reaches the handler at all.
        response = authenticated_client.put(
            "/api/admin/ingredients/Pork_Belly",
            json={"name": "X", "what_it_is": "y"},
        )
        assert response.status_code == 422


class TestDelete:
    def test_delete_existing_returns_204_and_clears_cache(self, authenticated_client, db):
        mock_db, mock_cache = db
        mock_db.get.return_value = _profile_doc("garlic", "Garlic")

        response = authenticated_client.delete("/api/admin/ingredients/garlic")

        assert response.status_code == 204
        mock_cache.clear.assert_called_once()

    def test_delete_missing_returns_404(self, authenticated_client, db):
        mock_db, mock_cache = db
        mock_db.get.return_value = _profile_doc("ghost", "Ghost", exists=False)

        response = authenticated_client.delete("/api/admin/ingredients/ghost")

        assert response.status_code == 404
        mock_cache.clear.assert_not_called()
