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


def check_worker_health(settings: Settings) -> tuple[str, str | None]:
    """Readiness worker probe: ARQ heartbeat in Redis, or skipped for Pub/Sub push workers."""
    if not settings.readiness_check_worker:
        return "skipped", None
    if settings.batch_processing_mode != "async":
        return "skipped", None
    if settings.job_queue_provider == "pubsub":
        return "skipped", "pubsub push worker"
    if settings.job_queue_provider != "arq":
        return "skipped", None
    return check_arq_worker_health(settings)
