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
from unittest.mock import MagicMock, patch

import pytest

from app.mcp_server.wrapper import mcp_tool
from app.services import instagram, recipes as recipe_service


@pytest.fixture(autouse=True)
def mock_audit_db():
    """Every read_only=False call below now also triggers wrapper.py's
    audit.record() (S13) — without this, that call reaches the real
    Firestore client (no credentials in this environment) and logs a
    WARNING on every single one of them, polluting caplog-based assertions
    in tests that have nothing to do with auditing. TestAuditTrail below
    overrides this per-test where it actually wants to inspect the write.
    """
    with patch("app.mcp_server.audit.get_db", return_value=MagicMock()):
        yield


@pytest.fixture(autouse=True)
def mock_idempotency_db():
    """Same reasoning as mock_audit_db above, for idempotency.py (S15) —
    only reached when a test both supplies a client_id AND passes
    idempotency_key, but mocked unconditionally so that combination never
    silently starts hitting real Firestore in some future test that adds
    one without the other having been present already."""
    with patch("app.mcp_server.idempotency.get_db", return_value=MagicMock()):
        yield


def _caller(client_id: str, subject: str | None = None) -> SimpleNamespace:
    """A fake mcp AccessToken-shaped object — real ones have more fields
    (token, scopes, ...) but wrapper.py's _current_caller() only ever reads
    .client_id and .subject."""
    return SimpleNamespace(client_id=client_id, subject=subject)


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
    _current_caller() is the thin, already-covered translation from that
    call to a plain (client_id, subject) pair — patching at that boundary
    keeps this test about mcp_tool()'s behavior, not about re-deriving how
    the SDK's auth context works.
    """

    def test_a_rejected_call_never_invokes_the_wrapped_function(self):
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn():
            calls.append(1)
            return {"ok": True}

        with patch(
            "app.mcp_server.wrapper.get_access_token",
            return_value=_caller("rate-test-client"),
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
            return_value=_caller("rate-test-client-2"),
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


class TestAuditTrail:
    """audit.py has its own tests (test_mcp_audit.py) for target extraction
    and the write-failure-is-swallowed behavior — this class checks only
    that mcp_tool() calls it at the right time: for mutating tools, not
    read-only ones, with the arguments the tool was actually called with.
    """

    def test_a_mutating_call_writes_one_audit_doc(self):
        mock_db = MagicMock()

        @mcp_tool(read_only=False, budget="write")
        def fn(recipe_id: str):
            return {"id": recipe_id, "published": True}

        with (
            patch("app.mcp_server.audit.get_db", return_value=mock_db),
            patch("app.mcp_server.wrapper.get_access_token", return_value=_caller("client-x")),
        ):
            fn(recipe_id="r1")

        mock_db.collection.assert_called_once_with("mcp_audit")
        written = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert written["tool"] == "fn"
        assert written["ok"] is True
        assert written["client_id"] == "client-x"
        assert written["arg_keys"] == ["recipe_id"]

    def test_a_read_only_call_writes_no_audit_doc(self):
        mock_db = MagicMock()

        @mcp_tool(read_only=True)
        def fn():
            return {"count": 0}

        with patch("app.mcp_server.audit.get_db", return_value=mock_db):
            fn()

        mock_db.collection.assert_not_called()

    def test_a_failed_mutating_call_still_writes_an_audit_doc(self):
        """Named update_recipe (rather than a generic local `fn`) since
        audit.py's target extraction is keyed by real tool name — see
        test_mcp_audit.py for that logic's own dedicated tests; this one
        just confirms the wrapper passes kwargs through so target ends up
        populated even on a failure, where audit._build_target has only
        the caller-supplied recipe_id to go on (the result carries none)."""
        mock_db = MagicMock()

        @mcp_tool(read_only=False, budget="write")
        def update_recipe(recipe_id: str):
            raise recipe_service.RecipeNotFound(recipe_id)

        with patch("app.mcp_server.audit.get_db", return_value=mock_db):
            update_recipe(recipe_id="ghost")

        written = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert written["ok"] is False
        assert written["error"] == "not_found"
        assert written["target"] == {"recipe_id": "ghost"}

    def test_an_audit_write_failure_does_not_fail_the_call(self):
        with patch("app.mcp_server.audit.get_db", side_effect=RuntimeError("firestore down")):

            @mcp_tool(read_only=False, budget="write")
            def fn():
                return {"ok": True}

            result = fn()  # must not raise

        assert result == {"ok": True}


def _fake_idempotency_db() -> MagicMock:
    """A minimal fake Firestore client backing idempotency.py's
    get/set-by-document-id calls with a real in-memory dict, so a test can
    prove a second call with the same key genuinely returns the first
    call's stored result — not just that some mock method was invoked."""
    store: dict[str, dict] = {}

    def fake_document(doc_id):
        doc = MagicMock()
        doc.set.side_effect = lambda data: store.__setitem__(doc_id, data)

        def fake_get():
            if doc_id in store:
                snap = MagicMock(exists=True)
                snap.to_dict.return_value = store[doc_id]
                return snap
            return MagicMock(exists=False)

        doc.get.side_effect = fake_get
        return doc

    mock_db = MagicMock()
    mock_db.collection.return_value.document.side_effect = fake_document
    return mock_db


class TestIdempotency:
    """idempotency.py has its own thorough tests (test_mcp_idempotency.py)
    for the cache primitives — this class checks only that mcp_tool() wires
    them in at the right point: skipped without a client_id or a key,
    consulted before fn() runs, and populated after.
    """

    def test_a_repeated_key_returns_the_cached_result_without_rerunning_fn(self):
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn(idempotency_key=None):
            calls.append(1)
            return {"id": f"call-{len(calls)}"}

        with (
            patch("app.mcp_server.idempotency.get_db", return_value=_fake_idempotency_db()),
            patch("app.mcp_server.wrapper.get_access_token", return_value=_caller("client-idem")),
        ):
            first = fn(idempotency_key="key-1")
            second = fn(idempotency_key="key-1")

        assert first == {"id": "call-1"}
        assert second == {"id": "call-1"}  # not "call-2" — fn() ran only once
        assert len(calls) == 1

    def test_a_different_key_runs_fn_again(self):
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn(idempotency_key=None):
            calls.append(1)
            return {"id": f"call-{len(calls)}"}

        with (
            patch("app.mcp_server.idempotency.get_db", return_value=_fake_idempotency_db()),
            patch("app.mcp_server.wrapper.get_access_token", return_value=_caller("client-idem")),
        ):
            fn(idempotency_key="key-1")
            second = fn(idempotency_key="key-2")

        assert second == {"id": "call-2"}
        assert len(calls) == 2

    def test_no_key_means_todays_behavior_every_call_runs_fn(self):
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn(idempotency_key=None):
            calls.append(1)
            return {"id": f"call-{len(calls)}"}

        with patch("app.mcp_server.wrapper.get_access_token", return_value=_caller("client-idem")):
            fn()
            fn()

        assert len(calls) == 2

    def test_a_failed_result_is_also_cached_and_replayed(self):
        """Matches the plan's own acceptance wording ("same key twice ->
        identical result") literally: a repeat of a call that failed
        returns the SAME failure, not a fresh attempt. A transient failure
        that genuinely needs retrying should use a new key."""
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn(idempotency_key=None):
            calls.append(1)
            raise recipe_service.RecipeNotFound("r1")

        with (
            patch("app.mcp_server.idempotency.get_db", return_value=_fake_idempotency_db()),
            patch("app.mcp_server.wrapper.get_access_token", return_value=_caller("client-idem")),
        ):
            first = fn(idempotency_key="key-1")
            second = fn(idempotency_key="key-1")

        assert first == second == {"error": "not_found", "message": "Recipe not found: r1"}
        assert len(calls) == 1

    def test_without_a_client_id_idempotency_never_applies(self):
        """dev mode / an in-memory Client() test: no client_id means no
        identity to scope the cache to, so every call runs fn() — matches
        rate_budgets.py's own no-client-id no-op precedent."""
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn(idempotency_key=None):
            calls.append(1)
            return {"id": f"call-{len(calls)}"}

        fn(idempotency_key="key-1")
        fn(idempotency_key="key-1")

        assert len(calls) == 2

    def test_an_overlong_key_is_rejected_before_fn_runs(self):
        calls = []

        @mcp_tool(read_only=False, budget="write")
        def fn(idempotency_key=None):
            calls.append(1)
            return {"ok": True}

        with patch("app.mcp_server.wrapper.get_access_token", return_value=_caller("client-idem")):
            result = fn(idempotency_key="x" * 129)

        assert result["error"] == "invalid_request"
        assert len(calls) == 0
