import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import logging as cloud_logging

from .config import settings
from .mcp_server import create_mcp_app
from .routes import admin, expenses, parse, public, reports, subscriptions, totp

# Fail fast in production if the JWT secret is the known-weak placeholder or too short
if not settings.is_dev:
    _secret = settings.subscriber_jwt_secret
    if _secret == "dev-subscriber-secret-change-in-prod":
        raise RuntimeError(
            "SUBSCRIBER_JWT_SECRET must be set to a cryptographically random value in production. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if len(_secret) < 32:
        raise RuntimeError("SUBSCRIBER_JWT_SECRET must be at least 32 characters in production")

# Setup Cloud Logging
if not settings.is_dev:
    client = cloud_logging.Client()
    client.setup_logging()
else:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

mcp_inner, mcp_app = create_mcp_app()


def _warm_cache() -> None:
    """Eagerly initialise the Firestore client and pre-populate the Redis cache
    with the main recipe list and categories so the first real request is fast,
    even after a Cloud Run cold start."""
    from collections import defaultdict

    from google.cloud.firestore_v1.base_query import FieldFilter

    from .cache import cache
    from .firestore import get_db
    from .models import (
        CategoryGroup,
        GroupedRecipes,
        PaginatedRecipes,
        Recipe,
    )

    try:
        db = get_db()
        docs = list(
            db.collection("recipes")
            .where(filter=FieldFilter("published", "==", True))
            .order_by("created_at", direction="DESCENDING")
            .limit(50)
            .stream()
        )
        recipes = []
        all_cats: set[str] = set()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            if isinstance(data.get("nutrition"), dict):
                data["nutrition"] = [
                    {"label": k, "value": v, "unit": ""} for k, v in data["nutrition"].items()
                ]
            data.pop("premium_content", None)
            data.pop("has_premium_content", None)
            recipes.append(Recipe(**data))
            all_cats.update(data.get("categories", []))

        if recipes:
            # Warm the default /api/recipes response (no filters, limit=12)
            page = recipes[:12]
            next_cursor = page[-1].created_at.isoformat() if len(recipes) > 12 else None
            cache.set(
                "recipes::::all:12:",
                PaginatedRecipes(recipes=page, next_cursor=next_cursor),
            )

            # Warm the /api/recipes/grouped response (homepage)
            recent = recipes[:6]
            by_category: dict[str, list[Recipe]] = defaultdict(list)
            for recipe in recipes:
                for cat in recipe.categories:
                    if len(by_category[cat]) < 8:
                        by_category[cat].append(recipe)
            groups = [
                CategoryGroup(category=cat, recipes=recs)
                for cat, recs in sorted(by_category.items())
            ]
            cache.set("recipes:grouped", GroupedRecipes(recent=recent, groups=groups))

            cache.set("categories", sorted(all_cats))
            logger.info("Cache warmed: %d recipes, %d categories", len(recipes), len(all_cats))
        else:
            logger.warning("Cache warm skipped: no published recipes found")
    except Exception as exc:
        logger.warning("Cache warm failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app):
    async with mcp_inner.router.lifespan_context(app):
        _warm_cache()
        yield


app = FastAPI(title="MadeForSeconds API", redirect_slashes=False, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Allow all Cloudflare Pages preview deployments automatically
    allow_origin_regex=r"https://.*\.madeforseconds\.pages\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(parse.router)
app.include_router(subscriptions.router)
app.include_router(expenses.router)
app.include_router(reports.router)
app.include_router(totp.router)



@app.get("/api/health")
async def health():
    logger.info("Health check endpoint called")
    return {"status": "ok"}


# Mount MCP server last — mounts at "/" so its internal /mcp route is reachable at /mcp
# Must come after all other routes since Mount("/") acts as a catch-all
app.mount("/", mcp_app)
