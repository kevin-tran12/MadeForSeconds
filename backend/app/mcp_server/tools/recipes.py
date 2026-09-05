"""Recipe tools: list, fetch, create, update, publish, delete."""

import logging
from datetime import datetime

from google.cloud.firestore_v1.base_query import FieldFilter

from ...config import settings
from ...firestore import get_db
from ...models import RecipeCreate, RecipeUpdate
from ...services import recipes as recipe_service
from ..wrapper import iso, mcp_tool

logger = logging.getLogger(__name__)

# S7: search mode scans forward in bounded pages instead of the whole
# catalogue in one call — this caps how much of it any single call touches.
_MAX_SEARCH_PAGES = 3


def _recipe_item(doc, data: dict) -> dict:
    return {
        "id": doc.id,
        "slug": data.get("slug", ""),
        "title": data.get("title", ""),
        "published": data.get("published", False),
        "updated_at": iso(data.get("updated_at")),
        "categories": data.get("categories", []),
        "labels": data.get("labels", []),
        "has_image": bool(data.get("image_url")),
    }


def _recipes_query(published: bool | None):
    # Known limitation, shared with routes/public.py's identical pattern
    # (this deliberately reuses it, per S7's own spec) rather than something
    # new: a `start_after` cursor keyed on `created_at` alone has no
    # tiebreaker, so two recipes sharing the exact same microsecond
    # timestamp would land on the same cursor "position" and one could be
    # silently skipped across a page boundary. Found this for real —
    # seed.py computes one `now` and reuses it for every seeded recipe,
    # which reproduces the tie deterministically — not a hypothetical.
    # Not fixed here: real recipe creation (one MCP/HTTP call at a time)
    # makes an exact microsecond collision astronomically unlikely, and a
    # proper fix (a compound (created_at, doc_id) cursor) is a change to a
    # pattern used in two places, not a one-line addition — worth its own
    # follow-up rather than folding into this story's scope.
    query = get_db().collection("recipes")
    if published is not None:
        query = query.where(filter=FieldFilter("published", "==", published))
    return query.order_by("created_at", direction="DESCENDING").select(
        ["slug", "title", "published", "created_at", "updated_at", "categories", "labels", "image_url"]
    )


@mcp_tool(read_only=True, budget="read")
def list_recipes(
    published: bool | None = None, search: str = "", limit: int = 20, cursor: str | None = None,
) -> dict:
    """List recipes (drafts and published) as lightweight summaries, newest first.

    published: filter by state (True/False), or omit for all.
    search: case-insensitive substring match on the title.
    cursor: pass back the next_cursor from a previous call to continue where
    it left off. An unrecognised cursor returns {"error": "invalid_request"}
    rather than silently starting over from the beginning.

    Without search, this is one Firestore page per call (limit+1 trick to
    detect whether another page exists, same as the public /api/recipes
    route). With search — Firestore has no substring/ILIKE query, so
    matching happens here — it scans up to 3 pages of min(limit*3, 100)
    docs each per call, bounding how much of the catalogue one call
    touches, rather than the whole thing at once. next_cursor continues
    from the last SCANNED doc (not the last matched one), so a follow-up
    call with the same search keeps scanning forward instead of
    re-scanning what this call already looked at; exhausted=true means
    every recipe has now been scanned end to end.

    Returns {recipes, count, next_cursor, exhausted}.
    """
    limit = max(1, min(limit, 100))

    cursor_dt = None
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError:
            return {"error": "invalid_request", "message": f"invalid cursor: {cursor!r}"}

    needle = search.lower()

    if not needle:
        query = _recipes_query(published)
        if cursor_dt is not None:
            query = query.start_after({"created_at": cursor_dt})
        fetch_limit = limit + 1  # +1 to detect whether another page exists
        docs = list(query.limit(fetch_limit).stream())
        has_more = len(docs) > limit
        docs = docs[:limit]

        items = []
        last_created_at = None
        for doc in docs:
            data = doc.to_dict() or {}
            last_created_at = data.get("created_at")
            items.append(_recipe_item(doc, data))

        return {
            "recipes": items,
            "count": len(items),
            "next_cursor": iso(last_created_at) if has_more else None,
            "exhausted": not has_more,
        }

    # search mode: scan forward in bounded pages rather than the whole
    # catalogue at once.
    page_fetch_limit = min(limit * 3, 100)
    page_cursor_dt = cursor_dt
    last_scanned_at = None
    exhausted = False
    items = []

    for _ in range(_MAX_SEARCH_PAGES):
        query = _recipes_query(published)
        if page_cursor_dt is not None:
            query = query.start_after({"created_at": page_cursor_dt})
        page_docs = list(query.limit(page_fetch_limit).stream())
        if not page_docs:
            exhausted = True
            break

        for doc in page_docs:
            data = doc.to_dict() or {}
            last_scanned_at = data.get("created_at")
            if needle in data.get("title", "").lower():
                items.append(_recipe_item(doc, data))
                if len(items) >= limit:
                    break

        if len(page_docs) < page_fetch_limit:
            exhausted = True
        page_cursor_dt = last_scanned_at

        if len(items) >= limit or exhausted:
            break

    return {
        "recipes": items[:limit],
        "count": len(items[:limit]),
        "next_cursor": None if exhausted else iso(last_scanned_at),
        "exhausted": exhausted,
    }


def _lookup_recipe(recipe_id: str = "", slug: str = ""):
    """Fetch a recipe document by id or slug (drafts included).

    Returns the owner's AdminRecipe view (includes sous_chef_notes).
    Raises RecipeNotFound / ValueError.
    """
    db = get_db()
    if recipe_id:
        doc = db.collection("recipes").document(recipe_id).get()
        if not doc.exists:
            raise recipe_service.RecipeNotFound(recipe_id)
    elif slug:
        docs = (
            db.collection("recipes")
            .where(filter=FieldFilter("slug", "==", slug))
            .limit(1)
            .stream()
        )
        doc = next(iter(docs), None)
        if doc is None:
            raise recipe_service.RecipeNotFound(slug)
    else:
        raise ValueError("Provide recipe_id or slug")
    return recipe_service.doc_to_admin_recipe(doc)


@mcp_tool(read_only=True, budget="read")
def get_recipe(recipe_id: str = "", slug: str = "") -> dict:
    """Fetch a full recipe by id or slug (drafts included)."""
    return _lookup_recipe(recipe_id, slug).model_dump(mode="json")


@mcp_tool(read_only=True, budget="read")
def list_categories() -> dict:
    """List the admin-configured categories valid for create_recipe/update_recipe."""
    return {"categories": recipe_service.get_categories(get_db())}


@mcp_tool(read_only=False, budget="write")
def create_recipe(
    title: str,
    description: str = "",
    about: str | None = None,
    ingredients: list[dict] = [],
    prep_steps: list[dict] = [],
    instructions: list[dict] = [],
    prep_time_minutes: int = 0,
    cook_time_minutes: int = 0,
    servings: int = 1,
    difficulty: str = "easy",
    categories: list[str] = [],
    labels: list[str] = [],
    nutrition: list[dict] = [],
    image_url: str | None = None,
    components: list[dict] | None = None,
    secrets: list[dict] = [],
    sous_chef_notes: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create a new recipe draft on MadeForSeconds.

    idempotency_key (optional, <=128 chars): pass the same value on a retry
    after a timeout to get back the original call's result instead of
    creating a second recipe (see server.py's INSTRUCTIONS retry note).

    The recipe is saved unpublished — finish it with update_recipe, attach a
    photo (request_image_upload), then publish_recipe.

    Each ingredient dict: item (str), amount (str), unit (str), optional group (str).
    Each instruction/prep_step dict: step (int), text (str), optional tip (str).
    Each nutrition dict: label (str), value (float), unit (str).
    Each secret dict: title (str), body (str).
    difficulty: easy | medium | hard.
    categories: must come from list_categories. labels are free-form tags.
    about is optional cultural/historical context, richer than description.
    image_url is optional — a publicly accessible URL to the recipe photo.
    sous_chef_notes is optional private guidance for the site's Sous Chef
    assistant (substitutions that work, ones that don't, known pitfalls) —
    it is never shown to readers.

    For multi-component dishes (e.g. Hainanese Chicken Rice with separate rice,
    sauces): pass components as up to 5 dicts, each with title (str), optional
    description, ingredients, optional prep_steps, instructions, optional
    prep/cook_time_minutes, optional yield_description. With components, leave
    top-level ingredients/instructions empty.

    On slug conflict (usually a retry) this returns a pointer to the existing
    recipe instead of creating a duplicate.
    """
    body = RecipeCreate.model_validate({
        "title": title,
        "description": description,
        "about": about,
        "ingredients": ingredients,
        "prep_steps": prep_steps,
        "instructions": instructions,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "servings": servings,
        "difficulty": difficulty,
        "categories": categories,
        "labels": labels,
        "nutrition": nutrition,
        "image_url": image_url,
        "published": False,
        "components": components[:5] if components else None,
        "secrets": secrets,
        "sous_chef_notes": sous_chef_notes,
    })

    recipe = recipe_service.create_recipe(get_db(), body, source="mcp")
    logger.info("MCP create_recipe: %s (%s)", recipe.title, recipe.id)
    return {
        "id": recipe.id,
        "slug": recipe.slug,
        "title": recipe.title,
        "message": (
            "Recipe created as draft. Iterate with update_recipe, attach an image "
            "via request_image_upload, then publish_recipe."
        ),
    }


_CLEARABLE_FIELDS = {"about", "image_url", "components", "sous_chef_notes"}


@mcp_tool(read_only=False, idempotent=True, budget="write")
def update_recipe(
    recipe_id: str,
    title: str | None = None,
    description: str | None = None,
    about: str | None = None,
    ingredients: list[dict] | None = None,
    prep_steps: list[dict] | None = None,
    instructions: list[dict] | None = None,
    prep_time_minutes: int | None = None,
    cook_time_minutes: int | None = None,
    servings: int | None = None,
    difficulty: str | None = None,
    categories: list[str] | None = None,
    labels: list[str] | None = None,
    nutrition: list[dict] | None = None,
    image_url: str | None = None,
    components: list[dict] | None = None,
    secrets: list[dict] | None = None,
    sous_chef_notes: str | None = None,
    clear_fields: list[str] = [],
) -> dict:
    """Update fields of an existing recipe (draft or published).

    Only the fields you pass are changed. List fields (ingredients,
    instructions, labels, ...) are replaced WHOLE — call get_recipe first and
    send back the complete modified list. The slug never changes, even when
    the title does. Published state cannot be set here — use
    publish_recipe/unpublish_recipe.

    To null an optional field (about, image_url, components, sous_chef_notes),
    name it in clear_fields instead of passing null.
    """
    provided = {
        "title": title,
        "description": description,
        "about": about,
        "ingredients": ingredients,
        "prep_steps": prep_steps,
        "instructions": instructions,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "servings": servings,
        "difficulty": difficulty,
        "categories": categories,
        "labels": labels,
        "nutrition": nutrition,
        "image_url": image_url,
        "components": components,
        "secrets": secrets,
        "sous_chef_notes": sous_chef_notes,
    }
    updates = {k: v for k, v in provided.items() if v is not None}
    for field in clear_fields:
        if field not in _CLEARABLE_FIELDS:
            raise ValueError(f"clear_fields supports only: {sorted(_CLEARABLE_FIELDS)}")
        updates[field] = None
    if not updates:
        raise ValueError("No fields to update")

    body = RecipeUpdate.model_validate(updates)
    recipe = recipe_service.update_recipe(get_db(), recipe_id, body, source="mcp")
    logger.info("MCP update_recipe: %s (%s) field_count=%d", recipe.title, recipe.id, len(updates))
    return {
        "id": recipe.id,
        "slug": recipe.slug,
        "title": recipe.title,
        "published": recipe.published,
        "updated_fields": sorted(updates),
        "message": "Recipe updated.",
    }


@mcp_tool(read_only=False, idempotent=True, budget="write")
def publish_recipe(recipe_id: str) -> dict:
    """Publish a recipe so it appears on the public site.

    Fails if the recipe has no ingredients+instructions (or components).
    Soft gaps — missing image, description, or categories — are returned
    as warnings, not errors.
    """
    recipe, warnings = recipe_service.set_published(get_db(), recipe_id, True, source="mcp")
    logger.info("MCP publish_recipe: %s (%s)", recipe.title, recipe.id)
    return {
        "id": recipe.id,
        "slug": recipe.slug,
        "published": True,
        "public_url": f"{settings.frontend_url}/recipes/{recipe.slug}/",
        "warnings": warnings,
    }


@mcp_tool(read_only=False, destructive=True, idempotent=True, budget="write")
def unpublish_recipe(recipe_id: str) -> dict:
    """Take a published recipe off the public site (back to draft)."""
    recipe, _ = recipe_service.set_published(get_db(), recipe_id, False, source="mcp")
    logger.info("MCP unpublish_recipe: %s (%s)", recipe.title, recipe.id)
    return {"id": recipe.id, "slug": recipe.slug, "published": False}


@mcp_tool(read_only=False, destructive=True, budget="write")
def delete_recipe(recipe_id: str, confirm_title: str) -> dict:
    """Delete a DRAFT recipe and its stored image.

    Any attached receipts are kept — they are expense records under seven-year
    retention, so deleting the recipe unlinks them rather than destroying them.

    Published recipes must be unpublished first. confirm_title must exactly
    match the recipe's title — fetch it with get_recipe if unsure.
    """
    db = get_db()
    doc = db.collection("recipes").document(recipe_id).get()
    if not doc.exists:
        raise recipe_service.RecipeNotFound(recipe_id)
    actual_title = (doc.to_dict() or {}).get("title", "")
    if confirm_title != actual_title:
        return {
            "error": "confirm_title_mismatch",
            "message": "confirm_title must exactly match the recipe title.",
            "expected_title": actual_title,
        }

    recipe_service.delete_recipe(db, recipe_id, source="mcp", require_draft=True)
    logger.info("MCP delete_recipe: %s (%s)", actual_title, recipe_id)
    return {"deleted": True, "id": recipe_id, "title": actual_title}


TOOLS = (
    list_recipes, get_recipe, list_categories, create_recipe, update_recipe,
    publish_recipe, unpublish_recipe, delete_recipe,
)  # source order


def register(mcp) -> None:
    """Register this module's tools on the server. Explicit, so the tool
    surface is this tuple, nothing else. Each tool's annotations (set by the
    @mcp_tool(...) decorator in wrapper.py) ride along so the server exposes
    them to clients."""
    for tool in TOOLS:
        mcp.tool(annotations=getattr(tool, "mcp_annotations", None))(tool)
