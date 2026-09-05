"""Remote MCP server for managing recipes and expenses from Claude conversations.

Claude clients (Claude Code, claude.ai Projects) connect via Streamable HTTP.
The full workflow happens without the admin web UI:

1. ``list_categories`` / ``list_recipes`` to discover existing content
2. ``create_recipe`` to save a draft (slug conflicts return a pointer to the
   existing recipe instead of writing a duplicate)
3. ``update_recipe`` to iterate on the draft
4. ``request_image_upload`` for a signed PUT URL (curl the file to GCS), or
   ``upload_image_from_url`` when the photo is already hosted somewhere —
   then attach via ``update_recipe(image_url=...)``
5. ``publish_recipe`` once complete

Expenses: upload the receipt with ``request_image_upload(kind="receipt")``,
PUT the file, then pass the returned ``final_url`` to ``create_expense``.

This is the only module in the package that imports the ``mcp`` SDK — every
tool lives in its own module under ``tools/`` (one per domain: recipes,
images, social, expenses), each exposing a ``TOOLS`` tuple and a
``register(mcp)`` function. ``TOOL_MODULES`` below lists them in the order
their workflow paragraph appears above.
"""

import logging
from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ..config import settings
from ..mcp_auth import WorkOSTokenVerifier
from .tools import expenses, images, recipes, social

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Manage MadeForSeconds recipes and expenses.

Recipe workflow: list_categories → create_recipe (saved as draft) →
update_recipe to iterate → request_image_upload + update_recipe(image_url=...)
to attach a photo → publish_recipe. Use list_recipes/get_recipe to inspect
existing content before creating — duplicate titles are rejected with a
pointer to the existing recipe.

Social workflow (after publish_recipe): call get_social_kit(slug=...) for the
recipe summary, brand voice, hashtag tiers, and per-platform limits. Draft an
Instagram caption and a TikTok caption + 15-second shot list, show both to the
operator, and only after explicit approval call
publish_recipe_to_instagram(slug, caption=...). TikTok is draft-only — hand
the draft over for manual posting. If a post fails with an auth error, call
social_status() and report when the token expires or last failed.

Note: the backend scales to zero; the first call after idle may take ~10s.
If a call times out, retry reads only. For a timed-out write (create_recipe,
create_expense, the Instagram publishers), first call list_recipes or
social_status to see whether it landed — a blind retry duplicates it."""

# One tools/*.py module per domain, in the order its workflow paragraph
# appears in INSTRUCTIONS above. Each exposes TOOLS (a tuple, source order)
# and register(mcp) — the tool surface is exactly the union of those tuples,
# nothing registers by side effect.
TOOL_MODULES = (recipes, images, social, expenses)


def _auth_for(settings) -> tuple[AuthSettings | None, WorkOSTokenVerifier | None, TransportSecuritySettings]:
    """(auth, token_verifier, transport_security) for the given settings.

    A function rather than module-level state so a prod-config test can build
    a server against a fake settings object without patching module globals.
    WorkOSTokenVerifier() reads the real app settings internally regardless
    of what is passed here — fine, since such a test never verifies a token.

    OAuth: WorkOS AuthKit is the authorization server; this MCP server is the
    resource server. When auth is configured the SDK serves
    /.well-known/oauth-protected-resource, enforces tokens on /mcp, and emits
    a compliant WWW-Authenticate challenge on 401. Dev runs unauthenticated
    (no WorkOS dependency), matching the require_admin dev bypass.
    """
    if settings.is_dev:
        # No DNS-rebinding host restriction locally — requests arrive as localhost:8000.
        return None, None, TransportSecuritySettings(enable_dns_rebinding_protection=False)

    auth = AuthSettings(
        issuer_url=settings.workos_issuer_url,
        resource_server_url=settings.mcp_resource_url,
        # Blank (the default) keeps prior behaviour — no scope beyond a
        # valid, owned token (see mcp_auth.WorkOSTokenVerifier) is required.
        required_scopes=settings.mcp_required_scopes_list or None,
    )
    token_verifier = WorkOSTokenVerifier()
    resource_host = urlparse(settings.mcp_resource_url).netloc
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[resource_host, f"{resource_host}:*", "localhost", "localhost:*"],
    )
    return auth, token_verifier, transport_security


def build_server(settings) -> MCPServer:
    """Construct the MCPServer and register every tool module's tools on it."""
    auth, token_verifier, _ = _auth_for(settings)
    server = MCPServer(
        "MadeForSeconds Recipe Creator",
        instructions=INSTRUCTIONS,
        auth=auth,
        token_verifier=token_verifier,
    )
    for module in TOOL_MODULES:
        module.register(server)
    return server


def build_app(settings, server: MCPServer):
    """ASGI app for mounting on FastAPI. Auth is enforced by the SDK when configured.

    transport_security MUST be passed here: in mcp 2.x streamable_http_app()
    defaults to localhost-only DNS-rebinding protection when it is omitted,
    which returns 421 for every request behind Cloud Run.
    """
    _, _, transport_security = _auth_for(settings)
    return server.streamable_http_app(stateless_http=True, transport_security=transport_security)


mcp = build_server(settings)


def create_mcp_app():
    return build_app(settings, mcp)
