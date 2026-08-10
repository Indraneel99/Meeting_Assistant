from fastapi import APIRouter, Depends, HTTPException, Request

from meeting_assistant.api.auth import assert_resource_user_scope
from meeting_assistant.api.deps import get_container, get_principal
from meeting_assistant.container import Container
from meeting_assistant.schemas.workflow import WorkflowStatusResponse

router = APIRouter(tags=["workflows"])


@router.get("/workflows/{workflow_run_id}", response_model=WorkflowStatusResponse)
def get_workflow_status(
    request: Request,
    workflow_run_id: int,
    container: Container = Depends(get_container),
) -> WorkflowStatusResponse:
    owner_id = container.repository.get_user_external_id_for_workflow(workflow_run_id)
    assert_resource_user_scope(
        get_principal(request),
        user_external_id=owner_id,
        not_found_detail=f"Workflow run {workflow_run_id} not found",
    )
    try:
        return container.orchestrator.get_workflow_status(workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
