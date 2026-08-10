from fastapi import APIRouter, Depends, HTTPException, Request

from meeting_assistant.api.auth import assert_resource_user_scope
from meeting_assistant.api.deps import get_container, get_principal
from meeting_assistant.container import Container
from meeting_assistant.schemas.approval import (
    ApprovalRequestResponse,
    ApprovalResolutionRequest,
    ApprovalResolutionResponse,
)
from meeting_assistant.services.approval_lock import ApprovalLockBusy

router = APIRouter(tags=["approvals"])


@router.get("/workflows/{workflow_run_id}/approvals", response_model=list[ApprovalRequestResponse])
def list_workflow_approvals(
    request: Request,
    workflow_run_id: int,
    container: Container = Depends(get_container),
) -> list[ApprovalRequestResponse]:
    owner_id = container.repository.get_user_external_id_for_workflow(workflow_run_id)
    assert_resource_user_scope(
        get_principal(request),
        user_external_id=owner_id,
        not_found_detail=f"Workflow run {workflow_run_id} not found",
    )
    try:
        return container.approval_service.list_workflow_approvals(workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/approvals/{approval_request_id}/approve", response_model=ApprovalResolutionResponse)
def approve_request(
    request: Request,
    approval_request_id: int,
    payload: ApprovalResolutionRequest | None = None,
    container: Container = Depends(get_container),
) -> ApprovalResolutionResponse:
    owner_id = container.repository.get_user_external_id_for_approval(approval_request_id)
    assert_resource_user_scope(
        get_principal(request),
        user_external_id=owner_id,
        not_found_detail=f"Approval request {approval_request_id} not found",
    )
    try:
        return container.approval_service.approve(
            approval_request_id,
            resolved_by=payload.resolved_by if payload else None,
        )
    except ApprovalLockBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc


@router.post("/approvals/{approval_request_id}/reject", response_model=ApprovalResolutionResponse)
def reject_request(
    request: Request,
    approval_request_id: int,
    payload: ApprovalResolutionRequest | None = None,
    container: Container = Depends(get_container),
) -> ApprovalResolutionResponse:
    owner_id = container.repository.get_user_external_id_for_approval(approval_request_id)
    assert_resource_user_scope(
        get_principal(request),
        user_external_id=owner_id,
        not_found_detail=f"Approval request {approval_request_id} not found",
    )
    try:
        return container.approval_service.reject(
            approval_request_id,
            resolved_by=payload.resolved_by if payload else None,
        )
    except ApprovalLockBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc
