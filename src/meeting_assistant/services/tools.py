from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from meeting_assistant.db.models import ToolExecutionStatus
from meeting_assistant.schemas.planner import ToolCall
from meeting_assistant.repositories import Repository


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
    def execute(self, payload: dict[str, str]) -> dict[str, object]:
        ...


class EmailToolProvider:
    def execute(self, payload: dict[str, str]) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient email delivery failure.")
        return {
            "provider": "sendgrid",
            "delivery_status": "queued",
            "subject": payload.get("subject", ""),
        }


class CalendarToolProvider:
    def execute(self, payload: dict[str, str]) -> dict[str, object]:
        return {
            "provider": "google-calendar",
            "approval_required": True,
            "approval_request_id": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()[:12],
        }


class WebhookToolProvider:
    def execute(self, payload: dict[str, str]) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient webhook failure.")
        return {
            "provider": "webhook",
            "delivery_status": "accepted",
            "target": payload.get("target", "unknown"),
        }


@dataclass(slots=True)
class ToolExecutionOutcome:
    status: str
    result: dict[str, object]
    attempts: int
    idempotency_key: str
    reused: bool = False


class ToolExecutor:
    def __init__(
        self,
        repository: Repository,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.repository = repository
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleep_fn = sleep_fn or time.sleep
        self.providers: dict[str, ToolProvider] = {
            "email.send": EmailToolProvider(),
            "calendar.create_event": CalendarToolProvider(),
            "slack.notify": WebhookToolProvider(),
            "jira.create_issue": WebhookToolProvider(),
        }

    def execute(self, workflow_run_id: int, tool_call: ToolCall) -> ToolExecutionOutcome:
        payload_blob = json.dumps(tool_call.payload, sort_keys=True)
        idempotency_key = hashlib.sha256(f"{tool_call.tool_name}:{payload_blob}".encode()).hexdigest()

        existing = self.repository.get_tool_execution(workflow_run_id, idempotency_key)
        if existing is not None and existing.status in {
            ToolExecutionStatus.EXECUTED,
            ToolExecutionStatus.APPROVAL_REQUIRED,
            ToolExecutionStatus.SKIPPED,
        }:
            attempts = self._attempt_count(existing.id)
            existing_result = json.loads(existing.result) if existing.result else None
            return ToolExecutionOutcome(
                status=existing.status.value,
                result=existing_result or {},
                attempts=attempts,
                idempotency_key=idempotency_key,
                reused=True,
            )

        execution = self.repository.create_tool_execution(
            workflow_run_id=workflow_run_id,
            tool_name=tool_call.tool_name,
            payload=payload_blob,
            idempotency_key=idempotency_key,
            status=ToolExecutionStatus.PENDING.value,
            result=json.dumps({"state": "pending"}),
        )

        provider = self.providers.get(tool_call.tool_name)
        if provider is None:
            result = {"error": f"Unsupported tool: {tool_call.tool_name}", "dlq": True}
            self.repository.create_tool_execution_attempt(
                execution.id, 1, ToolExecutionStatus.FAILED.value, None, result["error"]
            )
            self.repository.update_tool_execution(
                execution.id,
                status=ToolExecutionStatus.FAILED,
                result=json.dumps(result),
            )
            return ToolExecutionOutcome(
                status=ToolExecutionStatus.FAILED.value,
                result=result,
                attempts=1,
                idempotency_key=idempotency_key,
            )

        last_error: str | None = None
        for attempt_number in range(1, self.max_retries + 1):
            try:
                provider_result = provider.execute(tool_call.payload)
                if provider_result.get("approval_required"):
                    result = {
                        "message": "Calendar action requires human approval.",
                        **provider_result,
                    }
                    self.repository.create_tool_execution_attempt(
                        execution.id,
                        attempt_number,
                        ToolExecutionStatus.APPROVAL_REQUIRED.value,
                        json.dumps(result),
                        None,
                    )
                    self.repository.update_tool_execution(
                        execution.id,
                        status=ToolExecutionStatus.APPROVAL_REQUIRED,
                        result=json.dumps(result),
                    )
                    return ToolExecutionOutcome(
                        status=ToolExecutionStatus.APPROVAL_REQUIRED.value,
                        result=result,
                        attempts=attempt_number,
                        idempotency_key=idempotency_key,
                    )

                result = {"message": f"Executed {tool_call.tool_name}", **provider_result}
                self.repository.create_tool_execution_attempt(
                    execution.id,
                    attempt_number,
                    ToolExecutionStatus.EXECUTED.value,
                    json.dumps(result),
                    None,
                )
                self.repository.update_tool_execution(
                    execution.id,
                    status=ToolExecutionStatus.EXECUTED,
                    result=json.dumps(result),
                )
                return ToolExecutionOutcome(
                    status=ToolExecutionStatus.EXECUTED.value,
                    result=result,
                    attempts=attempt_number,
                    idempotency_key=idempotency_key,
                )
            except RetryableToolError as exc:
                last_error = str(exc)
                self.repository.create_tool_execution_attempt(
                    execution.id,
                    attempt_number,
                    ToolExecutionStatus.FAILED.value,
                    None,
                    last_error,
                )
                if attempt_number < self.max_retries:
                    self.sleep_fn(self.backoff_seconds * (2 ** (attempt_number - 1)))
                    continue

        failure_result = {
            "error": last_error or "Tool execution failed.",
            "dlq": True,
            "max_retries": self.max_retries,
        }
        self.repository.update_tool_execution(
            execution.id,
            status=ToolExecutionStatus.FAILED,
            result=json.dumps(failure_result),
        )
        return ToolExecutionOutcome(
            status=ToolExecutionStatus.FAILED.value,
            result=failure_result,
            attempts=self.max_retries,
            idempotency_key=idempotency_key,
        )

    def _attempt_count(self, execution_id: int) -> int:
        return self.repository.count_tool_execution_attempts(execution_id)
