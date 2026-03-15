"""Remote MCP server for creating recipes from Claude Projects.

Claude Projects on claude.ai connect to this via Streamable HTTP.
The user develops a recipe by chatting with Claude, then Claude
calls the create_recipe tool to save it as an unpublished draft.
"""

import re
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from .config import settings
from .firestore import get_db
from .models import Ingredient, Instruction, NutritionEntry, RecipeComponent, RecipeCreate


mcp = FastMCP(
    "MadeForSeconds Recipe Creator",
    stateless_http=True,
)


def _generate_slug(title: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", title.lower()))


@mcp.tool()
def create_recipe(
    title: str,
    description: str = "",
    ingredients: list[dict] = [],
    instructions: list[dict] = [],
    prep_time_minutes: int = 0,
    cook_time_minutes: int = 0,
    servings: int = 1,
    difficulty: str = "easy",
    categories: list[str] = [],
    nutrition: list[dict] = [],
    image_url: str | None = None,
    components: list[dict] | None = None,
) -> dict:
    """Create a new recipe draft on MadeForSeconds.

    The recipe is saved as unpublished. Review and publish it from the admin dashboard.

    Each ingredient dict must have: item (str), amount (str), unit (str), and optionally group (str).
    Each instruction dict must have: step (int), text (str), and optionally tip (str).
    Each nutrition dict must have: label (str), value (float), unit (str).
    Difficulty must be one of: easy, medium, hard.
    image_url is optional — a publicly accessible URL to the recipe photo.

    For multi-component dishes (e.g. Hainanese Chicken Rice with separate rice, sauces):
      Pass components as a list of up to 5 dicts, each with:
        title (str), description (str, optional),
        ingredients (list[dict]), instructions (list[dict]),
        prep_time_minutes (int, optional), cook_time_minutes (int, optional),
        yield_description (str, optional — e.g. "About ½ cup" for sauces).
      When components is provided, top-level ingredients/instructions should be empty.
    """
    # Build components if provided
    parsed_components = None
    if components:
        parsed_components = [
            RecipeComponent(
                title=c["title"],
                description=c.get("description"),
                ingredients=[Ingredient(**ing) for ing in c.get("ingredients", [])],
                instructions=[Instruction(**inst) for inst in c.get("instructions", [])],
                prep_time_minutes=c.get("prep_time_minutes"),
                cook_time_minutes=c.get("cook_time_minutes"),
                yield_description=c.get("yield_description"),
            )
            for c in components[:5]  # cap at 5
        ]

    # Validate through Pydantic models
    recipe = RecipeCreate(
        title=title,
        description=description,
        ingredients=[Ingredient(**ing) for ing in ingredients],
        instructions=[Instruction(**inst) for inst in instructions],
        prep_time_minutes=prep_time_minutes,
        cook_time_minutes=cook_time_minutes,
        servings=servings,
        difficulty=difficulty,
        categories=categories,
        nutrition=[NutritionEntry(**n) for n in nutrition],
        image_url=image_url,
        published=False,
        components=parsed_components,
    )

    now = datetime.now(timezone.utc)
    data = recipe.model_dump()
    data["slug"] = _generate_slug(recipe.title)
    data["created_at"] = now
    data["updated_at"] = now

    db = get_db()
    doc_ref = db.collection("recipes").document()
    doc_ref.set(data)

    return {
        "id": doc_ref.id,
        "slug": data["slug"],
        "title": recipe.title,
        "message": "Recipe created as draft. Review and publish at /admin.",
    }


class _BearerAuthMiddleware:
    """ASGI middleware that validates Authorization: Bearer <token> against MCP_API_KEY."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and settings.mcp_api_key:
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth != f"Bearer {settings.mcp_api_key}":
                response = b'{"error": "Unauthorized"}'
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({"type": "http.response.body", "body": response})
                return
        await self.app(scope, receive, send)


def create_mcp_app():
    """Create the ASGI app for mounting on FastAPI.

    Returns (inner_app, wrapped_app) — inner_app exposes .lifespan for FastAPI,
    wrapped_app adds bearer token auth and is what gets mounted.
    """
    inner = mcp.streamable_http_app()
    return inner, _BearerAuthMiddleware(inner)
