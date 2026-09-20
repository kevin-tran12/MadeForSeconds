"""Tests for services/ingredients.py: normalisation, the alias index,
coverage accounting, and profile CRUD.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.models import MAX_PROFILE_CHARS, IngredientProfileIn
from app.services import ingredients

from conftest import _chain_db


# ── candidate_keys ───────────────────────────────────────────────────────────

CANDIDATE_CASES = [
    ("pork belly, skin-on", ["pork belly", "belly"]),
    ("Pecorino Romano, grated", ["pecorino romano", "romano"]),
    ("canned chickpeas, drained (reserve liquid)", ["canned chickpea", "chickpea"]),
    ("guanciale or pancetta", ["guanciale or pancetta", "guanciale", "pancetta"]),
    ("paprika and parsley to garnish", ["paprika and parsley", "paprika", "parsley"]),
    ("garlic cloves", ["garlic clove", "garlic"]),
    ("green onions, sliced", ["green onion", "onion"]),
    ("light soy sauce", ["light soy sauce", "soy sauce", "sauce"]),
    ("salt", ["salt"]),
]


@pytest.mark.parametrize("item, expected", CANDIDATE_CASES, ids=[c[0] for c in CANDIDATE_CASES])
def test_candidate_keys(item, expected):
    assert ingredients.candidate_keys(item) == expected


def test_candidate_keys_empty_input():
    assert ingredients.candidate_keys("") == []
    assert ingredients.candidate_keys("   ") == []
    assert ingredients.candidate_keys("(garnish only)") == []


def test_candidate_keys_deduped_and_ordered():
    # "the sauce" and "sauce" would both canonicalise to "sauce" — only once.
    assert ingredients.candidate_keys("light soy sauce").count("sauce") == 1


# ── primary_keys ─────────────────────────────────────────────────────────────

def test_primary_keys_single_phrase_is_the_whole_head():
    assert ingredients.primary_keys("pork belly, skin-on") == ["pork belly"]


def test_primary_keys_disjunction_is_each_part_not_the_combined_head():
    assert ingredients.primary_keys("guanciale or pancetta") == ["guanciale", "pancetta"]


def test_primary_keys_empty_input():
    assert ingredients.primary_keys("") == []


# ── recipe_items ─────────────────────────────────────────────────────────────

def test_recipe_items_includes_components_and_dedupes_case_insensitively():
    doc = {
        "ingredients": [{"item": "Garlic"}, {"item": "Salt"}],
        "components": [
            {"ingredients": [{"item": "garlic"}, {"item": "Ginger"}]},  # "garlic" repeats, case-insensitive
        ],
    }
    assert ingredients.recipe_items(doc) == ["Garlic", "Salt", "Ginger"]


def test_recipe_items_ignores_malformed_entries():
    doc = {"ingredients": [{"item": ""}, {}, {"item": "  "}], "components": None}
    assert ingredients.recipe_items(doc) == []


# ── ProfileIndex / build_index / resolve ─────────────────────────────────────

def _profile(slug, name, aliases=None, **extra):
    return {
        "slug": slug, "name": name, "aliases": aliases or [],
        "what_it_is": "x", "role": "", "substitutions": "", "buying": "",
        "storage": "", "mistakes": "", "allergens": "", **extra,
    }


def test_build_index_maps_name_and_aliases():
    index = ingredients.build_index([_profile("pork-belly", "Pork Belly", aliases=["belly pork"])])
    assert index.by_key["pork belly"] == "pork-belly"
    assert index.by_key["belly pork"] == "pork-belly"


def test_build_index_raises_on_alias_conflict():
    profiles = [_profile("a", "Garlic"), _profile("b", "Garlic Powder", aliases=["garlic"])]
    with pytest.raises(ingredients.AliasConflict) as exc_info:
        ingredients.build_index(profiles)
    assert exc_info.value.key == "garlic"
    assert exc_info.value.existing_slug == "a"


def test_resolve_exact_match():
    index = ingredients.build_index([_profile("pork-belly", "Pork Belly")])
    result = index.resolve("pork belly, skin-on")
    assert result == ("pork-belly", "exact")


def test_resolve_fallback_match():
    # "light soy sauce" only matches via the shorter "soy sauce" candidate.
    index = ingredients.build_index([_profile("soy-sauce", "Soy Sauce")])
    result = index.resolve("light soy sauce")
    assert result == ("soy-sauce", "fallback")


def test_resolve_no_match_returns_none():
    index = ingredients.build_index([_profile("pork-belly", "Pork Belly")])
    assert index.resolve("dragonfruit") is None


def test_resolve_disjunction_exact_on_either_part():
    index = ingredients.build_index([_profile("pancetta", "Pancetta")])
    assert index.resolve("guanciale or pancetta") == ("pancetta", "exact")


# ── coverage ─────────────────────────────────────────────────────────────────

def _doc(slug, title, ingredient_items, components=None):
    return {
        "slug": slug, "title": title,
        "ingredients": [{"item": item} for item in ingredient_items],
        "components": components or [],
    }


def test_coverage_counts_recipes_and_sorts_by_count_desc():
    docs = [
        _doc("ramen", "Tonkotsu Ramen", ["pork belly, skin-on", "garlic cloves", "salt"]),
        _doc("carbonara", "Carbonara", ["guanciale or pancetta", "garlic"]),
    ]
    rows = ingredients.coverage([], docs)
    by_key = {row["key"]: row for row in rows}

    assert by_key["garlic"]["recipe_count"] == 2
    assert set(by_key["garlic"]["recipes"]) == {"Tonkotsu Ramen", "Carbonara"}
    assert by_key["pork belly"]["recipe_count"] == 1
    assert by_key["guanciale"]["recipe_count"] == 1
    assert by_key["pancetta"]["recipe_count"] == 1
    # sorted by recipe_count desc, then key
    assert rows[0]["key"] == "garlic"


def test_coverage_disjuncts_counted_as_separate_ingredients():
    docs = [_doc("carbonara", "Carbonara", ["guanciale or pancetta"])]
    rows = ingredients.coverage([], docs)
    keys = {row["key"] for row in rows}
    assert keys == {"guanciale", "pancetta"}  # not a combined "guanciale or pancetta" row


def test_coverage_includes_component_ingredients():
    docs = [_doc("hcr", "Hainanese Chicken Rice", [], components=[
        {"ingredients": [{"item": "ginger"}]},
    ])]
    rows = ingredients.coverage([], docs)
    assert rows[0]["key"] == "ginger"
    assert rows[0]["recipe_count"] == 1


def test_coverage_marks_covered_with_slug_and_via():
    docs = [_doc("ramen", "Tonkotsu Ramen", ["pork belly, skin-on"])]
    rows = ingredients.coverage([_profile("pork-belly", "Pork Belly")], docs)
    row = rows[0]
    assert row["covered"] is True
    assert row["profile_slug"] == "pork-belly"
    assert row["via"] == "exact"


def test_coverage_uncovered_ingredient_has_null_profile_fields():
    docs = [_doc("ramen", "Tonkotsu Ramen", ["dragonfruit"])]
    rows = ingredients.coverage([], docs)
    row = rows[0]
    assert row["covered"] is False
    assert row["profile_slug"] is None
    assert row["via"] is None


# ── IngredientProfileIn model ────────────────────────────────────────────────

def test_model_requires_what_it_is():
    with pytest.raises(ValidationError):
        IngredientProfileIn(name="Garlic", what_it_is="")


def test_model_dedupes_aliases_and_drops_the_names_own_key():
    profile = IngredientProfileIn(
        name="Garlic", what_it_is="An allium.",
        aliases=["garlic", "Garlic ", "garlic cloves", "garlic cloves"],
    )
    assert profile.aliases == ["garlic cloves"]


def test_model_accepts_prose_at_exactly_the_cap():
    # 300 + 200 + 400 + 100 == MAX_PROFILE_CHARS, each within its own per-field max.
    profile = IngredientProfileIn(
        name="Garlic", what_it_is="x" * 300, role="x" * 200, substitutions="x" * 400, buying="x" * 100,
    )
    total = sum(len(getattr(profile, field)) for field in
                ("what_it_is", "role", "substitutions", "buying", "storage", "mistakes", "allergens"))
    assert total == MAX_PROFILE_CHARS


def test_model_rejects_prose_one_char_over_the_combined_cap():
    with pytest.raises(ValidationError):
        IngredientProfileIn(
            name="Garlic", what_it_is="x" * 300, role="x" * 200, substitutions="x" * 400, buying="x" * 101,
        )


# ── CRUD ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    mock = _chain_db()
    with patch("app.services.ingredients.cache") as mock_cache:
        yield mock, mock_cache


def _profile_doc(slug, **data):
    doc = MagicMock()
    doc.id = slug
    doc.exists = True
    payload = {
        "name": "Garlic", "aliases": [], "what_it_is": "An allium.", "role": "",
        "substitutions": "", "buying": "", "storage": "", "mistakes": "", "allergens": "",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_via": "mcp",
    }
    payload.update(data)
    doc.to_dict.return_value = payload
    return doc


class TestListAndGetProfiles:
    def test_list_profiles_merges_slug_from_doc_id(self, db):
        mock, _ = db
        mock.stream.return_value = iter([_profile_doc("garlic"), _profile_doc("ginger", name="Ginger")])
        profiles = ingredients.list_profiles(mock)
        assert {p["slug"] for p in profiles} == {"garlic", "ginger"}

    def test_get_profile_not_found_returns_none(self, db):
        mock, _ = db
        mock.get.return_value.exists = False
        assert ingredients.get_profile(mock, "ghost") is None

    def test_get_profile_rejects_an_unsafe_slug(self, db):
        mock, _ = db
        with pytest.raises(ValueError):
            ingredients.get_profile(mock, "pork/belly")
        mock.get.assert_not_called()

    def test_get_profile_found(self, db):
        mock, _ = db
        mock.get.return_value = _profile_doc("garlic")
        profile = ingredients.get_profile(mock, "garlic")
        assert profile["slug"] == "garlic"
        assert profile["name"] == "Garlic"


class TestUpsertProfile:
    def test_creates_new_profile_and_clears_cache(self, db):
        mock, mock_cache = db
        mock.stream.return_value = iter([])  # no existing profiles
        mock.get.return_value.exists = False  # doc doesn't exist yet

        profile, created = ingredients.upsert_profile(
            mock, "pork-belly", {"name": "Pork Belly", "what_it_is": "A fatty cut."}, source="mcp",
        )

        assert created is True
        assert profile["name"] == "Pork Belly"
        assert profile["updated_via"] == "mcp"
        written = mock.set.call_args[0][0]
        assert written["name"] == "Pork Belly"
        mock_cache.clear.assert_called_once()

    def test_updates_existing_profile_preserves_created_at(self, db):
        mock, mock_cache = db
        mock.stream.return_value = iter([])
        original_created = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock.get.return_value = _profile_doc("pork-belly", created_at=original_created)

        profile, created = ingredients.upsert_profile(
            mock, "pork-belly", {"name": "Pork Belly", "what_it_is": "Updated text."}, source="admin",
        )

        assert created is False
        assert profile["created_at"] == original_created
        mock_cache.clear.assert_called_once()

    @pytest.mark.parametrize("slug", ["pork/belly", "../secrets", "", "pork belly", "PORK-BELLY"])
    def test_unsafe_slug_rejected_before_any_firestore_call(self, db, slug):
        """A slug containing "/" would otherwise be re-split by the Firestore
        client into a nested document path instead of a document id in this
        collection — see _SAFE_SLUG_RE's comment. Guarded before any read or
        write, not just before the final set()."""
        mock, mock_cache = db
        with pytest.raises(ValueError):
            ingredients.upsert_profile(mock, slug, {"name": "X", "what_it_is": "Y"}, source="mcp")
        mock.set.assert_not_called()
        mock_cache.clear.assert_not_called()

    def test_over_cap_prose_raises_validation_error(self, db):
        mock, _ = db
        mock.stream.return_value = iter([])
        mock.get.return_value.exists = False
        with pytest.raises(ValidationError):
            ingredients.upsert_profile(
                mock, "garlic",
                {"name": "Garlic", "what_it_is": "x" * 300, "role": "x" * 200,
                 "substitutions": "x" * 400, "buying": "x" * 101},  # 1001 total, one over the cap
                source="mcp",
            )

    def test_alias_conflict_with_a_different_profile_raises(self, db):
        mock, _ = db
        mock.stream.return_value = iter([_profile_doc("garlic", name="Garlic")])
        with pytest.raises(ingredients.AliasConflict):
            ingredients.upsert_profile(
                mock, "garlic-powder",
                {"name": "Garlic Powder", "aliases": ["garlic"], "what_it_is": "Dried, ground garlic."},
                source="mcp",
            )

    def test_updating_the_same_profile_does_not_self_conflict(self, db):
        mock, _ = db
        mock.stream.return_value = iter([_profile_doc("garlic", name="Garlic")])
        mock.get.return_value = _profile_doc("garlic")
        # Re-saving "garlic" against its own existing key must not raise.
        profile, created = ingredients.upsert_profile(
            mock, "garlic", {"name": "Garlic", "what_it_is": "An allium, updated."}, source="mcp",
        )
        assert created is False


class TestDeleteProfile:
    def test_delete_existing_clears_cache(self, db):
        mock, mock_cache = db
        mock.get.return_value.exists = True
        assert ingredients.delete_profile(mock, "garlic") is True
        mock.delete.assert_called_once()
        mock_cache.clear.assert_called_once()

    def test_delete_missing_returns_false(self, db):
        mock, mock_cache = db
        mock.get.return_value.exists = False
        assert ingredients.delete_profile(mock, "ghost") is False
        mock.delete.assert_not_called()
        mock_cache.clear.assert_not_called()

    def test_delete_rejects_an_unsafe_slug(self, db):
        mock, mock_cache = db
        with pytest.raises(ValueError):
            ingredients.delete_profile(mock, "pork/belly")
        mock.get.assert_not_called()
        mock_cache.clear.assert_not_called()
