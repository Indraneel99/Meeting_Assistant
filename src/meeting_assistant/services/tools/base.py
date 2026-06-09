from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from meeting_assistant.schemas.planner import ToolCall


class ToolValidator:
    def validate(self, tool_calls: list[ToolCall], max_iterations: int = 10) -> list[ToolCall]:
        seen: set[tuple[str, str]] = set()
        validated: list[ToolCall] = []

        for tool_call in tool_calls[:max_iterations]:
            payload_blob = json.dumps(tool_call.payload, sort_keys=True)
            signature = (tool_call.tool_name, payload_blob)
            if signature in seen:
                continue
            seen.add(signature)
            validated.append(tool_call)

        return validated


class RetryableToolError(Exception):
    pass


class ToolProvider(Protocol):
    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        ...


class ApprovalGatedToolProvider(ToolProvider, Protocol):
    def execute_after_approval(
        self,
        payload: dict[str, str],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        ...


@dataclass(slots=True)
class ToolExecutionOutcome:
    status: str
    result: dict[str, object]
    attempts: int
    idempotency_key: str
    reused: bool = False
