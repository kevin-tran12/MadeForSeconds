"""MCP resources: the same data the read tools serve, addressable by URI.

A resource is a *read*. A client fetches one by URI instead of calling a
tool, which is the right shape for "attach this recipe to the conversation"
or "keep the category list handy" — no arguments to get wrong, and a client
can cache and re-read it.

Deliberately thinner than the tools, and it matters:

- **No ``@mcp_tool`` wrapper.** These carry no rate budget, no audit row and
  no idempotency key, because none of them writes anything. Every mutating
  path is still a tool, so the audit trail (S13) stays complete.
- **Exceptions propagate.** The tools return ``{"error": ...}`` dicts because
  a model calling a tool benefits from structured, in-band failure it can
  reason about. A resource read has no such convention: a missing URI should
  fail as a read, so ``RecipeNotFound`` and friends are left to raise and the
  SDK reports the failure.

Registered explicitly from ``server.py`` via ``register(mcp)``, the same
pattern the tool modules use, so the resource surface is exactly what
``RESOURCES`` and ``RESOURCE_TEMPLATES`` list. This module must not import
the ``mcp`` SDK — ``server.py`` and ``wrapper.py`` are the only two allowed
to (see ``test_mcp_transport.py``'s AST check); it reaches the SDK only
through the ``mcp`` object ``register`` receives.
"""

from ..firestore import get_db
from ..services import ingredients as ingredient_service
from ..services import recipes as recipe_service
from ..services import social as social_service
from .tools.recipes import _lookup_recipe
from .tools.social import build_social_kit

JSON = "application/json"


def recipe_resource(slug: str) -> dict:
    """The full recipe behind a slug, drafts included — the same owner's view
    ``get_recipe`` returns (``AdminRecipe``, so ``sous_chef_notes`` is in it)."""
    return _lookup_recipe(slug=slug).model_dump(mode="json")


def ingredient_resource(slug: str) -> dict:
    """One owner-authored ingredient profile.

    Raises IngredientNotFound rather than returning None, so an unknown slug
    is a failed read instead of a successful null the client has to check.
    """
    profile = ingredient_service.get_profile(get_db(), slug)
    if profile is None:
        raise ingredient_service.IngredientNotFound(slug)
    return profile


def categories_resource() -> dict:
    """The admin-configured category allowlist for create_recipe/update_recipe.

    An empty list is a real, supported state: it means no allowlist is
    configured and every category validates (see app/validation.py).
    """
    return {"categories": recipe_service.get_categories(get_db())}


def social_kit_resource(slug: str) -> dict:
    """Everything needed to draft social posts for one recipe — the same
    payload as the ``get_social_kit`` tool, minus the tool's rate budget."""
    return build_social_kit(slug=slug)


def social_status_resource() -> dict:
    """Per-platform publishing health, as the token-refresh job recorded it."""
    return social_service.status(get_db())


# (uri, fn, name, description). A URI with a {param} registers as a template;
# a plain one as a static resource. Static URIs must take no parameters — the
# SDK raises if they do.
RESOURCE_TEMPLATES = (
    ("recipe://{slug}", recipe_resource, "Recipe", "A full recipe by slug, drafts included."),
    (
        "ingredient://{slug}",
        ingredient_resource,
        "Ingredient profile",
        "An owner-authored ingredient profile by slug.",
    ),
    (
        "social-kit://{slug}",
        social_kit_resource,
        "Social kit",
        "Brand voice, hashtag tiers, platform limits and workflow for drafting a recipe's posts.",
    ),
)

RESOURCES = (
    (
        "categories://list",
        categories_resource,
        "Categories",
        "The admin-configured categories valid for create_recipe/update_recipe.",
    ),
    (
        "social://status",
        social_status_resource,
        "Social status",
        "Per-platform social publishing health: configured, last refresh, expiry, last error.",
    ),
)


def register(mcp) -> None:
    """Register this module's resources. Explicit, so the resource surface is
    exactly RESOURCES + RESOURCE_TEMPLATES and nothing registers by import."""
    for uri, fn, name, description in RESOURCES + RESOURCE_TEMPLATES:
        mcp.resource(uri, name=name, description=description, mime_type=JSON)(fn)
