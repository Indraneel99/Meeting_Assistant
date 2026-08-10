from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text

from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.services.worker_readiness import check_arq_worker_health


@dataclass(slots=True)
class ReadinessReport:
    status: str
    checks: dict[str, str]
    details: dict[str, str] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return all(value in {"ok", "skipped"} for value in self.checks.values())


def _check_database(container: Container) -> str:
    try:
        with container.repository.session_factory() as session:
            session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def _check_redis(settings: Settings) -> str:
    if settings.queue_provider != "redis" and settings.job_queue_provider != "arq":
        return "skipped"

    try:
        from meeting_assistant.services.redis_client import redis_from_url

        client = redis_from_url(settings.redis_url)
        client.ping()
        return "ok"
    except Exception:
        return "error"


def _check_embedder(container: Container, settings: Settings) -> str:
    if not settings.readiness_check_embedder:
        return "skipped"

    try:
        vector = container.query_service.embedding_index.embed("readiness probe")
        return "ok" if vector else "error"
    except Exception:
        return "error"


def build_readiness_report(container: Container, settings: Settings) -> ReadinessReport:
    checks = {
        "database": _check_database(container),
    }
    details: dict[str, str] = {}
    if settings.readiness_check_redis:
        checks["redis"] = _check_redis(settings)
    if settings.readiness_check_worker:
        worker_status, worker_detail = check_arq_worker_health(settings)
        checks["worker"] = worker_status
        if worker_detail:
            details["worker"] = worker_detail
    checks["embedder"] = _check_embedder(container, settings)

    status = "ready" if all(value in {"ok", "skipped"} for value in checks.values()) else "degraded"
    return ReadinessReport(status=status, checks=checks, details=details)
