from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


def _jwt_settings(**overrides: object) -> Settings:
    defaults = {
        "auth_enabled": True,
        "auth_mode": "jwt",
        "auth_jwt_secret": "jwt-test-secret-key-with-32-bytes-minimum",
        "auth_jwt_algorithm": "HS256",
        "auth_jwt_expiry_seconds": 3600,
        "readiness_check_redis": False,
        "readiness_check_embedder": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_auth_config_reports_login_modes() -> None:
    with TestClient(create_app(_jwt_settings(auth_login_allow_dev=True))) as client:
        response = client.get("/api/v1/auth/config")
        assert response.status_code == 200
        payload = response.json()
        assert payload["auth_enabled"] is True
        assert payload["login_allow_dev"] is True


def test_login_with_scoped_api_key_returns_jwt() -> None:
    user_external_id = f"user-{uuid4()}"
    settings = _jwt_settings(
        auth_mode="api_key",
        auth_api_keys=f"{user_external_id}:login-secret",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"api_key": "login-secret", "user_email": f"{user_external_id}@example.com"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["token_type"] == "bearer"
        assert payload["user_external_id"] == user_external_id
        assert payload["expires_in"] == 3600

        decoded = jwt.decode(
            payload["access_token"],
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
        )
        assert decoded["sub"] == user_external_id

        batch = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
                "title": "JWT login test",
                "transcript_text": "Decision: verify jwt login.",
            },
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        assert batch.status_code == 200


def test_login_with_dev_credentials_when_enabled() -> None:
    user_external_id = f"dev-{uuid4()}"
    settings = _jwt_settings(auth_login_allow_dev=True)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
            },
        )
        assert response.status_code == 200
        assert response.json()["user_external_id"] == user_external_id


def test_login_rejects_dev_credentials_when_disabled() -> None:
    settings = _jwt_settings(auth_login_allow_dev=False)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"user_external_id": "alice", "user_email": "alice@example.com"},
        )
        assert response.status_code == 401


def test_auth_me_returns_session_for_bearer_token() -> None:
    user_external_id = f"user-{uuid4()}"
    settings = _jwt_settings(auth_login_allow_dev=True)
    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
            },
        )
        token = login.json()["access_token"]

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        payload = me.json()
        assert payload["user_external_id"] == user_external_id
        assert payload["auth_type"] == "jwt"


def test_bearer_token_works_when_auth_mode_is_api_key() -> None:
    user_external_id = f"user-{uuid4()}"
    settings = _jwt_settings(
        auth_mode="api_key",
        auth_api_keys=f"{user_external_id}:legacy-secret",
        auth_login_allow_dev=True,
    )
    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
            },
        )
        token = login.json()["access_token"]

        batch = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
                "title": "Hybrid auth",
                "transcript_text": "Decision: hybrid auth works.",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert batch.status_code == 200
