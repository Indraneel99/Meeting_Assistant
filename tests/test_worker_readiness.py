from unittest.mock import patch

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.services.worker_readiness import arq_health_check_key, check_worker_health


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


def test_ready_skips_worker_check_for_pubsub_mode() -> None:
    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        pubsub_topic="meeting-assistant-batch-jobs",
        pubsub_project="test-project",
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=True,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["checks"]["worker"] == "skipped"
        assert payload["details"]["worker"] == "pubsub push worker"


def test_check_worker_health_skips_pubsub_without_redis() -> None:
    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        readiness_check_worker=True,
    )
    status, detail = check_worker_health(settings)
    assert status == "skipped"
    assert detail == "pubsub push worker"


def test_worker_app_ready_pubsub_checks_database_only() -> None:
    from meeting_assistant.worker_app import create_worker_app

    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        pubsub_topic="meeting-assistant-batch-jobs",
        pubsub_project="test-project",
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=True,
    )
    with TestClient(create_worker_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["checks"]["database"] == "ok"
        assert payload["checks"]["worker"] == "skipped"
        assert payload["details"]["worker"] == "pubsub push worker"
        assert "redis" not in payload["checks"]
        assert payload["checks"]["embedder"] == "skipped"


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
