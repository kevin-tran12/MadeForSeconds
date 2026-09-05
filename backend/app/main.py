import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import logging as cloud_logging

from .config import settings, validate_production_settings
from .log_redaction import RedactionFilter

validate_production_settings(settings)

# Logging must be configured BEFORE the route/MCP imports below. Those pull in
# app.cache, which decides Redis-vs-memory at import time and logs the outcome.
# Configure it afterwards and that record is emitted with no handler attached
# and silently dropped — which is how a dead Redis went unnoticed for weeks.
if not settings.is_dev:
    client = cloud_logging.Client()
    client.setup_logging()
else:
    logging.basicConfig(level=logging.INFO)

# On the root logger's HANDLERS, not the root Logger itself — a record from
# any of this app's named loggers (logging.getLogger(__name__) in every
# module) propagates straight to these handlers without passing through the
# root Logger's own .filter(), so a filter attached there would silently
# never run. See RedactionFilter's own docstring.
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RedactionFilter())

logger = logging.getLogger(__name__)

# Cloud Trace export for the MCP server's built-in OpenTelemetry spans (see
# app/tracing.py). Placed before the MCP import below on the same principle
# as the logging setup above it: get everything observability-related
# configured before importing the modules it will observe. Not strictly
# required for correctness — the mcp SDK's module-level get_tracer() call
# returns an OpenTelemetry ProxyTracer, which defers to whichever
# TracerProvider set_tracer_provider() installs, even one installed later
# (verified empirically, not assumed) — but there's no reason to depend on
# that rather than just doing it in the obvious order.
from .tracing import configure_tracing  # noqa: E402

if configure_tracing():
    logger.info("Cloud Trace export configured")

# ruff: noqa: E402 — deliberately after logging setup, see above.
from .mcp_server import create_mcp_app, mcp as mcp_server  # noqa: E402
from .routes import (  # noqa: E402
    admin,
    assistant,
    expenses,
    internal,
    me,
    public,
    reports,
    subscriptions,
    totp,
)

mcp_app = create_mcp_app()


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
    from .services.recipes import doc_to_recipe

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
            recipe = doc_to_recipe(doc)
            recipes.append(recipe)
            all_cats.update(recipe.categories)

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
    # mcp 2.x: the streamable-HTTP session manager owns a task group that must
    # be running for any /mcp request; it exists only after create_mcp_app().
    async with mcp_server.session_manager.run():
        _warm_cache()
        yield


app = FastAPI(title="MadeForSeconds API", redirect_slashes=False, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Allow all Cloudflare Pages preview deployments automatically
    allow_origin_regex=r"https://.*\.madeforseconds\.pages\.dev",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Dev-Admin", "X-TOTP-Session"],
)

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(subscriptions.router)
app.include_router(expenses.router)
app.include_router(reports.router)
app.include_router(totp.router)
app.include_router(internal.router)
app.include_router(me.router)
app.include_router(assistant.router)



@app.get("/api/health")
async def health():
    logger.info("Health check endpoint called")
    return {"status": "ok"}


# Mount MCP server last — mounts at "/" so its internal /mcp route is reachable at /mcp
# Must come after all other routes since Mount("/") acts as a catch-all
app.mount("/", mcp_app)
