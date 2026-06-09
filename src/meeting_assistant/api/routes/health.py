from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from meeting_assistant.api.deps import get_container, get_settings
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.services.readiness import build_readiness_report

router = APIRouter()


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
        content={"status": report.status, "checks": report.checks},
    )
