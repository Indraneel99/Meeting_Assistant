from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


def test_ready_endpoint_reports_database_ok() -> None:
    settings = Settings(readiness_check_redis=False, readiness_check_embedder=False, readiness_check_worker=False)
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["checks"]["database"] == "ok"


def test_ready_pubsub_skips_arq_worker_check_even_when_enabled() -> None:
    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        pubsub_topic="jobs",
        pubsub_project="test-project",
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=True,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["checks"]["worker"] == "skipped"
        assert payload["details"]["worker"] == "pubsub push worker"
