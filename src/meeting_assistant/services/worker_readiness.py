from __future__ import annotations

from arq.constants import default_queue_name, health_check_key_suffix

from meeting_assistant.core.config import Settings
from meeting_assistant.services.redis_client import redis_from_url


def arq_health_check_key(settings: Settings) -> str:
    if settings.arq_health_check_key:
        return settings.arq_health_check_key
    queue_name = settings.arq_queue_name or default_queue_name
    return queue_name + health_check_key_suffix


def check_arq_worker_health(settings: Settings) -> tuple[str, str | None]:
    if settings.batch_processing_mode != "async" or settings.job_queue_provider != "arq":
        return "skipped", None
    if not settings.readiness_check_worker:
        return "skipped", None

    try:
        client = redis_from_url(settings.redis_url, decode_responses=True)
        key = arq_health_check_key(settings)
        value = client.get(key)
        if not value:
            return "error", "no arq worker heartbeat"
        return "ok", value
    except Exception:
        return "error", "worker heartbeat check failed"
