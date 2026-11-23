"""Tests for the ChatGPT discovery pair, tools/discovery.py (search / fetch).

ChatGPT's chat and deep-research modes call exactly two tools with a fixed
contract (developers.openai.com/api/docs/mcp): search(query) returning
{"results": [{id, title, url}]} and fetch(id) returning {id, title, text,
url, metadata}, each delivered as structuredContent plus the same JSON in a
text block. The direct-call tests below pin the shapes and the ranking; the
in-memory Client tests pin the wire format, since that is what a plain
function call cannot show and what ChatGPT actually depends on.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from mcp.client import Client

from app import mcp_server
from app.mcp_server.tools import discovery


def _recipe_data(**over):
    data = {
        "title": "Pho Ga",
        "slug": "pho-ga",
        "description": "Chicken noodle soup with charred ginger.",
        "ingredients": [
            {"item": "chicken thighs", "amount": "2", "unit": "lb"},
            {"item": "fish sauce", "amount": "2", "unit": "tbsp", "group": "Broth"},
        ],
        "instructions": [{"step": 1, "text": "Char the ginger.", "tip": "Right on the flame."}],
        "prep_time_minutes": 20,
        "cook_time_minutes": 90,
        "servings": 4,
        "difficulty": "medium",
        "categories": ["soups"],
        "labels": ["weeknight"],
        "image_url": "https://storage.googleapis.com/b/pho.jpg",
        "published": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    data.update(over)
    return data


def _doc(id="doc-id", exists=True, **data):
    doc = MagicMock()
    doc.id = id
    doc.exists = exists
    doc.to_dict.return_value = _recipe_data(**data)
    return doc


def _profile_doc(slug="fish-sauce", **over):
    doc = MagicMock()
    doc.id = slug
    doc.exists = True
    data = {
        "name": "Fish sauce",
        "aliases": ["nuoc mam"],
        "what_it_is": "Fermented anchovy liquid; salty umami.",
        "role": "umami",
        "substitutions": "Soy sauce plus a pinch of salt, less depth.",
        "updated_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
    }
    data.update(over)
    doc.to_dict.return_value = data
    return doc


@pytest.fixture
def db(mcp_db):
    return mcp_db


@pytest.fixture
def frontend(monkeypatch):
    monkeypatch.setattr(discovery.settings, "frontend_url", "https://site.example/")


# ── search ──────────────────────────────────────────────────────────────────


class TestSearch:
    def test_title_hits_rank_above_body_hits_and_ingredients(self, db, frontend):
        # Stream call order follows the code: the recipe scan first, then the
        # ingredient profile listing (see _search_recipes / _search_ingredients).
        db.stream.side_effect = [
            iter([
                _doc(id="a", title="Tom Yum", slug="tom-yum", description="A sour soup, fish sauce forward."),
                _doc(id="b", title="Fish Sauce Wings", slug="fish-sauce-wings"),
                _doc(id="c", title="Banh Mi", slug="banh-mi", description="Sandwich", categories=["lunch"]),
            ]),
            iter([
                _profile_doc(),
                # Matches only in its body text, so it ranks below even a
                # recipe description hit.
                _profile_doc(slug="salt", name="Salt", aliases=[], what_it_is="Season fish sauce dishes lightly."),
            ]),
        ]

        result = mcp_server.search(query="fish sauce")

        assert [r["id"] for r in result["results"]] == [
            "recipe:fish-sauce-wings",   # title hit
            "ingredient:fish-sauce",     # ingredient name hit
            "recipe:tom-yum",            # description hit
            "ingredient:salt",           # ingredient body-only hit
        ]
        assert set(result["results"][0]) == {"id", "title", "url"}

    def test_every_term_must_match_and_case_is_ignored(self, db):
        db.stream.side_effect = [
            iter([_doc(id="a", title="Pho Ga", slug="pho-ga"), _doc(id="b", title="Pho Bo", slug="pho-bo")]),
            iter([]),
        ]
        result = mcp_server.search(query="PHO ga")
        assert [r["id"] for r in result["results"]] == ["recipe:pho-ga"]

    def test_url_is_the_public_page_only_for_published_recipes(self, db, frontend):
        db.stream.side_effect = [
            iter([
                _doc(id="a", title="Pho Ga", slug="pho-ga", published=True),
                _doc(id="b", title="Pho Bo", slug="pho-bo", published=False),
            ]),
            iter([_profile_doc(slug="pho-spice", name="Pho spice")]),
        ]
        by_id = {r["id"]: r for r in mcp_server.search(query="pho")["results"]}
        assert by_id["recipe:pho-ga"]["url"] == "https://site.example/recipes/pho-ga/"
        assert by_id["recipe:pho-bo"]["url"] == ""
        assert by_id["ingredient:pho-spice"]["url"] == ""
        assert by_id["ingredient:pho-spice"]["title"] == "Pho spice (ingredient)"

    def test_blank_query_returns_no_results_without_touching_firestore(self, db):
        assert mcp_server.search(query="   ") == {"results": []}
        db.stream.assert_not_called()

    def test_scan_is_bounded(self, db):
        db.stream.side_effect = [iter([]), iter([])]
        mcp_server.search(query="x")
        db.limit.assert_any_call(discovery._MAX_SCANNED_RECIPES)

    def test_a_full_scan_logs_truncation(self, db, caplog):
        """Recipes older than the cap are unsearchable; that must be visible
        in the log (MCP_SEARCH_TRUNCATED), not silent."""
        docs = [_doc(id=f"r{i}", slug=f"r-{i}", title=f"Recipe {i}") for i in range(discovery._MAX_SCANNED_RECIPES)]
        db.stream.side_effect = [iter(docs), iter([])]
        with caplog.at_level("WARNING", logger="app.mcp_server.tools.discovery"):
            result = mcp_server.search(query="recipe")
        assert result["results"], "the scan itself still returns hits"
        assert any("MCP_SEARCH_TRUNCATED" in r.message for r in caplog.records)

    def test_a_partial_scan_does_not_log_truncation(self, db, caplog):
        db.stream.side_effect = [iter([_doc(id="a")]), iter([])]
        with caplog.at_level("WARNING", logger="app.mcp_server.tools.discovery"):
            mcp_server.search(query="pho")
        assert not any("MCP_SEARCH_TRUNCATED" in r.message for r in caplog.records)


# ── fetch ───────────────────────────────────────────────────────────────────


class TestFetch:
    def test_recipe_by_prefixed_slug_renders_text_and_metadata(self, db, frontend):
        db.stream.return_value = iter([_doc(id="r1")])

        result = mcp_server.fetch(id="recipe:pho-ga")

        assert set(result) == {"id", "title", "text", "url", "metadata"}
        assert result["id"] == "recipe:pho-ga"
        assert result["title"] == "Pho Ga"
        assert result["url"] == "https://site.example/recipes/pho-ga/"
        text = result["text"]
        assert text.startswith("# Pho Ga\n")
        assert "Chicken noodle soup" in text
        assert "## Ingredients" in text and "- 2 lb chicken thighs" in text
        assert "\nBroth:\n- 2 tbsp fish sauce" in text
        assert "## Instructions" in text and "1. Char the ginger." in text
        assert "Tip: Right on the flame." in text
        assert result["metadata"]["recipe_id"] == "r1"
        assert result["metadata"]["kind"] == "recipe"
        assert result["metadata"]["published"] is True
        # model_dump(mode="json") already serialised the datetime (RFC 3339, "Z").
        assert result["metadata"]["updated_at"] == "2026-01-02T00:00:00Z"

    def test_ingredient_groups_close_and_blank_amounts_do_not_double_space(self, db):
        db.stream.return_value = iter([_doc(id="r1", ingredients=[
            {"item": "chicken", "amount": "2", "unit": "lb"},
            {"item": "fish sauce", "amount": "2", "unit": "tbsp", "group": "Broth"},
            {"item": "star anise", "amount": "", "unit": "", "group": "Broth"},
            {"item": "lime", "amount": "1", "unit": "", "group": None},
        ])])
        text = mcp_server.fetch(id="recipe:pho-ga")["text"]
        assert (
            "## Ingredients\n- 2 lb chicken\n\nBroth:\n- 2 tbsp fish sauce\n- star anise\n\nOther:\n- 1 lime\n"
        ) in text

    def test_bare_slug_is_treated_as_a_recipe(self, db):
        db.stream.return_value = iter([_doc(id="r1")])
        assert mcp_server.fetch(id="pho-ga")["id"] == "recipe:pho-ga"

    def test_falls_back_to_a_firestore_recipe_id(self, db):
        db.stream.return_value = iter([])  # no slug match
        db.get.return_value = _doc(id="r1")
        assert mcp_server.fetch(id="r1")["metadata"]["recipe_id"] == "r1"

    def test_draft_has_no_url_and_includes_owner_notes(self, db, frontend):
        db.stream.return_value = iter([_doc(id="r1", published=False, sous_chef_notes="Go easy on the salt.")])
        result = mcp_server.fetch(id="recipe:pho-ga")
        assert result["url"] == ""
        assert "## Sous Chef notes\nGo easy on the salt." in result["text"]

    def test_components_nutrition_and_secrets_are_rendered(self, db):
        db.stream.return_value = iter([_doc(
            id="r1",
            components=[{
                "title": "Nuoc cham",
                "description": "The dipping sauce.",
                "yield_description": "About 1 cup",
                "ingredients": [{"item": "lime juice", "amount": "3", "unit": "tbsp"}],
                "prep_steps": [{"step": 1, "text": "Juice the limes."}],
                "instructions": [{"step": 1, "text": "Stir."}],
            }],
            nutrition=[{"label": "Calories", "value": 420.5, "unit": "kcal"}],
            secrets=[{"title": "The trick", "body": "Char the onion too."}],
        )])
        text = mcp_server.fetch(id="recipe:pho-ga")["text"]
        assert (
            "## Nuoc cham\nThe dipping sauce.\nYield: About 1 cup\nIngredients:\n- 3 tbsp lime juice\n"
            "Prep:\n1. Juice the limes.\nSteps:\n1. Stir."
        ) in text
        assert "## Nutrition\n- Calories: 420.5 kcal" in text
        assert "## The trick\nChar the onion too." in text

    def test_ingredient_profile(self, db):
        db.get.return_value = _profile_doc()

        result = mcp_server.fetch(id="ingredient:fish-sauce")

        assert result["id"] == "ingredient:fish-sauce"
        assert result["title"] == "Fish sauce (ingredient)"
        assert result["url"] == ""
        assert result["text"].startswith("# Fish sauce\n\nAlso called: nuoc mam\n")
        assert "## Substitutions\nSoy sauce plus a pinch of salt, less depth." in result["text"]
        assert result["metadata"] == {
            "kind": "ingredient",
            "slug": "fish-sauce",
            "aliases": ["nuoc mam"],
            "updated_at": "2026-01-03T00:00:00+00:00",
        }

    def test_unknown_recipe_is_a_structured_not_found(self, db):
        db.stream.return_value = iter([])
        db.get.return_value.exists = False
        assert mcp_server.fetch(id="recipe:ghost")["error"] == "not_found"

    def test_unknown_ingredient_is_a_structured_not_found(self, db):
        db.get.return_value.exists = False
        assert mcp_server.fetch(id="ingredient:ghost")["error"] == "not_found"

    def test_blank_id_is_invalid_request(self, db):
        assert mcp_server.fetch(id=" ")["error"] == "invalid_request"


# ── wire format — what ChatGPT actually reads ───────────────────────────────


class TestWireFormat:
    """ChatGPT reads structuredContent and falls back to the JSON text block;
    the OpenAI docs ask for both, carrying the same value."""

    @pytest.mark.asyncio
    async def test_search_result_is_structured_and_mirrored_as_json_text(self, db, frontend):
        db.stream.side_effect = [iter([_doc(id="a")]), iter([])]
        async with Client(mcp_server.mcp) as c:
            result = await c.call_tool("search", {"query": "pho"})
        assert result.is_error is False
        expected = {"results": [{"id": "recipe:pho-ga", "title": "Pho Ga", "url": "https://site.example/recipes/pho-ga/"}]}
        assert result.structured_content == expected
        assert json.loads(result.content[0].text) == expected

    @pytest.mark.asyncio
    async def test_fetch_result_is_structured_and_mirrored_as_json_text(self, db):
        db.stream.return_value = iter([_doc(id="r1")])
        async with Client(mcp_server.mcp) as c:
            result = await c.call_tool("fetch", {"id": "recipe:pho-ga"})
        assert result.is_error is False
        assert set(result.structured_content) == {"id", "title", "text", "url", "metadata"}
        assert json.loads(result.content[0].text) == result.structured_content

    @pytest.mark.asyncio
    async def test_not_found_still_validates_against_the_open_output_schema(self, db):
        """The error-dict contract (see test_mcp_transport's output-schema
        note) survives declaring an output schema: it is an open object."""
        db.stream.return_value = iter([])
        db.get.return_value.exists = False
        async with Client(mcp_server.mcp) as c:
            result = await c.call_tool("fetch", {"id": "recipe:ghost"})
        assert result.is_error is False
        assert result.structured_content["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_schemas_name_the_chatgpt_arguments(self):
        async with Client(mcp_server.mcp) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
        assert tools["search"].input_schema["required"] == ["query"]
        assert tools["fetch"].input_schema["required"] == ["id"]
        assert tools["search"].annotations.read_only_hint is True
        assert tools["fetch"].annotations.read_only_hint is True
