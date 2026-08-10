from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from meeting_assistant.core.config import Settings
from meeting_assistant.core.logging import get_logger
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.ops import FailedToolAlertResponse, FailedToolItem

logger = get_logger("meeting_assistant.ops")


def _parse_failure_result(result: str | None) -> tuple[bool, str | None]:
    if not result:
        return False, None
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return False, None
    if not isinstance(payload, dict):
        return False, None
    dlq = bool(payload.get("dlq"))
    error = payload.get("error")
    return dlq, str(error) if error is not None else None


class FailedToolMonitor:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def check_and_alert(self) -> FailedToolAlertResponse:
        lookback_minutes = self.settings.failed_tool_alert_lookback_minutes
        max_retries = self.settings.tool_execution_max_retries
        if not self.settings.failed_tool_alert_enabled:
            return FailedToolAlertResponse(
                enabled=False,
                lookback_minutes=lookback_minutes,
                max_retries=max_retries,
                count=0,
            )

        since = datetime.now(UTC) - timedelta(minutes=lookback_minutes)
        records = self.repository.list_failed_tool_executions(since=since)
        items: list[FailedToolItem] = []
        for record in records:
            dlq, error_message = _parse_failure_result(record.result)
            retry_exhausted = record.attempt_count >= max_retries
            item = FailedToolItem(
                tool_execution_id=record.tool_execution_id,
                workflow_run_id=record.workflow_run_id,
                meeting_id=record.meeting_id,
                user_external_id=record.user_external_id,
                tool_name=record.tool_name,
                status=record.status,
                attempt_count=record.attempt_count,
                max_retries=max_retries,
                dlq=dlq,
                error_message=error_message,
                last_attempt_at=record.last_attempt_at,
            )
            items.append(item)
            logger.warning(
                "failed_tool_detected",
                alert_event="failed_tool_alert",
                tool_execution_id=item.tool_execution_id,
                workflow_run_id=item.workflow_run_id,
                meeting_id=item.meeting_id,
                user_external_id=item.user_external_id,
                tool_name=item.tool_name,
                attempt_count=item.attempt_count,
                max_retries=max_retries,
                dlq=item.dlq,
                retry_exhausted=retry_exhausted,
                error_message=item.error_message,
                lookback_minutes=lookback_minutes,
            )

        return FailedToolAlertResponse(
            enabled=True,
            lookback_minutes=lookback_minutes,
            max_retries=max_retries,
            count=len(items),
            executions=items,
        )
