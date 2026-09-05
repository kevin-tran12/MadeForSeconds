"""MCP server package: the remote Model Context Protocol server that lets
Claude author, publish, and (for expenses) log records on MadeForSeconds.

Layout:

- ``server.py`` — the only module in this package that imports the ``mcp``
  SDK. Builds ``AuthSettings``/``TokenVerifier``/``TransportSecuritySettings``
  from app settings, holds the tool-workflow instructions the model reads,
  and constructs the ``MCPServer``.
- ``errors.py`` — ``tool_errors``, the decorator every tool wears that turns
  a domain exception into a structured dict instead of a raw traceback.
- ``tools/<domain>.py`` — one module per kind of tool (recipes, images,
  social, expenses). Each defines its tool functions as plain, undecorated-
  by-the-SDK callables (only ``@tool_errors`` applied directly), a ``TOOLS``
  tuple listing them in source order, and a ``register(mcp)`` function that
  calls ``mcp.tool()`` on each — so the tool surface is exactly the union of
  those tuples, never an accident of import order.

Everything below re-exports the flat surface the rest of the app, the test
suite, and ``scripts/smoke_test_receipt_role.py`` import as
``app.mcp_server.<name>`` — the package's import path is unchanged from the
single-module version this replaced.
"""

from .server import INSTRUCTIONS, TOOL_MODULES, build_app, build_server, create_mcp_app, mcp
from .tools.expenses import create_expense
from .tools.images import request_image_upload, upload_image_from_url
from .tools.recipes import (
    create_recipe,
    delete_recipe,
    get_recipe,
    list_categories,
    list_recipes,
    publish_recipe,
    unpublish_recipe,
    update_recipe,
)
from .tools.social import get_social_kit, publish_instagram_post, publish_recipe_to_instagram, social_status

__all__ = [
    "INSTRUCTIONS",
    "TOOL_MODULES",
    "build_app",
    "build_server",
    "create_expense",
    "create_mcp_app",
    "create_recipe",
    "delete_recipe",
    "get_recipe",
    "get_social_kit",
    "list_categories",
    "list_recipes",
    "mcp",
    "publish_instagram_post",
    "publish_recipe",
    "publish_recipe_to_instagram",
    "request_image_upload",
    "social_status",
    "unpublish_recipe",
    "update_recipe",
    "upload_image_from_url",
]
