from pydantic import BaseModel, EmailStr, Field, model_validator


class BatchMeetingRequest(BaseModel):
    user_external_id: str = Field(min_length=1)
    user_email: EmailStr
    title: str = Field(min_length=1)
    source_uri: str | None = None
    transcript_text: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "BatchMeetingRequest":
        if not self.source_uri and not self.transcript_text:
            raise ValueError("Either source_uri or transcript_text must be provided.")
        return self


class BatchMeetingResponse(BaseModel):
    class ToolExecutionRecord(BaseModel):
        tool_name: str
        status: str
        attempts: int
        idempotency_key: str
        result: dict[str, object] | None = None

    meeting_id: int
    workflow_run_id: int
    status: str
    summary: str
    tasks_created: int
    decisions_logged: int
    tool_calls_recorded: int
    tool_executions: list[ToolExecutionRecord] = Field(default_factory=list)
