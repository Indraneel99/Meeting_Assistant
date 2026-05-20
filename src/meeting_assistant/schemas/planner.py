from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    payload: dict[str, str]


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee: str
    action: str


class PlannedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    decision_text: str


class PlanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    tasks: list[PlannedTask] = Field(default_factory=list)
    decisions: list[PlannedDecision] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
