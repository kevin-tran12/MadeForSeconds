import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import logging as cloud_logging

from .config import settings
from .mcp_server import create_mcp_app
from .routes import admin, parse, public

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

# Mount MCP server for Claude Projects integration
app.mount("/mcp", mcp_app)


@app.get("/api/health")
async def health():
    logger.info("Health check endpoint called")
    return {"status": "ok"}
