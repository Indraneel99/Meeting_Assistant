from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from meeting_assistant.bootstrap import bootstrap_container
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.core.logging import RequestContextMiddleware, configure_logging
from meeting_assistant.core.telemetry import (
    attach_trace_context,
    configure_telemetry,
    extract_trace_context_from_carrier,
)
from meeting_assistant.services.pubsub_push import (
    PubSubPushEnvelope,
    decode_pubsub_push_envelope,
    verify_pubsub_push_authorization,
)
from meeting_assistant.services.readiness import build_readiness_report

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings or Settings()


def get_container(request: Request) -> Container:
    return request.app.state.container


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness(
    container: Container = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    report = build_readiness_report(container, settings)
    return JSONResponse(
        status_code=200 if report.is_ready else 503,
        content={
            "status": report.status,
            "checks": report.checks,
            **({"details": report.details} if report.details else {}),
        },
    )


@router.post("/internal/jobs/batch")
def handle_pubsub_batch_push(
    envelope: PubSubPushEnvelope,
    container: Container = Depends(get_container),
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    verify_pubsub_push_authorization(
        authorization,
        audience=settings.pubsub_push_audience,
        skip_auth=settings.pubsub_push_skip_auth,
    )

    workflow_run_id, payload, attributes = decode_pubsub_push_envelope(envelope)
    parent_context = extract_trace_context_from_carrier(attributes)

    try:
        with attach_trace_context(parent_context):
            container.orchestrator.run_batch_workflow(workflow_run_id, payload)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="batch workflow processing failed") from exc

    return {"status": "ok"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings or Settings()
    configure_logging(settings)
    app.state.container = bootstrap_container(settings)
    yield


def create_worker_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(
        title="Meeting Assistant Worker",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.add_middleware(RequestContextMiddleware, service_name=resolved_settings.otel_worker_service_name)
    app.include_router(router)
    configure_telemetry(resolved_settings)
    return app


app = create_worker_app()
