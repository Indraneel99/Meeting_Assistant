from __future__ import annotations

from fastapi import FastAPI

from meeting_assistant.core.config import Settings
from meeting_assistant.core.logging import get_logger

logger = get_logger("meeting_assistant.telemetry")


def configure_telemetry(settings: Settings, app: FastAPI) -> None:
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

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready")
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()
    logger.info("otel_configured", service_name=settings.otel_service_name)
