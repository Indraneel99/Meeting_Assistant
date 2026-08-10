from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.api.rate_limit import limiter
from meeting_assistant.core.config import Settings


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    limiter.reset()
    yield
    limiter.reset()


def _batch_payload(user_external_id: str) -> dict[str, str]:
    return {
        "user_external_id": user_external_id,
        "user_email": f"{user_external_id}@example.com",
        "title": "Rate limit test",
        "transcript_text": "Decision: test rate limits.",
    }


def test_rate_limit_keys_by_scoped_api_key_not_client_ip() -> None:
    user_external_id = f"user-{uuid4()}"
    settings = Settings(
        auth_enabled=True,
        auth_mode="api_key",
        auth_api_keys=f"{user_external_id}:tenant-secret",
        rate_limit_enabled=True,
        rate_limit_default="100/minute",
        rate_limit_batch="2/minute",
        readiness_check_redis=False,
        readiness_check_embedder=False,
    )
    headers = {"X-API-Key": "tenant-secret"}

    with TestClient(create_app(settings)) as client:
        for index in range(2):
            response = client.post(
                "/api/v1/meetings/batch",
                json=_batch_payload(user_external_id),
                headers={**headers, "X-Forwarded-For": f"10.0.0.{index + 1}"},
            )
            assert response.status_code == 200

        blocked = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload(user_external_id),
            headers={**headers, "X-Forwarded-For": "10.0.0.99"},
        )
        assert blocked.status_code == 429


def test_different_api_keys_have_separate_rate_limit_buckets() -> None:
    alice = f"alice-{uuid4()}"
    bob = f"bob-{uuid4()}"
    settings = Settings(
        auth_enabled=True,
        auth_mode="api_key",
        auth_api_keys=f"{alice}:alice-secret,{bob}:bob-secret",
        rate_limit_enabled=True,
        rate_limit_batch="1/minute",
        readiness_check_redis=False,
        readiness_check_embedder=False,
    )

    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/meetings/batch",
                json=_batch_payload(alice),
                headers={"X-API-Key": "alice-secret"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/meetings/batch",
                json=_batch_payload(alice),
                headers={"X-API-Key": "alice-secret"},
            ).status_code
            == 429
        )
        assert (
            client.post(
                "/api/v1/meetings/batch",
                json=_batch_payload(bob),
                headers={"X-API-Key": "bob-secret"},
            ).status_code
            == 200
        )


def test_rate_limit_keys_by_jwt_subject() -> None:
    import jwt

    user_external_id = f"user-{uuid4()}"
    secret = "jwt-test-secret-key-with-32-bytes-minimum"
    token = jwt.encode({"sub": user_external_id}, secret, algorithm="HS256")
    settings = Settings(
        auth_enabled=True,
        auth_mode="jwt",
        auth_jwt_secret=secret,
        auth_jwt_algorithm="HS256",
        rate_limit_enabled=True,
        rate_limit_batch="2/minute",
        readiness_check_redis=False,
        readiness_check_embedder=False,
    )
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(create_app(settings)) as client:
        for index in range(2):
            response = client.post(
                "/api/v1/meetings/batch",
                json=_batch_payload(user_external_id),
                headers={**headers, "X-Forwarded-For": f"192.168.1.{index}"},
            )
            assert response.status_code == 200

        blocked = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload(user_external_id),
            headers={**headers, "X-Forwarded-For": "192.168.1.50"},
        )
        assert blocked.status_code == 429


def test_rate_limit_falls_back_to_ip_without_credentials() -> None:
    settings = Settings(
        auth_enabled=False,
        rate_limit_enabled=True,
        rate_limit_batch="2/minute",
        readiness_check_redis=False,
        readiness_check_embedder=False,
    )
    user_external_id = f"user-{uuid4()}"

    with TestClient(create_app(settings)) as client:
        same_ip_headers = {"X-Forwarded-For": "203.0.113.10"}
        for _ in range(2):
            assert (
                client.post(
                    "/api/v1/meetings/batch",
                    json=_batch_payload(user_external_id),
                    headers=same_ip_headers,
                ).status_code
                == 200
            )

        blocked = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload(user_external_id),
            headers=same_ip_headers,
        )
        assert blocked.status_code == 429

        other_ip = client.post(
            "/api/v1/meetings/batch",
            json=_batch_payload(user_external_id),
            headers={"X-Forwarded-For": "203.0.113.11"},
        )
        assert other_ip.status_code == 200
