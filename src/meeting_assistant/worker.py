from __future__ import annotations

from typing import Any

from meeting_assistant.bootstrap import bootstrap_container
from meeting_assistant.schemas.batch import BatchMeetingRequest


from arq.connections import RedisSettings

from meeting_assistant.core.config import Settings

_settings = Settings()


async def process_batch_workflow(_ctx: dict[str, Any], workflow_run_id: int, payload: dict[str, Any]) -> None:
    container = bootstrap_container()
    container.orchestrator.run_batch_workflow(
        workflow_run_id=workflow_run_id,
        payload=BatchMeetingRequest.model_validate(payload),
    )


class WorkerSettings:
    functions = [process_batch_workflow]
    job_timeout = 3600
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
