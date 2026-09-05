"""Tests for app/tracing.py's Cloud Trace export of the mcp SDK's built-in spans.

configure_tracing() must never raise — a tracing misconfiguration is not
allowed to take the whole app down at startup (see its own docstring) — and
opentelemetry's global TracerProvider can only be installed once per process,
so every test that calls set_tracer_provider must reset the module-private
_TRACER_PROVIDER afterwards or later tests (in this file and beyond) would
silently keep whatever provider an earlier test installed.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from opentelemetry import trace


@pytest.fixture(autouse=True)
def reset_tracer_provider():
    """Isolate each test's global TracerProvider install. See module docstring.

    The one-shot guard is trace._TRACER_PROVIDER_SET_ONCE (an
    opentelemetry.util._once.Once), not the _TRACER_PROVIDER value itself —
    do_once() short-circuits on the Once object regardless of what
    _TRACER_PROVIDER currently holds, so a fresh Once() is what actually
    lets a later set_tracer_provider() call take effect.
    """
    original_provider = trace._TRACER_PROVIDER
    original_once = trace._TRACER_PROVIDER_SET_ONCE
    yield
    trace._TRACER_PROVIDER = original_provider
    trace._TRACER_PROVIDER_SET_ONCE = original_once


def _settings(**over):
    base = dict(is_dev=True, trace_enabled=True, trace_sample_ratio=1.0, gcp_project_id="test-project")
    base.update(over)
    return SimpleNamespace(**base)


class TestConfigureTracingOff:
    def test_dev_skips_tracing_entirely(self):
        with patch("app.tracing.settings", _settings(is_dev=True)):
            with patch("opentelemetry.trace.set_tracer_provider") as mock_set:
                result = app_tracing_configure()
        assert result is False
        mock_set.assert_not_called()

    def test_disabled_flag_skips_even_in_prod(self):
        with patch("app.tracing.settings", _settings(is_dev=False, trace_enabled=False)):
            with patch("opentelemetry.trace.set_tracer_provider") as mock_set:
                result = app_tracing_configure()
        assert result is False
        mock_set.assert_not_called()


class TestConfigureTracingOn:
    def test_prod_installs_one_span_processor(self):
        trace._TRACER_PROVIDER_SET_ONCE = trace.Once()
        with patch("app.tracing.settings", _settings(is_dev=False)):
            with patch("opentelemetry.exporter.cloud_trace.CloudTraceSpanExporter") as mock_exporter_cls:
                with patch(
                    "opentelemetry.sdk.trace.export.SimpleSpanProcessor",
                ) as mock_processor_cls:
                    result = app_tracing_configure()

        from opentelemetry.sdk.trace import TracerProvider

        assert result is True
        mock_exporter_cls.assert_called_once_with(project_id="test-project")
        mock_processor_cls.assert_called_once_with(mock_exporter_cls.return_value)
        assert isinstance(trace.get_tracer_provider(), TracerProvider)

    def test_exporter_construction_failure_is_swallowed(self, caplog):
        with patch("app.tracing.settings", _settings(is_dev=False)):
            with patch(
                "opentelemetry.exporter.cloud_trace.CloudTraceSpanExporter",
                side_effect=RuntimeError("no ADC credentials"),
            ):
                result = app_tracing_configure()

        assert result is False
        assert any("configure_tracing failed" in r.message for r in caplog.records)


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_a_real_tool_call_produces_a_finished_span(self, mcp_db):
        """Bypasses configure_tracing's hardcoded Cloud Trace exporter and
        installs an in-memory one directly — proves spans actually flow
        through the SDK's instrumentation once *any* real TracerProvider is
        the global one, which is what configure_tracing itself installs in
        production. mcp_db (conftest.py) stands in for Firestore so the call
        doesn't need real credentials."""
        from mcp.client import Client
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        from app import mcp_server

        mcp_db.stream.return_value = iter([])

        exporter = InMemorySpanExporter()
        provider = TracerProvider(resource=Resource.create({"service.name": "mfs-backend-test"}))
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        # set_tracer_provider is one-shot per process, guarded by a separate
        # Once object (not by _TRACER_PROVIDER's value) — see the
        # reset_tracer_provider fixture's docstring.
        trace._TRACER_PROVIDER_SET_ONCE = trace.Once()
        trace.set_tracer_provider(provider)

        async with Client(mcp_server.mcp) as c:
            await c.call_tool("list_categories", {})

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1


def app_tracing_configure():
    """Import inline so the module-level `settings` patched above is read
    freshly by configure_tracing() on every call rather than bound once at
    collection time."""
    from app.tracing import configure_tracing

    return configure_tracing()
