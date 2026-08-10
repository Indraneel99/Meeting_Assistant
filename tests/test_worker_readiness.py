from unittest.mock import patch

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.services.worker_readiness import arq_health_check_key


def test_ready_skips_worker_check_for_sync_batch_mode() -> None:
    settings = Settings(
        batch_processing_mode="sync",
        job_queue_provider="arq",
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=True,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["worker"] == "skipped"


def test_ready_reports_worker_ok_when_arq_heartbeat_present() -> None:
    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="arq",
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=True,
    )
    heartbeat = "Jul-26 14:00:00 j_complete=1 j_failed=0 j_retried=0 j_ongoing=0 queued=0"

    class FakeRedis:
        def get(self, key: str) -> str | None:
            assert key == arq_health_check_key(settings)
            return heartbeat

    with patch("meeting_assistant.services.worker_readiness.redis_from_url", return_value=FakeRedis()):
        with TestClient(create_app(settings)) as client:
            response = client.get("/ready")
            assert response.status_code == 200
            payload = response.json()
            assert payload["checks"]["worker"] == "ok"
            assert payload["details"]["worker"] == heartbeat


def test_ready_reports_degraded_when_worker_heartbeat_missing() -> None:
    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="arq",
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=True,
    )

    class FakeRedis:
        def get(self, key: str) -> None:
            return None

    with patch("meeting_assistant.services.worker_readiness.redis_from_url", return_value=FakeRedis()):
        with TestClient(create_app(settings)) as client:
            response = client.get("/ready")
            assert response.status_code == 503
            payload = response.json()
            assert payload["status"] == "degraded"
            assert payload["checks"]["worker"] == "error"
            assert payload["details"]["worker"] == "no arq worker heartbeat"
