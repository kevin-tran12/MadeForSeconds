"""Tests for the MCP resource and prompt surface (S12).

Both are additive: they add ways to *read* what the tools already expose and
ways to *start* a workflow, without changing any tool's signature, result, or
error contract. So these tests deliberately assert two things at once — that
the new surface works, and that it did not disturb the old one.

Everything goes through the in-memory Client rather than calling the module
functions directly, because the point of a resource is the URI routing the
SDK does on our behalf: a template with a {slug}, a static URI with no
arguments, and a declared mime type are exactly what a client depends on and
what a plain function call would not exercise.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from mcp.client import Client

from app import mcp_server
from app.mcp_server import prompts, resources

EXPECTED_RESOURCES = {"categories://list", "social://status"}
EXPECTED_TEMPLATES = {"recipe://{slug}", "ingredient://{slug}", "social-kit://{slug}"}
EXPECTED_PROMPTS = {"draft_social_post", "review_before_publish", "draft_ingredient_profiles"}


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
        "categories": ["mains"],
        "labels": ["quick"],
        "image_url": "https://storage.googleapis.com/b/img.jpg",
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


def _profile_doc(slug="pork-belly", **over):
    data = {
        "name": "pork belly",
        "aliases": ["belly"],
        "what_it_is": "The fatty slab from the underside of the pig.",
        "role": "Fat and richness.",
        "substitutions": "Shoulder is leaner.",
        "buying": "Skin-on slab.",
        "storage": "Two days, wrapped.",
        "mistakes": "Slicing it warm.",
        "allergens": "",
        "updated_via": "admin",
    }
    data.update(over)
    doc = MagicMock()
    doc.id = slug
    doc.exists = True
    doc.to_dict.return_value = data
    return doc


@pytest.fixture
def db(mcp_db):
    """conftest.py's mcp_db — which, since S12, also patches
    app.mcp_server.resources.get_db (resources.py binds its own)."""
    return mcp_db


def _text(result):
    """The single text body of a read_resource result.

    Asserting exactly one content block matters: a resource that silently
    returned two would still pass a naive contents[0] read.
    """
    contents = result.contents
    assert len(contents) == 1
    return contents[0].text


# ── Surface ──────────────────────────────────────────────────────────────────


class TestResourceSurface:
    @pytest.mark.asyncio
    async def test_static_resources_are_registered(self, db):
        async with Client(mcp_server.mcp) as c:
            result = await c.list_resources()
        assert {str(r.uri) for r in result.resources} == EXPECTED_RESOURCES
        for resource in result.resources:
            assert resource.description, f"{resource.uri} has no description"
            assert resource.mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_templates_are_registered(self, db):
        """A URI with a {param} must register as a template, not a static
        resource — a client lists and fills these differently."""
        async with Client(mcp_server.mcp) as c:
            result = await c.list_resource_templates()
        assert {t.uri_template for t in result.resource_templates} == EXPECTED_TEMPLATES
        for template in result.resource_templates:
            assert template.description
            assert template.mime_type == "application/json"

    @pytest.mark.asyncio
    async def test_registered_surface_equals_the_module_tuples(self, db):
        """The same guarantee register() gives for tools: the surface is
        exactly what the module lists, never an accident of import order."""
        async with Client(mcp_server.mcp) as c:
            static = {str(r.uri) for r in (await c.list_resources()).resources}
            templates = {t.uri_template for t in (await c.list_resource_templates()).resource_templates}
        assert static == {uri for uri, _fn, _n, _d in resources.RESOURCES}
        assert templates == {uri for uri, _fn, _n, _d in resources.RESOURCE_TEMPLATES}

    @pytest.mark.asyncio
    async def test_tool_surface_is_unchanged_by_this_story(self, db):
        """S12 is additive. If registering resources or prompts ever costs or
        renames a tool, that is a regression this file should catch."""
        async with Client(mcp_server.mcp) as c:
            names = {t.name for t in (await c.list_tools()).tools}
        assert len(names) == 19
        assert "get_social_kit" in names


# ── Reads ────────────────────────────────────────────────────────────────────


class TestResourceReads:
    @pytest.mark.asyncio
    async def test_recipe_template_returns_the_owners_view(self, db):
        db.stream.return_value = iter([_doc(sous_chef_notes="private note")])
        async with Client(mcp_server.mcp) as c:
            result = await c.read_resource("recipe://test-recipe")
        body = json.loads(_text(result))
        assert body["slug"] == "test-recipe"
        # AdminRecipe, not the public Recipe: sous_chef_notes survives.
        assert body["sous_chef_notes"] == "private note"

    @pytest.mark.asyncio
    async def test_categories_resource_reads_the_allowlist(self, db):
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {"list": ["Mains", "Desserts"]}
        db.get.return_value = doc
        async with Client(mcp_server.mcp) as c:
            result = await c.read_resource("categories://list")
        assert json.loads(_text(result)) == {"categories": ["Desserts", "Mains"]}

    @pytest.mark.asyncio
    async def test_ingredient_template_returns_the_profile(self, db):
        db.get.return_value = _profile_doc()
        async with Client(mcp_server.mcp) as c:
            result = await c.read_resource("ingredient://pork-belly")
        body = json.loads(_text(result))
        assert body["name"] == "pork belly"
        assert body["slug"] == "pork-belly"

    @pytest.mark.asyncio
    async def test_social_kit_template_matches_the_tool(self, db):
        """The resource and the tool must not drift: build_social_kit is the
        single source, and this is what proves the split stayed honest."""
        db.stream.return_value = iter([_doc()])
        db.get.return_value = MagicMock(exists=False)
        async with Client(mcp_server.mcp) as c:
            result = await c.read_resource("social-kit://test-recipe")
        from_resource = json.loads(_text(result))

        db.stream.return_value = iter([_doc()])
        from_tool = mcp_server.get_social_kit(slug="test-recipe")
        assert from_resource == json.loads(json.dumps(from_tool))

    @pytest.mark.asyncio
    async def test_missing_recipe_is_a_failed_read_not_an_error_dict(self, db):
        """Tools return {"error": "not_found"} as normal content because a
        model benefits from structured in-band failure. A resource has no such
        convention, so a missing URI must fail the read instead of returning a
        success whose body happens to describe a failure."""
        db.stream.return_value = iter([])
        db.get.return_value = _doc(exists=False)
        async with Client(mcp_server.mcp) as c:
            with pytest.raises(Exception) as excinfo:
                await c.read_resource("recipe://ghost")
        # The SDK reports it as a failed read naming the URI, and does not
        # leak RecipeNotFound's type or a traceback to the client.
        message = str(excinfo.value)
        assert "recipe://ghost" in message
        assert "RecipeNotFound" not in message
        assert "Traceback" not in message

    @pytest.mark.asyncio
    async def test_missing_ingredient_is_a_failed_read(self, db):
        db.get.return_value = MagicMock(exists=False)
        async with Client(mcp_server.mcp) as c:
            with pytest.raises(Exception):
                await c.read_resource("ingredient://nope")


# ── Prompts ──────────────────────────────────────────────────────────────────


class TestPrompts:
    @pytest.mark.asyncio
    async def test_prompts_are_registered_with_descriptions(self, db):
        async with Client(mcp_server.mcp) as c:
            result = await c.list_prompts()
        assert {p.name for p in result.prompts} == EXPECTED_PROMPTS
        assert {p.name for p in result.prompts} == {fn.__name__ for fn, _d in prompts.PROMPTS}
        for prompt in result.prompts:
            assert prompt.description

    @pytest.mark.asyncio
    async def test_draft_social_post_carries_voice_and_the_approval_step(self, db):
        db.stream.return_value = iter([_doc()])
        db.get.return_value = MagicMock(exists=False)
        async with Client(mcp_server.mcp) as c:
            result = await c.get_prompt("draft_social_post", {"slug": "test-recipe"})
        text = "\n".join(m.content.text for m in result.messages)
        assert "Test Recipe" in text
        for heading in ("VOICE", "HASHTAGS", "WHAT TO PRODUCE"):
            assert heading in text
        # The rule that keeps a drafting prompt from becoming a posting one.
        assert "never publish, post, or save anything unasked" in text.lower()

    @pytest.mark.asyncio
    async def test_review_before_publish_separates_blocking_from_warnings(self, db):
        """publish_recipe refuses without ingredients+instructions but only
        warns about an image, so the prompt must not present them alike."""
        db.get.return_value = _doc(instructions=[], image_url=None)
        async with Client(mcp_server.mcp) as c:
            result = await c.get_prompt("review_before_publish", {"recipe_id": "doc-id"})
        text = "\n".join(m.content.text for m in result.messages)
        blocking, warnings = text.split("WORTH FIXING FIRST")
        assert "no instructions" in blocking
        assert "no image" in warnings
        assert "no instructions" not in warnings

    @pytest.mark.asyncio
    async def test_review_before_publish_reports_a_complete_recipe_as_clean(self, db):
        db.get.return_value = _doc(secrets=[{"title": "T", "body": "B"}], sous_chef_notes="n")
        async with Client(mcp_server.mcp) as c:
            result = await c.get_prompt("review_before_publish", {"recipe_id": "doc-id"})
        text = "\n".join(m.content.text for m in result.messages)
        assert "BLOCKING\n- none" in text

    @pytest.mark.asyncio
    async def test_draft_ingredient_profiles_says_so_when_coverage_cannot_be_read(self, db):
        """list_ingredients wears @mcp_tool, so a failure arrives as an error
        dict, not an exception. Rendering that as an empty gap list would tell
        the operator every ingredient is already covered — confidently wrong
        in the one direction that stops them authoring anything."""
        with patch(
            "app.mcp_server.prompts.list_ingredients",
            return_value={"error": "internal", "message": "firestore down"},
        ):
            async with Client(mcp_server.mcp) as c:
                result = await c.get_prompt("draft_ingredient_profiles", {"limit": "5"})
        text = "\n".join(m.content.text for m in result.messages)
        assert "could not read ingredient coverage" in text.lower()
        assert "firestore down" in text
        assert "every ingredient" not in text.lower()

    @pytest.mark.asyncio
    async def test_draft_ingredient_profiles_names_the_uncovered_gaps(self, db):
        """Note the string "5": MCP sends prompt arguments as strings
        (GetPromptRequestParams types them dict[str, str]), so the int
        annotation on draft_ingredient_profiles is coerced server-side rather
        than received as an int. Passing 5 here fails client-side validation.
        """
        db.stream.side_effect = [iter([_doc()]), iter([])]
        async with Client(mcp_server.mcp) as c:
            result = await c.get_prompt("draft_ingredient_profiles", {"limit": "5"})
        text = "\n".join(m.content.text for m in result.messages)
        assert "water" in text.lower()
        assert "1,000 characters" in text
        assert "upsert_ingredient" in text
