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
