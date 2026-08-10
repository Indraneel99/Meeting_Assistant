from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.core.telemetry import (
    TRACE_CONTEXT_KEY,
    configure_telemetry,
    inject_trace_context,
    pop_trace_context,
    trace_batch_workflow,
    trace_tool_execution,
)
from meeting_assistant.schemas.planner import ToolCall
from meeting_assistant.services.jobs import SyncBatchJobQueue
from meeting_assistant.services.tools.base import ToolProvider
from meeting_assistant.services.tools.executor import ToolExecutor


def _ensure_tracer_provider(exporter: InMemorySpanExporter) -> None:
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        current.add_span_processor(SimpleSpanProcessor(exporter))
        return
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def test_configure_telemetry_noop_when_disabled() -> None:
    settings = Settings(otel_enabled=False)
    configure_telemetry(settings, FastAPI())


def test_configure_telemetry_api_enables_tracer() -> None:
    settings = Settings(otel_enabled=True, otel_service_name="meeting-assistant-api")
    configure_telemetry(settings, FastAPI())
    assert isinstance(trace.get_tracer_provider(), TracerProvider)


def test_configure_telemetry_worker_enables_tracer() -> None:
    settings = Settings(
        otel_enabled=True,
        otel_worker_service_name="meeting-assistant-worker",
    )
    configure_telemetry(settings)
    assert isinstance(trace.get_tracer_provider(), TracerProvider)


def test_trace_context_inject_and_pop_roundtrip() -> None:
    settings = Settings(otel_enabled=True)
    configure_telemetry(settings, FastAPI())

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("parent_request"):
        enriched = inject_trace_context({"title": "Weekly sync"})

    assert TRACE_CONTEXT_KEY in enriched
    assert enriched["title"] == "Weekly sync"

    payload = dict(enriched)
    parent_context = pop_trace_context(payload)
    assert TRACE_CONTEXT_KEY not in payload
    assert parent_context is not None


def test_sync_batch_queue_injects_trace_context() -> None:
    settings = Settings(otel_enabled=True)
    configure_telemetry(settings, FastAPI())

    captured: dict[str, object] = {}

    def handler(workflow_run_id: int, payload: dict[str, object]) -> None:
        captured["workflow_run_id"] = workflow_run_id
        captured["payload"] = payload

    queue = SyncBatchJobQueue(handler)
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("batch.submit"):
        queue.enqueue_batch(42, {"title": "Demo", "transcript_text": "hello"})

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert TRACE_CONTEXT_KEY in payload
    assert captured["workflow_run_id"] == 42


def test_trace_batch_workflow_emits_span() -> None:
    exporter = InMemorySpanExporter()
    _ensure_tracer_provider(exporter)

    with trace_batch_workflow(99):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "batch.process_workflow"
    assert spans[0].attributes["workflow_run_id"] == 99


def test_trace_tool_execution_emits_span() -> None:
    exporter = InMemorySpanExporter()
    _ensure_tracer_provider(exporter)

    with trace_tool_execution(7, "email.send"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "tool.execute"
    assert spans[0].attributes["workflow_run_id"] == 7
    assert spans[0].attributes["tool.name"] == "email.send"


def test_create_app_with_otel_enabled_starts_cleanly() -> None:
    settings = Settings(
        otel_enabled=True,
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=False,
    )
    with patch("meeting_assistant.api.app.configure_telemetry") as configure_mock:
        app = create_app(settings)
        configure_mock.assert_called_once_with(settings, app)


def test_tool_executor_wraps_execution_with_span() -> None:
    exporter = InMemorySpanExporter()
    _ensure_tracer_provider(exporter)

    class StubProvider(ToolProvider):
        def execute(self, payload: dict[str, object], *, idempotency_key: str) -> dict[str, object]:
            return {"message": "sent"}

    execution = type("Execution", (), {"id": 1, "status": "pending", "result": None})()
    repository = patch("meeting_assistant.repositories.Repository").start()
    repository.get_tool_execution.return_value = None
    repository.create_tool_execution.return_value = execution
    repository.count_tool_execution_attempts.return_value = 0

    executor = ToolExecutor(repository, providers={"email.send": StubProvider()})
    try:
        outcome = executor.execute(
            5,
            ToolCall(tool_name="email.send", payload={"subject": "Follow-up", "body": "Please send this"}),
        )
    finally:
        patch.stopall()

    assert outcome.status == "executed"
    span_names = [span.name for span in exporter.get_finished_spans()]
    assert "tool.execute" in span_names
