"""Transport-level tests for the mcp SDK 2.x migration (app/mcp_server/).

test_mcp_tools.py calls tools as plain functions and never touches the SDK's
own surface — tools/list, schemas, the /mcp mount, or the auth challenge. This
file is the first real coverage of the MCP server as a client sees it: the
in-memory Client (1.6a), worker-thread concurrency (1.6c), the request-body
limit (1.6d), and the HTTP mount (1.6b).
"""

import json
import time
from itertools import count

import anyio
import pytest
from mcp.client import Client

from app import mcp_server

DOCUMENTED_TOOLS = {
    "list_recipes", "get_recipe", "list_categories", "create_recipe",
    "update_recipe", "publish_recipe", "unpublish_recipe", "delete_recipe",
    "request_image_upload", "upload_image_from_url", "create_expense",
    "publish_instagram_post", "publish_recipe_to_instagram", "get_social_kit",
    "social_status",
    "list_ingredients", "get_ingredient", "upsert_ingredient", "delete_ingredient",
}

INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def db(mcp_db):
    """Alias for conftest.py's mcp_db, kept so every test below reads
    unchanged — see that fixture for what it patches."""
    return mcp_db


# ── 1.6a In-memory client ───────────────────────────────────────────────────


class TestInMemoryClient:
    @pytest.mark.asyncio
    async def test_tools_list_matches_documented_surface(self):
        async with Client(mcp_server.mcp) as c:
            result = await c.list_tools()
        names = {t.name for t in result.tools}
        assert names == DOCUMENTED_TOOLS
        for tool in result.tools:
            assert tool.description, f"{tool.name} has no description"
            assert tool.input_schema, f"{tool.name} has no input schema"

    @pytest.mark.asyncio
    async def test_snapshot_create_recipe_schema(self):
        """Ground truth for later stories (typed inputs, outputSchema): today
        `ingredients` is an untyped array of open objects
        ({"type": "object", "additionalProperties": True}) — S10 replaces this
        with list[Ingredient] — no tool has an output schema, and no tool
        carries annotations (both added later, S11/S4)."""
        async with Client(mcp_server.mcp) as c:
            result = await c.list_tools()
        by_name = {t.name: t for t in result.tools}
        create_recipe = by_name["create_recipe"]
        ingredients_schema = create_recipe.input_schema["properties"]["ingredients"]
        assert ingredients_schema["type"] == "array"
        assert ingredients_schema["items"] == {"type": "object", "additionalProperties": True}
        assert all(t.output_schema is None for t in result.tools)
        assert all(t.annotations is None for t in result.tools)

    @pytest.mark.asyncio
    async def test_call_list_categories(self, db):
        db.stream.side_effect = lambda *a, **k: iter([])
        async with Client(mcp_server.mcp) as c:
            result = await c.call_tool("list_categories", {})
        assert result.is_error is False
        assert json.loads(result.content[0].text) == {"categories": []}

    @pytest.mark.asyncio
    async def test_call_get_recipe_not_found_is_structured(self, db):
        """Today's contract: a domain "not found" is structured content, not an
        error result. S11 changes this to isError=true."""
        db.get.return_value.exists = False
        db.stream.side_effect = lambda *a, **k: iter([])
        async with Client(mcp_server.mcp) as c:
            result = await c.call_tool("get_recipe", {"recipe_id": "ghost"})
        assert result.is_error is False
        assert json.loads(result.content[0].text)["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_call_create_recipe_validation_error(self, db):
        async with Client(mcp_server.mcp) as c:
            result = await c.call_tool("create_recipe", {
                "title": "T", "description": "D", "ingredients": [], "instructions": [],
                "prep_time_minutes": 1, "cook_time_minutes": 1, "servings": -1,
                "difficulty": "easy", "categories": [],
            })
        body = json.loads(result.content[0].text)
        assert body["error"] == "validation_error"
        assert body["field_errors"]

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        """Recorded behaviour: an unrouted tool name is a normal CallToolResult
        with is_error=True (not a raised exception), even with
        raise_exceptions=True on the client — the SDK logs "Unknown tool: ..."
        server-side and returns it as tool-call content, not a protocol error."""
        async with Client(mcp_server.mcp, raise_exceptions=True) as c:
            result = await c.call_tool("no_such_tool", {})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_legacy_mode_discovery_and_call(self, db):
        """What today's Claude clients actually speak — a green modern-mode
        suite above does not prove this path works."""
        db.stream.side_effect = lambda *a, **k: iter([])
        async with Client(mcp_server.mcp, mode="legacy") as c:
            tools = await c.list_tools()
            assert {t.name for t in tools.tools} == DOCUMENTED_TOOLS
            result = await c.call_tool("list_categories", {})
        assert result.is_error is False


# ── 1.6c Concurrency — v2 runs sync tools in worker threads ─────────────────


class TestConcurrentToolCalls:
    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_do_not_cross_wires(self, monkeypatch, db):
        """If sync tools still ran inline on the event loop (v1 behaviour), 8
        calls sleeping 0.2s each would serialise to ~1.6s. Worker threads (v2)
        run them in parallel, so wall time stays well under that.

        Lazy singletons touched from tools, and why each is safe under
        concurrent worker threads: firestore.get_db is a per-call factory
        here (patched to a shared mock, which is fine — no tool mutates it
        concurrently in this test); app.cache.cache normally wraps either an
        in-memory dict guarded by the GIL or a thread-safe Redis client;
        rate_limit._fallback and mcp_auth._jwks_client are read-mostly caches
        with idempotent re-initialization. None are touched by list_categories.
        """
        counter = count()

        def slow_get_categories(_db):
            time.sleep(0.2)
            return [f"cat-{next(counter)}"]

        monkeypatch.setattr("app.services.recipes.get_categories", slow_get_categories)

        results = []

        async def one_call():
            async with Client(mcp_server.mcp) as c:
                r = await c.call_tool("list_categories", {})
                results.append(json.loads(r.content[0].text)["categories"][0])

        start = time.monotonic()
        async with anyio.create_task_group() as tg:
            for _ in range(8):
                tg.start_soon(one_call)
        elapsed = time.monotonic() - start

        assert len(results) == 8
        assert len(set(results)) == 8, "two calls returned the same (corrupted-copy) result"
        assert elapsed < 1.0, f"took {elapsed:.2f}s — looks like serial (inline) execution"


# ── 1.6d Request-body limit — v2 default is 4 MiB ───────────────────────────


class TestRequestBodyLimit:
    def test_oversized_body_rejected(self, client):
        """Recorded: 413, "Request body too large" — the SDK's default 4 MiB
        max_request_body_size on streamable_http_app(). Recipe payloads are far
        smaller than that; media goes through signed URLs, not this endpoint."""
        oversized = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {"pad": "a" * (5 * 1024 * 1024)}})
        response = client.post("/mcp", content=oversized, headers=MCP_HEADERS)
        assert response.status_code == 413


# ── 1.6b HTTP mount ──────────────────────────────────────────────────────────


class TestHttpMount:
    def test_mcp_initialize_over_http(self, client):
        response = client.post("/mcp", json=INITIALIZE_BODY, headers=MCP_HEADERS)
        assert response.status_code == 200
        body = response.text
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            body = next(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
        assert "serverInfo" in body

    def test_mcp_rejects_incomplete_accept(self, client):
        """A client must accept both application/json and text/event-stream —
        omitting the header entirely defaults to httpx's "*/*" and is accepted
        (that path is covered by test_mcp_initialize_over_http), but an
        explicit, incomplete Accept is rejected."""
        response = client.post("/mcp", json=INITIALIZE_BODY,
                                headers={"Content-Type": "application/json", "Accept": "application/json"})
        assert response.status_code == 406

    def test_mcp_not_421_behind_non_localhost_host(self, client):
        """The DNS-rebinding tripwire: fails if transport_security was not
        passed to streamable_http_app() (see create_mcp_app's docstring)."""
        response = client.post("/mcp", json=INITIALIZE_BODY, headers={**MCP_HEADERS, "Host": "testserver"})
        assert response.status_code != 421

    def test_mount_ordering_preserved(self, client):
        assert client.get("/api/health").status_code == 200
        assert client.get("/definitely-not-a-route").status_code == 404


# ── Package structure (app/mcp_server/ split) ───────────────────────────────


class TestPackageStructure:
    @pytest.mark.asyncio
    async def test_registered_tools_equal_module_tool_tuples(self):
        """The tool surface is exactly the union of each tools/*.py module's
        TOOLS tuple — nothing registers by import-order side effect."""
        expected = {tool.__name__ for module in mcp_server.TOOL_MODULES for tool in module.TOOLS}
        async with Client(mcp_server.mcp) as c:
            result = await c.list_tools()
        assert {t.name for t in result.tools} == expected

    def test_sdk_is_imported_only_in_server_py(self):
        """server.py is the only module in the package allowed to import the
        mcp SDK — every tools/*.py module talks to it only through the `mcp`
        object register(mcp) receives."""
        import ast
        from pathlib import Path

        package_dir = Path(mcp_server.__file__).parent
        offenders = []
        for path in package_dir.rglob("*.py"):
            if path.name == "server.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                if any(name and (name == "mcp" or name.startswith("mcp.")) for name in names):
                    offenders.append(str(path.relative_to(package_dir)))
        assert not offenders, f"mcp SDK imported outside server.py: {offenders}"

    def test_prod_config_serves_auth_challenge(self):
        """build_server/build_app take an explicit settings object, so a
        prod-like server can be built and probed without patching module
        globals or setting real env vars — this is the same server.py path
        production actually runs, just constructed with a fake settings."""
        from types import SimpleNamespace

        from starlette.testclient import TestClient

        prod_settings = SimpleNamespace(
            is_dev=False,
            workos_issuer_url="https://example.authkit.app",
            mcp_resource_url="https://api.example.com/mcp",
            mcp_required_scopes_list=[],
        )
        server = mcp_server.build_server(prod_settings)
        app = mcp_server.build_app(prod_settings, server)

        with TestClient(app) as c:
            response = c.post("/mcp", json=INITIALIZE_BODY, headers=MCP_HEADERS)
            assert response.status_code == 401
            assert "resource_metadata=" in response.headers.get("www-authenticate", "")

            metadata = c.get("/.well-known/oauth-protected-resource/mcp")
            assert metadata.status_code == 200
            assert metadata.json()["authorization_servers"] == ["https://example.authkit.app"]
