from fastapi import APIRouter, Depends

from meeting_assistant.api.deps import get_container, get_settings
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.schemas.ops import FailedToolAlertResponse, StaleWorkflowAlertResponse
from meeting_assistant.services.failed_tools import FailedToolMonitor
from meeting_assistant.services.stale_workflows import StaleWorkflowMonitor

router = APIRouter(tags=["ops"])


@router.get("/admin/ops/stale-workflows", response_model=StaleWorkflowAlertResponse)
def check_stale_workflows(
    container: Container = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> StaleWorkflowAlertResponse:
    """Poll for PENDING workflows older than threshold; emits structured logs for alerting."""
    return StaleWorkflowMonitor(container.repository, settings).check_and_alert()


@router.get("/admin/ops/failed-tools", response_model=FailedToolAlertResponse)
def check_failed_tools(
    container: Container = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> FailedToolAlertResponse:
    """Poll for failed tool executions and DLQ-style retry exhaustion; emits structured logs for alerting."""
    return FailedToolMonitor(container.repository, settings).check_and_alert()
