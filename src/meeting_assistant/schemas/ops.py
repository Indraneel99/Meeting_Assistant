from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StaleWorkflowItem(BaseModel):
    workflow_run_id: int
    meeting_id: int
    user_external_id: str | None
    status: str
    created_at: datetime
    pending_minutes: int


class StaleWorkflowAlertResponse(BaseModel):
    enabled: bool
    threshold_minutes: int
    count: int
    workflows: list[StaleWorkflowItem] = Field(default_factory=list)


class FailedToolItem(BaseModel):
    tool_execution_id: int
    workflow_run_id: int
    meeting_id: int
    user_external_id: str | None
    tool_name: str
    status: str
    attempt_count: int
    max_retries: int
    dlq: bool
    error_message: str | None
    last_attempt_at: datetime | None


class FailedToolAlertResponse(BaseModel):
    enabled: bool
    lookback_minutes: int
    max_retries: int
    count: int
    executions: list[FailedToolItem] = Field(default_factory=list)
