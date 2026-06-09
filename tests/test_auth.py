from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


def _batch_payload(user_external_id: str) -> dict[str, str]:
    return {
        "user_external_id": user_external_id,
        "user_email": f"{user_external_id}@example.com",
        "title": "Auth test meeting",
        "transcript_text": "Decision: test auth. Please email the team.",
    }


def test_api_key_required_when_auth_enabled() -> None:
    settings = Settings(auth_enabled=True, auth_mode="api_key", auth_api_keys="alice:test-secret")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/meetings/batch", json=_batch_payload("alice"))
        assert response.status_code == 401


def test_scoped_api_key_allows_matching_user() -> None:
    settings = Settings(auth_enabled=True, auth_mode="api_key", auth_api_keys="alice:test-secret")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload("alice"),
            headers={"X-API-Key": "test-secret"},
        )
        assert response.status_code == 200


def test_scoped_api_key_rejects_other_user() -> None:
    settings = Settings(auth_enabled=True, auth_mode="api_key", auth_api_keys="alice:test-secret")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload("bob"),
            headers={"X-API-Key": "test-secret"},
        )
        assert response.status_code == 403


def test_jwt_auth_scopes_user_external_id() -> None:
    secret = "jwt-test-secret-key-with-32-bytes-minimum"
    user_external_id = f"user-{uuid4()}"
    token = jwt.encode({"sub": user_external_id}, secret, algorithm="HS256")
    settings = Settings(
        auth_enabled=True,
        auth_mode="jwt",
        auth_jwt_secret=secret,
        auth_jwt_algorithm="HS256",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload(user_external_id),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
