from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalRequestResponse(BaseModel):
    approval_request_id: int
    workflow_run_id: int
    tool_execution_id: int
    tool_name: str
    payload: dict[str, object]
    status: str
    requested_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class ApprovalResolutionRequest(BaseModel):
    resolved_by: str | None = Field(default=None, min_length=1)


class ApprovalResolutionResponse(BaseModel):
    approval_request_id: int
    workflow_run_id: int
    approval_status: str
    tool_status: str
    tool_result: dict[str, object]
    workflow_status: str
    summary: str
    tool_executions: list[dict[str, object]] = Field(default_factory=list)
    iterations_used: int
