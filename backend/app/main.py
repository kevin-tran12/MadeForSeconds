import logging
import os

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
app = FastAPI(title="MadeForSeconds API", redirect_slashes=False, lifespan=mcp_inner.router.lifespan_context)

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
