from fastapi import APIRouter, Depends, HTTPException

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.schemas.approval import (
    ApprovalRequestResponse,
    ApprovalResolutionRequest,
    ApprovalResolutionResponse,
)

router = APIRouter(tags=["approvals"])


@router.get("/workflows/{workflow_run_id}/approvals", response_model=list[ApprovalRequestResponse])
def list_workflow_approvals(
    workflow_run_id: int,
    container: Container = Depends(get_container),
) -> list[ApprovalRequestResponse]:
    try:
        return container.approval_service.list_workflow_approvals(workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/approvals/{approval_request_id}/approve", response_model=ApprovalResolutionResponse)
def approve_request(
    approval_request_id: int,
    payload: ApprovalResolutionRequest | None = None,
    container: Container = Depends(get_container),
) -> ApprovalResolutionResponse:
    try:
        return container.approval_service.approve(
            approval_request_id,
            resolved_by=payload.resolved_by if payload else None,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc


@router.post("/approvals/{approval_request_id}/reject", response_model=ApprovalResolutionResponse)
def reject_request(
    approval_request_id: int,
    payload: ApprovalResolutionRequest | None = None,
    container: Container = Depends(get_container),
) -> ApprovalResolutionResponse:
    try:
        return container.approval_service.reject(
            approval_request_id,
            resolved_by=payload.resolved_by if payload else None,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc
