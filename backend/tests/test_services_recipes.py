"""Unit tests for the recipe domain service (app/services/recipes.py)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models import RecipeCreate, RecipeUpdate
from app.services import recipes as svc


def _chain_db():
    """Chainable Firestore mock matching the conftest pattern."""
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
        "categories": [],
        "image_url": None,
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
    return _chain_db()


@pytest.fixture
def svc_cache():
    with patch("app.services.recipes.cache") as mock:
        yield mock


# ── generate_slug ─────────────────────────────────────────────────────────────

class TestGenerateSlug:
    def test_basic_title(self):
        assert svc.generate_slug("Hainanese Chicken Rice") == "hainanese-chicken-rice"

    def test_strips_punctuation_and_edges(self):
        assert svc.generate_slug("  Mom's BEST PHO!! ") == "mom-s-best-pho"

    def test_collapses_runs_of_symbols(self):
        assert svc.generate_slug("a -- b") == "a-b"


# ── doc_to_recipe ─────────────────────────────────────────────────────────────

class TestDocToRecipe:
    def test_migrates_legacy_nutrition_dict(self):
        doc = _doc(nutrition={"calories": 500.0, "protein": 30.0})
        recipe = svc.doc_to_recipe(doc)
        assert {n.label: n.value for n in recipe.nutrition} == {"calories": 500.0, "protein": 30.0}

    def test_strips_premium_content_fields(self):
        doc = _doc(premium_content="secret", has_premium_content=True)
        recipe = svc.doc_to_recipe(doc)
        assert not hasattr(recipe, "premium_content")


# ── find_by_slug ──────────────────────────────────────────────────────────────

class TestFindBySlug:
    def test_returns_none_when_absent(self, db):
        db.stream.return_value = iter([])
        assert svc.find_by_slug(db, "nope") is None

    def test_returns_serializable_pointer(self, db):
        db.stream.return_value = iter([_doc(id="abc", published=True)])
        found = svc.find_by_slug(db, "test-recipe")
        assert found == {
            "id": "abc",
            "slug": "test-recipe",
            "title": "Test Recipe",
            "published": True,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }


# ── create_recipe ─────────────────────────────────────────────────────────────

class TestCreateRecipe:
    def test_sets_slug_timestamps_and_source(self, db, svc_cache):
        db.stream.return_value = iter([])  # no slug conflict
        db.document.return_value.id = "new-id"

        recipe = svc.create_recipe(db, RecipeCreate(title="New Recipe"), source="mcp")

        assert recipe.slug == "new-recipe"
        assert recipe.id == "new-id"
        written = db.set.call_args[0][0]
        assert written["created_via"] == "mcp"
        assert written["created_at"] == written["updated_at"]
        svc_cache.clear.assert_called_once()

    def test_raises_slug_conflict_with_pointer(self, db, svc_cache):
        db.stream.return_value = iter([_doc(id="existing-id", slug="new-recipe")])

        with pytest.raises(svc.SlugConflict) as exc:
            svc.create_recipe(db, RecipeCreate(title="New Recipe"), source="admin")

        assert exc.value.existing["id"] == "existing-id"
        db.set.assert_not_called()
        svc_cache.clear.assert_not_called()

    def test_raises_invalid_categories(self, db, svc_cache):
        config_doc = MagicMock()
        config_doc.exists = True
        config_doc.to_dict.return_value = {"list": ["mains", "sides"]}
        db.get.return_value = config_doc

        with pytest.raises(svc.InvalidCategories) as exc:
            svc.create_recipe(
                db, RecipeCreate(title="X", categories=["desserts"]), source="admin"
            )

        assert exc.value.invalid == ["desserts"]
        assert exc.value.allowed == ["mains", "sides"]
        db.set.assert_not_called()


# ── update_recipe ─────────────────────────────────────────────────────────────

class TestUpdateRecipe:
    def test_raises_not_found(self, db, svc_cache):
        db.get.return_value = _doc(exists=False)
        with pytest.raises(svc.RecipeNotFound):
            svc.update_recipe(db, "ghost", RecipeUpdate(title="X"), source="admin")

    def test_sets_updated_via_and_clears_cache(self, db, svc_cache):
        db.get.side_effect = [_doc(), _doc(title="New Title")]

        recipe = svc.update_recipe(
            db, "doc-id", RecipeUpdate.model_validate({"title": "New Title"}), source="mcp"
        )

        assert recipe.title == "New Title"
        updates = db.update.call_args[0][0]
        assert updates["updated_via"] == "mcp"
        assert "slug" not in updates and "published" not in updates
        svc_cache.clear.assert_called_once()

    def test_replaced_image_blob_deleted(self, db, svc_cache):
        old_url = "https://storage.googleapis.com/b/old.jpg"
        new_url = "https://storage.googleapis.com/b/new.jpg"
        db.get.side_effect = [_doc(image_url=old_url), _doc(image_url=new_url)]

        with patch("app.services.uploads.delete_recipe_image_blob") as deleter:
            svc.update_recipe(
                db, "doc-id", RecipeUpdate.model_validate({"image_url": new_url}), source="admin"
            )

        deleter.assert_called_once_with(old_url)

    def test_image_untouched_when_not_in_update(self, db, svc_cache):
        db.get.side_effect = [_doc(image_url="https://x/img.jpg"), _doc(title="T")]

        with patch("app.services.uploads.delete_recipe_image_blob") as deleter:
            svc.update_recipe(
                db, "doc-id", RecipeUpdate.model_validate({"title": "T"}), source="admin"
            )

        deleter.assert_not_called()


# ── set_published ─────────────────────────────────────────────────────────────

class TestSetPublished:
    def test_blocks_publish_of_empty_recipe(self, db, svc_cache):
        db.get.return_value = _doc(ingredients=[], instructions=[], components=None)

        with pytest.raises(svc.NotPublishable):
            svc.set_published(db, "doc-id", True, source="mcp")

        db.update.assert_not_called()

    def test_components_only_recipe_is_publishable(self, db, svc_cache):
        component = {
            "title": "Rice",
            "ingredients": [{"item": "Rice", "amount": "1", "unit": "cup"}],
            "instructions": [{"step": 1, "text": "Cook"}],
        }
        doc = _doc(ingredients=[], instructions=[], components=[component])
        db.get.side_effect = [doc, _doc(published=True, components=[component])]

        recipe, warnings = svc.set_published(db, "doc-id", True, source="mcp")

        assert recipe.published is True
        svc_cache.clear.assert_called_once()

    def test_warns_on_missing_image_and_categories(self, db, svc_cache):
        db.get.side_effect = [
            _doc(image_url=None, categories=[]),
            _doc(published=True),
        ]

        _, warnings = svc.set_published(db, "doc-id", True, source="mcp")

        assert "Recipe has no image" in warnings
        assert "Recipe has no categories" in warnings

    def test_unpublish_never_warns(self, db, svc_cache):
        db.get.side_effect = [
            _doc(ingredients=[], instructions=[], published=True),
            _doc(published=False),
        ]

        recipe, warnings = svc.set_published(db, "doc-id", False, source="mcp")

        assert warnings == []
        assert recipe.published is False


# ── delete_recipe ─────────────────────────────────────────────────────────────

class TestDeleteRecipe:
    def test_require_draft_refuses_published(self, db, svc_cache):
        db.get.return_value = _doc(published=True)

        with pytest.raises(svc.RecipeServiceError):
            svc.delete_recipe(db, "doc-id", require_draft=True)

        db.delete.assert_not_called()

    def test_deletes_image_and_receipt_blobs(self, db, svc_cache):
        db.get.return_value = _doc(
            image_url="https://storage.googleapis.com/b/img.jpg",
            receipt_urls=["https://storage.googleapis.com/r/r1.jpg", "https://storage.googleapis.com/r/r2.jpg"],
        )

        with (
            patch("app.services.uploads.delete_recipe_image_blob") as img_deleter,
            patch("app.services.uploads.delete_recipe_receipt_blob") as receipt_deleter,
        ):
            svc.delete_recipe(db, "doc-id")

        img_deleter.assert_called_once()
        assert receipt_deleter.call_count == 2
        db.delete.assert_called_once()
        svc_cache.clear.assert_called_once()
