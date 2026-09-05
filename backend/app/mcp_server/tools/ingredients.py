"""Ingredient knowledge tools: coverage, lookup, and profile authoring.

Claude drafts every profile in the owner's own MCP chat and the owner
approves each one before it is saved — there is no server-side model call
anywhere in this file. See _INSTRUCTIONS in server.py for the workflow.
"""

import logging

from ...firestore import get_db
from ...services import ingredients as ingredient_service
from ...services import recipes as recipe_service
from ...services.recipes import generate_slug
from ..errors import tool_errors

logger = logging.getLogger(__name__)


@tool_errors
def list_ingredients(coverage: str = "missing", search: str = "", limit: int = 50) -> dict:
    """Every distinct ingredient across the published catalogue, with which
    recipes use it and whether an owner-authored profile covers it — the
    starting point for an authoring session.

    coverage: "missing" (default — draft these next) | "covered" | "all".
    search: case-insensitive substring match on the ingredient's key.
    Returns {ingredients: [{key, display, recipes, recipe_count, covered,
    profile_slug, via}], count, covered_count, total_count}. `via` is
    "exact" when the ingredient's own name/alias matched, "fallback" when
    only a shorter or unit-stripped form did (e.g. "light soy sauce"
    matching a "soy sauce" profile) — worth a more specific profile.
    Sorted by recipe_count descending: the most-used gaps come first.
    """
    if coverage not in ("missing", "covered", "all"):
        raise ValueError("coverage must be one of: missing, covered, all")

    db = get_db()
    # Explicit order (recipes, then profiles) rather than inline — Python
    # evaluates function arguments left to right, so writing these as one
    # nested call would silently reverse it, which matters to any test that
    # queues .stream() results by call order.
    docs = recipe_service.get_all_published_docs(db)
    profiles = ingredient_service.list_profiles(db)
    rows = ingredient_service.coverage(profiles, docs)
    total_count = len(rows)
    covered_count = sum(1 for row in rows if row["covered"])

    if coverage == "missing":
        rows = [row for row in rows if not row["covered"]]
    elif coverage == "covered":
        rows = [row for row in rows if row["covered"]]

    needle = search.strip().lower()
    if needle:
        rows = [row for row in rows if needle in row["key"]]

    limit = max(1, min(limit, 200))
    return {
        "ingredients": rows[:limit],
        "count": min(len(rows), limit),
        "covered_count": covered_count,
        "total_count": total_count,
    }


@tool_errors
def get_ingredient(slug: str = "", name: str = "") -> dict:
    """Fetch a profile by its slug, or resolve a name/alias through the same
    index list_ingredients and the assistant use, and fetch that. Provide
    one of slug or name."""
    db = get_db()
    if slug:
        profile = ingredient_service.get_profile(db, slug)
        if profile is None:
            raise ingredient_service.IngredientNotFound(slug)
        return profile
    if name:
        index = ingredient_service.build_index(ingredient_service.list_profiles(db))
        resolved = index.resolve(name)
        if resolved is None:
            raise ingredient_service.IngredientNotFound(name)
        return index.by_slug[resolved[0]]
    raise ValueError("Provide slug or name")


@tool_errors
def upsert_ingredient(
    name: str,
    slug: str = "",
    aliases: list[str] | None = None,
    what_it_is: str | None = None,
    role: str | None = None,
    substitutions: str | None = None,
    buying: str | None = None,
    storage: str | None = None,
    mistakes: str | None = None,
    allergens: str | None = None,
) -> dict:
    """Create or update an ingredient profile. Save only what the operator
    has approved in this conversation — never an unreviewed draft.

    slug defaults to a slug generated from name (the same scheme
    create_recipe uses), so calling this again with the same name updates
    the same profile rather than creating a duplicate — safe to retry.
    On an existing profile, only the fields you pass are changed; the rest
    keep their current value. what_it_is is required on first creation.

    Each profile: a short role (fat/acid/umami/aromatic/texture...),
    substitutions (what works, what doesn't, what changes), buying, storage,
    common mistakes, and allergens — aim for roughly 150 words total across
    all of them; the combined length is capped because this text is
    rendered directly into the assistant's prompt. aliases should include
    every form recipes on the site actually use ("garlic cloves", "green
    onions"), so the assistant finds this profile from any recipe's
    ingredient list.
    """
    db = get_db()
    doc_slug = slug or generate_slug(name)
    # Read once here to merge partial updates onto the full existing profile
    # (upsert_profile's own contract is "body is the whole desired state," not
    # a patch). upsert_profile below reads the doc a second time to decide
    # created vs updated and preserve created_at — an accepted second
    # Firestore read on an authoring path with no real traffic, rather than
    # changing that already-shipped contract for this one caller.
    existing = ingredient_service.get_profile(db, doc_slug)

    body = dict(existing) if existing else {}
    body["name"] = name
    for field, value in (
        ("aliases", aliases), ("what_it_is", what_it_is), ("role", role),
        ("substitutions", substitutions), ("buying", buying), ("storage", storage),
        ("mistakes", mistakes), ("allergens", allergens),
    ):
        if value is not None:
            body[field] = value

    profile, created = ingredient_service.upsert_profile(db, doc_slug, body, source="mcp")
    updated_fields = sorted(
        field for field, value in (
            ("name", name), ("aliases", aliases), ("what_it_is", what_it_is), ("role", role),
            ("substitutions", substitutions), ("buying", buying), ("storage", storage),
            ("mistakes", mistakes), ("allergens", allergens),
        ) if value is not None
    )
    prose_chars = sum(len(profile.get(field, "") or "") for field in
                       ("what_it_is", "role", "substitutions", "buying", "storage", "mistakes", "allergens"))
    logger.info("MCP upsert_ingredient: %s (%s) created=%s", name, doc_slug, created)
    return {
        "slug": doc_slug,
        "name": profile["name"],
        "created": created,
        "updated_fields": updated_fields,
        "prose_chars": prose_chars,
        "approx_tokens": prose_chars // 4,
        "message": "Ingredient profile created." if created else "Ingredient profile updated.",
    }


@tool_errors
def delete_ingredient(slug: str) -> dict:
    """Delete an ingredient profile. The ingredient itself is unaffected —
    this only removes the owner's notes about it from the knowledge base."""
    db = get_db()
    if not ingredient_service.delete_profile(db, slug):
        raise ingredient_service.IngredientNotFound(slug)
    return {"deleted": True, "slug": slug}


TOOLS = (list_ingredients, get_ingredient, upsert_ingredient, delete_ingredient)


def register(mcp) -> None:
    """Register this module's tools on the server. Explicit, so the tool
    surface is this tuple, nothing else."""
    for tool in TOOLS:
        mcp.tool()(tool)
