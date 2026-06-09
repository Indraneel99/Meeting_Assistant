from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, model_validator


class ToolPayload(TypedDict):
    subject: str
    body: str
    title: str
    details: str
    target: str
    recipient: str
    channel: str
    issue_summary: str
    issue_description: str
    issue_type: str
    simulate_retryable_failure: str


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    payload: ToolPayload

    @model_validator(mode="before")
    @classmethod
    def fill_payload_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        payload = data.get("payload")
        if not isinstance(payload, dict):
            return data

        normalized_payload = {
            "subject": "",
            "body": "",
            "title": "",
            "details": "",
            "target": "",
            "recipient": "",
            "channel": "",
            "issue_summary": "",
            "issue_description": "",
            "issue_type": "",
            "simulate_retryable_failure": "",
            **payload,
        }
        return {**data, "payload": normalized_payload}


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
    tasks: list[PlannedTask]
    decisions: list[PlannedDecision]
    tool_calls: list[ToolCall]
