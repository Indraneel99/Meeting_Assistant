from pydantic import BaseModel, Field


class WorkflowToolExecutionRecord(BaseModel):
    tool_name: str
    status: str
    attempts: int
    idempotency_key: str
    result: dict[str, object] | None = None


class WorkflowStatusResponse(BaseModel):
    workflow_run_id: int
    meeting_id: int
    status: str
    failure_reason: str | None = None
    iteration_count: int = 0
    summary: str | None = None
    tasks_created: int | None = None
    decisions_logged: int | None = None
    tool_calls_recorded: int | None = None
    tool_executions: list[WorkflowToolExecutionRecord] = Field(default_factory=list)
