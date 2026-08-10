from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings
from arq.constants import default_queue_name

from meeting_assistant.bootstrap import bootstrap_container
from meeting_assistant.core.config import Settings
from meeting_assistant.core.telemetry import attach_trace_context, configure_telemetry, pop_trace_context
from meeting_assistant.schemas.batch import BatchMeetingRequest

_settings = Settings()
configure_telemetry(_settings)


async def process_batch_workflow(_ctx: dict[str, Any], workflow_run_id: int, payload: dict[str, Any]) -> None:
    job_payload = dict(payload)
    parent_context = pop_trace_context(job_payload)
    with attach_trace_context(parent_context):
        container = bootstrap_container()
        container.orchestrator.run_batch_workflow(
            workflow_run_id=workflow_run_id,
            payload=BatchMeetingRequest.model_validate(job_payload),
        )


class WorkerSettings:
    functions = [process_batch_workflow]
    job_timeout = 3600
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    queue_name = _settings.arq_queue_name or default_queue_name
    health_check_interval = _settings.worker_health_check_interval_seconds
