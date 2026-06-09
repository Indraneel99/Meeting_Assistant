from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


def test_ready_endpoint_reports_database_ok() -> None:
    settings = Settings(readiness_check_redis=False, readiness_check_embedder=False)
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["checks"]["database"] == "ok"
