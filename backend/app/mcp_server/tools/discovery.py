"""Discovery tools: the ``search`` / ``fetch`` pair ChatGPT looks for.

ChatGPT's connector surface works in two modes. In developer mode (and in
the Apps SDK) it calls any tool the server exposes, so every tool in this
package is already reachable from ChatGPT once the OAuth flow completes.
Its ordinary chat and deep-research modes, however, only ever call two
read-only tools with a fixed contract (developers.openai.com/api/docs/mcp):

- ``search(query)`` → ``{"results": [{"id", "title", "url"}]}``
- ``fetch(id)``     → ``{"id", "title", "text", "url", "metadata"}``

Both are returned as ``structuredContent`` *and* as the same JSON encoded in
a text content block — which is exactly what the mcp SDK emits for a tool
whose return annotation is ``dict[str, Any]`` (an open ``object`` output
schema, so the ``{"error": ...}`` dicts ``mcp_tool`` produces on a domain
failure still validate; see ``test_mcp_transport.py``'s output-schema
snapshot for why no other tool declares one).

What is searchable: every recipe (drafts included — the caller is the
authenticated owner, same as ``list_recipes``) and every owner-authored
ingredient profile. Ids are namespaced (``recipe:<slug>``,
``ingredient:<slug>``) so one ``fetch`` serves both; a bare slug is treated
as a recipe for convenience. ``url`` is the public recipe page for a
published recipe and empty otherwise — ChatGPT only builds a citation from
a non-empty ``url``, and a draft has no page a reader could follow.

Nothing here is Claude-specific or ChatGPT-specific in behaviour: a Claude
client may call ``search`` too, it is simply a friendlier entry point than
``list_recipes`` for a free-text question. Neither tool writes anything, so
neither carries an audit row (``read_only=True``), and both draw on the
``read`` rate budget like every other read.
"""

import logging
from typing import Any

from google.cloud.firestore_v1.base_query import FieldFilter

from ...config import settings
from ...firestore import get_db
from ...services import ingredients as ingredient_service
from ...services import recipes as recipe_service
from ..wrapper import iso, mcp_tool
from .recipes import _lookup_recipe

logger = logging.getLogger(__name__)

RECIPE_PREFIX = "recipe:"
INGREDIENT_PREFIX = "ingredient:"

# Recipe fields the search scan reads. Firestore's select() keeps the scan
# to a projection rather than whole documents (instructions and components
# are the bulk of a recipe and are not searched).
_SEARCH_FIELDS = (
    "slug", "title", "description", "published", "created_at", "updated_at", "categories", "labels",
)
# Hard cap on how many recipes one search call scans, so a single call can
# never walk an unbounded collection. 1000 is an order of magnitude above
# the catalogue; if a scan ever fills it, recipes older than the cap become
# unsearchable, so _search_recipes logs MCP_SEARCH_TRUNCATED when that
# happens rather than failing silently.
_MAX_SCANNED_RECIPES = 1000
_MAX_RESULTS = 50


def _public_recipe_url(slug: str, published: bool) -> str:
    if not (slug and published):
        return ""
    return f"{settings.frontend_url.rstrip('/')}/recipes/{slug}/"


def _terms(query: str) -> list[str]:
    return [t for t in query.lower().split() if t]


def _matches(terms: list[str], haystack: str) -> bool:
    return all(t in haystack for t in terms)


def _recipe_search_query():
    return (
        get_db()
        .collection("recipes")
        .order_by("created_at", direction="DESCENDING")
        .select(list(_SEARCH_FIELDS))
        .limit(_MAX_SCANNED_RECIPES)
    )


def _search_recipes(terms: list[str]) -> list[tuple[int, dict]]:
    """(rank, result) pairs — rank 0 for a title hit, 1 for anything else."""
    hits: list[tuple[int, dict]] = []
    scanned = 0
    for doc in _recipe_search_query().stream():
        scanned += 1
        data = doc.to_dict() or {}
        title = data.get("title", "")
        rest = " ".join(
            [data.get("description", ""), *data.get("categories", []), *data.get("labels", [])]
        )
        title_l = title.lower()
        if _matches(terms, title_l):
            rank = 0
        elif _matches(terms, f"{title_l} {rest.lower()}"):
            rank = 1
        else:
            continue
        slug = data.get("slug", "")
        hits.append((
            rank,
            {
                "id": f"{RECIPE_PREFIX}{slug}" if slug else f"{RECIPE_PREFIX}{doc.id}",
                "title": title,
                "url": _public_recipe_url(slug, data.get("published", False)),
            },
        ))
    if scanned >= _MAX_SCANNED_RECIPES:
        logger.warning(
            "MCP_SEARCH_TRUNCATED scanned=%d cap=%d — recipes older than the cap are not searchable",
            scanned,
            _MAX_SCANNED_RECIPES,
        )
    return hits


def _search_ingredients(terms: list[str]) -> list[tuple[int, dict]]:
    hits: list[tuple[int, dict]] = []
    for profile in ingredient_service.list_profiles(get_db()):
        name = profile.get("name", "") or profile.get("slug", "")
        names = " ".join([name, *profile.get("aliases", [])]).lower()
        body = " ".join(
            str(profile.get(k, "")) for k in ("what_it_is", "role", "substitutions", "buying", "storage", "mistakes")
        ).lower()
        if _matches(terms, names):
            rank = 0
        elif _matches(terms, f"{names} {body}"):
            rank = 2  # a body-only ingredient hit ranks below a recipe body hit
        else:
            continue
        hits.append((
            rank,
            {"id": f"{INGREDIENT_PREFIX}{profile['slug']}", "title": f"{name} (ingredient)", "url": ""},
        ))
    return hits


@mcp_tool(read_only=True, budget="read")
def search(query: str) -> dict[str, Any]:
    """Search recipes (drafts included) and ingredient profiles by free text.

    Every word in `query` must appear (case-insensitive) in a recipe's
    title, description, categories or labels, or in an ingredient profile's
    name, aliases or body. Title/name hits rank first. Returns
    {results: [{id, title, url}]} — pass a result's `id` to `fetch` for the
    full document. `url` is the public page for a published recipe and
    empty for drafts and ingredient profiles, which have no public page.
    """
    terms = _terms(query)
    if not terms:
        return {"results": []}
    hits = _search_recipes(terms) + _search_ingredients(terms)
    hits.sort(key=lambda pair: pair[0])
    return {"results": [result for _, result in hits[:_MAX_RESULTS]]}


def _lines_for_ingredients(items: list[dict]) -> list[str]:
    """One "- amount unit item" line per ingredient, under a "Group:" heading
    whenever the group changes — including back to none, so an ungrouped
    ingredient after a grouped block is never listed under that group."""
    lines = []
    group = None
    for i, ing in enumerate(items):
        this_group = ing.get("group") or None
        if this_group != group:
            group = this_group
            if group:
                lines.append(f"\n{group}:")
            elif i:
                lines.append("\nOther:")
        parts = [p for p in (ing.get("amount", ""), ing.get("unit", ""), ing.get("item", "")) if p]
        lines.append("- " + " ".join(parts))
    return lines


def _lines_for_steps(steps: list[dict]) -> list[str]:
    lines = []
    for step in steps:
        lines.append(f"{step.get('step')}. {step.get('text', '')}")
        if step.get("tip"):
            lines.append(f"   Tip: {step['tip']}")
    return lines


def _recipe_text(recipe: dict) -> str:
    """The recipe as plain, readable text — what ChatGPT quotes and cites."""
    out = [f"# {recipe['title']}", ""]
    if recipe.get("description"):
        out += [recipe["description"], ""]
    if recipe.get("about"):
        out += [recipe["about"], ""]
    meta = [
        f"Serves {recipe.get('servings')}",
        f"Prep {recipe.get('prep_time_minutes')} min",
        f"Cook {recipe.get('cook_time_minutes')} min",
        f"Difficulty: {recipe.get('difficulty')}",
    ]
    if recipe.get("categories"):
        meta.append("Categories: " + ", ".join(recipe["categories"]))
    if recipe.get("labels"):
        meta.append("Labels: " + ", ".join(recipe["labels"]))
    out += [" · ".join(meta), ""]

    if recipe.get("ingredients"):
        out += ["## Ingredients", *_lines_for_ingredients(recipe["ingredients"]), ""]
    if recipe.get("prep_steps"):
        out += ["## Prep", *_lines_for_steps(recipe["prep_steps"]), ""]
    if recipe.get("instructions"):
        out += ["## Instructions", *_lines_for_steps(recipe["instructions"]), ""]

    for component in recipe.get("components") or []:
        out.append(f"## {component.get('title', '')}")
        if component.get("description"):
            out.append(component["description"])
        if component.get("yield_description"):
            out.append(f"Yield: {component['yield_description']}")
        if component.get("ingredients"):
            out += ["Ingredients:", *_lines_for_ingredients(component["ingredients"])]
        if component.get("prep_steps"):
            out += ["Prep:", *_lines_for_steps(component["prep_steps"])]
        if component.get("instructions"):
            out += ["Steps:", *_lines_for_steps(component["instructions"])]
        out.append("")

    if recipe.get("nutrition"):
        out.append("## Nutrition")
        out += [f"- {n.get('label')}: {n.get('value')} {n.get('unit', '')}".rstrip() for n in recipe["nutrition"]]
        out.append("")
    for secret in recipe.get("secrets") or []:
        out += [f"## {secret.get('title', '')}", secret.get("body", ""), ""]
    if recipe.get("sous_chef_notes"):
        out += ["## Sous Chef notes", recipe["sous_chef_notes"], ""]
    return "\n".join(out).rstrip() + "\n"


def _fetch_recipe(slug_or_id: str) -> dict[str, Any]:
    # Slug first (that is what search hands out); a Firestore id second, so
    # an id copied from list_recipes/get_recipe works too.
    try:
        recipe = _lookup_recipe(slug=slug_or_id).model_dump(mode="json")
    except recipe_service.RecipeNotFound:
        recipe = _lookup_recipe(recipe_id=slug_or_id).model_dump(mode="json")
    return {
        "id": f"{RECIPE_PREFIX}{recipe['slug']}",
        "title": recipe["title"],
        "text": _recipe_text(recipe),
        "url": _public_recipe_url(recipe["slug"], recipe["published"]),
        "metadata": {
            "kind": "recipe",
            "recipe_id": recipe["id"],
            "slug": recipe["slug"],
            "published": recipe["published"],
            "categories": recipe.get("categories", []),
            "labels": recipe.get("labels", []),
            "difficulty": recipe.get("difficulty"),
            "servings": recipe.get("servings"),
            "prep_time_minutes": recipe.get("prep_time_minutes"),
            "cook_time_minutes": recipe.get("cook_time_minutes"),
            "image_url": recipe.get("image_url"),
            "updated_at": iso(recipe.get("updated_at")),
        },
    }


_PROFILE_SECTIONS = (
    ("what_it_is", "What it is"),
    ("role", "Role"),
    ("substitutions", "Substitutions"),
    ("buying", "Buying"),
    ("storage", "Storage"),
    ("mistakes", "Common mistakes"),
    ("allergens", "Allergens"),
)


def _fetch_ingredient(slug: str) -> dict[str, Any]:
    profile = ingredient_service.get_profile(get_db(), slug)
    if profile is None:
        raise ingredient_service.IngredientNotFound(slug)
    name = profile.get("name", "") or slug
    out = [f"# {name}", ""]
    if profile.get("aliases"):
        out += ["Also called: " + ", ".join(profile["aliases"]), ""]
    for key, heading in _PROFILE_SECTIONS:
        if profile.get(key):
            out += [f"## {heading}", profile[key], ""]
    return {
        "id": f"{INGREDIENT_PREFIX}{slug}",
        "title": f"{name} (ingredient)",
        "text": "\n".join(out).rstrip() + "\n",
        "url": "",
        "metadata": {
            "kind": "ingredient",
            "slug": slug,
            "aliases": profile.get("aliases", []),
            "updated_at": iso(profile.get("updated_at")),
        },
    }


@mcp_tool(read_only=True, budget="read")
def fetch(id: str) -> dict[str, Any]:
    """Fetch one document found by `search`, as readable text plus metadata.

    `id` is a search result id: `recipe:<slug>` or `ingredient:<slug>`. A
    bare recipe slug or Firestore recipe id also works. Returns {id, title,
    text, url, metadata}; `text` is the whole recipe (ingredients, steps,
    components, notes) or the whole ingredient profile as plain text. An
    unknown id returns {"error": "not_found"}.
    """
    key = id.strip()
    if not key:
        raise ValueError("id is required")
    if key.startswith(INGREDIENT_PREFIX):
        return _fetch_ingredient(key[len(INGREDIENT_PREFIX):])
    if key.startswith(RECIPE_PREFIX):
        key = key[len(RECIPE_PREFIX):]
    return _fetch_recipe(key)


TOOLS = (search, fetch)  # source order


def register(mcp) -> None:
    """Register this module's tools on the server. Explicit, so the tool
    surface is this tuple, nothing else (see tools/recipes.py)."""
    for tool in TOOLS:
        mcp.tool(annotations=getattr(tool, "mcp_annotations", None))(tool)
