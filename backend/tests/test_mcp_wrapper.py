"""Tests for mcp_server/wrapper.py's mcp_tool() decorator: the outcome log,
the MCP_TOOL_FAILED alert marker, and the annotations/budget it attaches to
the wrapped function.

test_mcp_transport.py::test_snapshot_create_recipe_schema is the ground-truth
snapshot of every real tool's annotation matrix as seen through the SDK's own
list_tools() — this file exercises the decorator directly instead, so a
failure here points at wrapper.py itself rather than at a tool's own
@mcp_tool(...) call.
"""

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.mcp_server.wrapper import mcp_tool
from app.services import instagram, recipes as recipe_service


class TestAnnotationsAndBudget:
    def test_attaches_annotations_matching_the_kwargs(self):
        @mcp_tool(read_only=False, destructive=True, idempotent=True, open_world=True, budget="publish_social")
        def fn():
            return {}

        assert fn.mcp_annotations.read_only_hint is False
        assert fn.mcp_annotations.destructive_hint is True
        assert fn.mcp_annotations.idempotent_hint is True
        assert fn.mcp_annotations.open_world_hint is True
        assert fn.mcp_budget == "publish_social"

    def test_defaults_are_the_common_read_case(self):
        @mcp_tool(read_only=True)
        def fn():
            return {}

        assert fn.mcp_annotations.destructive_hint is False
        assert fn.mcp_annotations.idempotent_hint is False
        assert fn.mcp_annotations.open_world_hint is False
        assert fn.mcp_budget == "read"

    def test_preserves_the_wrapped_function_identity(self):
        @mcp_tool(read_only=True)
        def my_tool(x: int) -> dict:
            """docstring"""
            return {"x": x}

        assert my_tool.__name__ == "my_tool"
        assert my_tool.__doc__ == "docstring"
        assert my_tool(5) == {"x": 5}


class TestOutcomeLog:
    def test_successful_call_logs_ok_true_with_no_warning(self, caplog):
        @mcp_tool(read_only=True)
        def fn():
            return {"count": 3}

        with caplog.at_level(logging.INFO, logger="app.mcp_server.wrapper"):
            result = fn()

        assert result == {"count": 3}
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) == 1
        assert info_records[0].json_fields == {
            "tool": "fn", "ok": True, "error": None, "client_id": None,
        }
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    def test_expected_error_kind_logs_ok_false_but_no_warning(self, caplog):
        """not_found, validation_error, etc. are routine tool output — the
        caller passed something the tool correctly rejected, nothing broke
        server-side, so this must not trigger the MCP_TOOL_FAILED alert
        marker (that would just be alert-fatigue noise)."""

        @mcp_tool(read_only=True)
        def fn():
            raise recipe_service.RecipeNotFound("r1")

        with caplog.at_level(logging.INFO, logger="app.mcp_server.wrapper"):
            result = fn()

        assert result["error"] == "not_found"
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert info_records[0].json_fields["ok"] is False
        assert info_records[0].json_fields["error"] == "not_found"
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    @pytest.mark.parametrize("exc, expected_error", [
        (RuntimeError("boom"), "internal"),
        (instagram.InstagramError("token expired", auth=True), "instagram_auth"),
        (instagram.InstagramError("rate limited", auth=False), "instagram"),
    ])
    def test_broken_error_kinds_trigger_the_failed_warning(self, caplog, exc, expected_error):
        @mcp_tool(read_only=False, budget="write")
        def fn():
            raise exc

        with caplog.at_level(logging.INFO, logger="app.mcp_server.wrapper"):
            result = fn()

        assert result["error"] == expected_error
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "MCP_TOOL_FAILED" in warnings[0].getMessage()
        assert "fn" in warnings[0].getMessage()

    def test_validation_error_is_translated_and_logged_not_raised(self, caplog):
        from pydantic import BaseModel

        class Model(BaseModel):
            x: int

        @mcp_tool(read_only=False, budget="write")
        def fn():
            Model.model_validate({"x": "not-an-int"})

        with caplog.at_level(logging.INFO, logger="app.mcp_server.wrapper"):
            result = fn()

        assert result["error"] == "validation_error"
        assert result["field_errors"][0]["field"] == "x"
        assert not any(r.levelno == logging.WARNING for r in caplog.records)


class TestRateLimitEnforcement:
    """rate_budgets.py has its own thorough tests (test_mcp_rate_budgets.py)
    for the actual limit math — this class checks only that mcp_tool()
    wires it in correctly: called with the real caller identity, and a
    rejection short-circuits before the wrapped function ever runs.

    get_access_token() is patched directly (rather than threading a real
    AccessToken through contextvars) since wrapper.py's own
    _current_client_id() is the thin, already-covered translation from that
    call to a plain client_id string — patching at that boundary keeps this
    test about mcp_tool()'s behavior, not about re-deriving how the SDK's
    auth context works.
    """

    def test_a_rejected_call_never_invokes_the_wrapped_function(self):
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn():
            calls.append(1)
            return {"ok": True}

        with patch(
            "app.mcp_server.wrapper.get_access_token",
            return_value=SimpleNamespace(client_id="rate-test-client"),
        ):
            for _ in range(30):
                fn()
            assert len(calls) == 30

            result = fn()  # 31st: over the write budget (30/min)

        assert result == {"error": "rate_limited", "retry_after_seconds": 60}
        assert len(calls) == 30  # the 31st call never reached fn()

    def test_a_rejected_call_still_logs_the_outcome_line(self, caplog):
        @mcp_tool(read_only=False, budget="write")
        def fn():
            return {"ok": True}

        with patch(
            "app.mcp_server.wrapper.get_access_token",
            return_value=SimpleNamespace(client_id="rate-test-client-2"),
        ):
            with caplog.at_level(logging.INFO, logger="app.mcp_server.wrapper"):
                for _ in range(31):
                    fn()

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert info_records[-1].json_fields["error"] == "rate_limited"
        assert info_records[-1].json_fields["ok"] is False
        # rate_limited is a working-as-designed rejection, not a broken tool
        # — it must not also trigger the MCP_TOOL_FAILED alert marker.
        assert not any("MCP_TOOL_FAILED" in r.getMessage() for r in caplog.records)

    def test_without_a_client_id_the_budget_never_applies(self):
        """dev mode / an in-memory Client() test: no patch needed here since
        get_access_token() genuinely returns None outside a request
        context, which is exactly the case this exercises."""
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn():
            calls.append(1)
            return {"ok": True}

        for _ in range(40):
            fn()

        assert len(calls) == 40
