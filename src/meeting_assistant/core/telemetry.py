from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI

from meeting_assistant.core.config import Settings
from meeting_assistant.core.logging import get_logger

logger = get_logger("meeting_assistant.telemetry")

TRACE_CONTEXT_KEY = "__otel_trace_context"
_tracer = None


def _get_tracer():
    global _tracer
    if _tracer is None:
        try:
            from opentelemetry import trace

            _tracer = trace.get_tracer("meeting_assistant")
        except ImportError:
            return None
    return _tracer


def configure_telemetry(settings: Settings, app: FastAPI | None = None) -> None:
    if not settings.otel_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("otel_dependencies_missing", error=str(exc))
        return

    service_name = settings.otel_service_name if app is not None else settings.otel_worker_service_name
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready")
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()
    logger.info("otel_configured", service_name=service_name, component="api" if app is not None else "worker")


def inject_trace_context(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from opentelemetry.propagate import inject
    except ImportError:
        return payload

    enriched = dict(payload)
    carrier: dict[str, str] = {}
    inject(carrier)
    if carrier:
        enriched[TRACE_CONTEXT_KEY] = carrier
    return enriched


def pop_trace_context(payload: dict[str, Any]) -> Any | None:
    carrier = payload.pop(TRACE_CONTEXT_KEY, None)
    return extract_trace_context_from_carrier(carrier)


def extract_trace_context_from_carrier(carrier: dict[str, str] | None) -> Any | None:
    if not carrier:
        return None
    try:
        from opentelemetry.propagate import extract

        return extract(carrier)
    except ImportError:
        return None


@contextmanager
def trace_batch_workflow(workflow_run_id: int | None = None, *, parent_context: Any | None = None) -> Iterator[None]:
    tracer = _get_tracer()
    if tracer is None:
        yield
        return

    from opentelemetry import context, trace

    token = context.attach(parent_context) if parent_context is not None else None
    attributes: dict[str, int] = {}
    if workflow_run_id is not None:
        attributes["workflow_run_id"] = workflow_run_id
    try:
        with tracer.start_as_current_span(
            "batch.process_workflow",
            attributes=attributes,
            kind=trace.SpanKind.CONSUMER,
        ):
            yield
    finally:
        if token is not None:
            context.detach(token)


@contextmanager
def trace_tool_execution(workflow_run_id: int, tool_name: str) -> Iterator[None]:
    tracer = _get_tracer()
    if tracer is None:
        yield
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(
        "tool.execute",
        attributes={"workflow_run_id": workflow_run_id, "tool.name": tool_name},
        kind=trace.SpanKind.CLIENT,
    ):
        yield


@contextmanager
def attach_trace_context(parent_context: Any | None) -> Iterator[None]:
    if parent_context is None:
        yield
        return

    try:
        from opentelemetry import context
    except ImportError:
        yield
        return

    token = context.attach(parent_context)
    try:
        yield
    finally:
        context.detach(token)
