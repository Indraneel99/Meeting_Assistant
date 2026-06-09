from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings


@dataclass(slots=True)
class ReadinessReport:
    status: str
    checks: dict[str, str]

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
        import redis

        client = redis.from_url(settings.redis_url)
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
    if settings.readiness_check_redis:
        checks["redis"] = _check_redis(settings)
    checks["embedder"] = _check_embedder(container, settings)

    status = "ready" if all(value in {"ok", "skipped"} for value in checks.values()) else "degraded"
    return ReadinessReport(status=status, checks=checks)
