from __future__ import annotations

from datetime import UTC, datetime, timedelta

from meeting_assistant.core.config import Settings
from meeting_assistant.core.logging import get_logger
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.ops import StaleWorkflowAlertResponse, StaleWorkflowItem

logger = get_logger("meeting_assistant.ops")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class StaleWorkflowMonitor:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def check_and_alert(self) -> StaleWorkflowAlertResponse:
        threshold_minutes = self.settings.stale_workflow_threshold_minutes
        if not self.settings.stale_workflow_alert_enabled:
            return StaleWorkflowAlertResponse(
                enabled=False,
                threshold_minutes=threshold_minutes,
                count=0,
            )

        cutoff = datetime.now(UTC) - timedelta(minutes=threshold_minutes)
        records = self.repository.list_stale_pending_workflows(older_than=cutoff)
        now = datetime.now(UTC)
        items: list[StaleWorkflowItem] = []
        for record in records:
            pending_minutes = max(0, int((_as_utc(now) - _as_utc(record.created_at)).total_seconds() // 60))
            item = StaleWorkflowItem(
                workflow_run_id=record.workflow_run_id,
                meeting_id=record.meeting_id,
                user_external_id=record.user_external_id,
                status=record.status,
                created_at=record.created_at,
                pending_minutes=pending_minutes,
            )
            items.append(item)
            logger.warning(
                "stale_workflow_detected",
                alert_event="stale_workflow_alert",
                workflow_run_id=item.workflow_run_id,
                meeting_id=item.meeting_id,
                user_external_id=item.user_external_id,
                pending_minutes=item.pending_minutes,
                threshold_minutes=threshold_minutes,
            )

        return StaleWorkflowAlertResponse(
            enabled=True,
            threshold_minutes=threshold_minutes,
            count=len(items),
            workflows=items,
        )
