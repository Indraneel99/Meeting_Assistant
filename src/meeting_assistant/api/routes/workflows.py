from fastapi import APIRouter, Depends, HTTPException

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.schemas.workflow import WorkflowStatusResponse

router = APIRouter(tags=["workflows"])


@router.get("/workflows/{workflow_run_id}", response_model=WorkflowStatusResponse)
def get_workflow_status(
    workflow_run_id: int,
    container: Container = Depends(get_container),
) -> WorkflowStatusResponse:
    try:
        return container.orchestrator.get_workflow_status(workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
