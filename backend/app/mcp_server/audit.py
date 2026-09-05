"""Audit trail for mutating MCP tools (S13 of the MCP hardening epic).

record() is called from wrapper.py's mcp_tool() decorator for every
read_only=False tool call — success, a translated domain error, or a
rate-limit rejection alike — never for a read-only tool. Best-effort: an
audit write failure must never turn a successful mutation into a failed one
for the caller (pattern: services/social.py's own `_record`, which the
docstring there names for exactly this reason).

Each doc in the `mcp_audit` collection: {tool, at, ok, error, client_id,
subject, target, arg_keys}. `arg_keys` is the sorted list of argument
NAMES the call was made with, never values — this is a record of what was
attempted, not a second copy of the mutation's payload sitting in a second
collection with a different access-control story than the one it belongs
in. `target` is the handful of identifiers (recipe_id, slug, expense_id,
media_id, ingredient_slug) that say WHAT the call touched, extracted below
per tool since each domain names its own identifiers differently.

No Terraform, no TTL: a personal site's mutation volume through this
surface keeps `mcp_audit` writes trivially inside Firestore's free tier
indefinitely — see docs/DEPLOYMENT.md's "Audit trail" paragraph.
"""

import logging
from datetime import datetime, timezone

from ..firestore import get_db

logger = logging.getLogger(__name__)

COLLECTION = "mcp_audit"

_RECIPE_TOOLS = frozenset({"create_recipe", "update_recipe", "publish_recipe", "unpublish_recipe", "delete_recipe"})
_SOCIAL_TOOLS = frozenset({"publish_instagram_post", "publish_recipe_to_instagram"})
_INGREDIENT_TOOLS = frozenset({"upsert_ingredient", "delete_ingredient"})


def _build_target(tool_name: str, kwargs: dict, result) -> dict:
    """Best-effort identifiers for what a mutation touched.

    Checked first from the caller-supplied kwargs (known even when the call
    ultimately failed — e.g. update_recipe(recipe_id="ghost", ...) failing
    with not_found should still record which recipe_id was attempted), then
    from the tool's own result (the only place an id is available for a
    tool that creates something new, e.g. create_recipe/create_expense —
    there is no id to pass in until the write has already happened).
    """
    result = result if isinstance(result, dict) else {}
    target: dict = {}

    if tool_name in _RECIPE_TOOLS:
        recipe_id = kwargs.get("recipe_id") or result.get("id")
        slug = result.get("slug")  # no recipe tool takes slug as an argument
        if recipe_id:
            target["recipe_id"] = recipe_id
        if slug:
            target["slug"] = slug
    elif tool_name == "create_expense":
        expense_id = result.get("id")
        if expense_id:
            target["expense_id"] = expense_id
    elif tool_name in _SOCIAL_TOOLS:
        media_id = result.get("id")  # instagram.publish_image's media id
        if media_id:
            target["media_id"] = media_id
        recipe_id = kwargs.get("recipe_id")
        slug = kwargs.get("slug")
        if recipe_id:
            target["recipe_id"] = recipe_id
        if slug:
            target["slug"] = slug
    elif tool_name in _INGREDIENT_TOOLS:
        ingredient_slug = kwargs.get("slug") or result.get("slug")
        if ingredient_slug:
            target["ingredient_slug"] = ingredient_slug
    # request_image_upload / upload_image_from_url: no identifier in this
    # schema names an upload — they produce URLs, not an entity with an id.

    return target


def record(tool_name: str, kwargs: dict, result, client_id: str | None, subject: str | None) -> None:
    """Write one audit doc for a mutating MCP tool call. Never raises."""
    error_kind = result.get("error") if isinstance(result, dict) else None
    doc = {
        "tool": tool_name,
        "at": datetime.now(timezone.utc),
        "ok": error_kind is None,
        "error": error_kind,
        "client_id": client_id,
        # WorkOSTokenVerifier does not populate AccessToken.subject today
        # (see mcp_auth.py) — always None until that lands, kept here so
        # the schema does not need to change when it does.
        "subject": subject,
        "target": _build_target(tool_name, kwargs, result),
        "arg_keys": sorted(kwargs.keys()),
    }
    try:
        get_db().collection(COLLECTION).document().set(doc)
    except Exception:
        logger.warning("mcp audit write failed for tool=%s", tool_name, exc_info=True)
