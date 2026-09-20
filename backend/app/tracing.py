"""Export the mcp SDK's built-in OpenTelemetry spans to Cloud Trace.

mcp 2.x instruments every tools/call, tools/list and initialize request with
an OpenTelemetry span out of the box (see docs/DEPLOYMENT.md § MCP "Traces").
This module just wires a real exporter to that instrumentation — it is the
ONLY place in the app that touches the OpenTelemetry SDK (as opposed to the
API, which mcp itself already depends on — see requirements.lock).

Cloud Run only bills and schedules CPU while a request is in flight; outside
that window a background thread doing batched I/O may simply never run. A
BatchSpanProcessor buffers spans in memory and flushes them from its own
background thread — exactly the pattern that can silently lose every span
this instance ever produced. SimpleSpanProcessor exports synchronously,
inline with the request that created the span, which is slower per-span but
never drops data to a scheduler quirk. At this app's traffic volume the
latency cost is not worth trading correctness for.
"""

import logging

from .config import settings

logger = logging.getLogger(__name__)


def configure_tracing() -> bool:
    """Best-effort. Never raises — a tracing misconfiguration must not take
    the whole app down at startup. Returns True iff a real exporter was
    installed; False in dev, when disabled, or on any error (logged with a
    traceback either way, so the cause is visible in Cloud Logging)."""
    if settings.is_dev or not settings.trace_enabled:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        provider = TracerProvider(
            resource=Resource.create({"service.name": "mfs-backend"}),
            sampler=ParentBased(TraceIdRatioBased(settings.trace_sample_ratio)),
        )
        exporter = CloudTraceSpanExporter(project_id=settings.gcp_project_id)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        return True
    except Exception:
        # Never fails startup over tracing — the app is fully functional
        # without it, just less observable. logger.exception so the actual
        # cause (missing IAM binding, bad project id, import error) shows up
        # in Cloud Logging rather than only "tracing is off".
        logger.exception("configure_tracing failed; continuing without Cloud Trace export")
        return False
