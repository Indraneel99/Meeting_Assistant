from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


def _auth_settings(**overrides: object) -> Settings:
    defaults = {
        "auth_enabled": True,
        "auth_mode": "jwt",
        "auth_jwt_secret": "jwt-test-secret-key-with-32-bytes-minimum",
        "auth_jwt_algorithm": "HS256",
        "auth_jwt_expiry_seconds": 3600,
        "auth_password_login_enabled": True,
        "readiness_check_redis": False,
        "readiness_check_embedder": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_register_and_login_email_returns_jwt() -> None:
    email = f"alice-{uuid4()}@example.com"
    password = "secure-pass-123"
    settings = _auth_settings()

    with TestClient(create_app(settings)) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": "Alice"},
        )
        assert register.status_code == 200
        register_payload = register.json()
        assert register_payload["user_email"] == email.lower()
        assert register_payload["token_type"] == "bearer"
        assert register_payload["user_external_id"].startswith("usr_")

        decoded = jwt.decode(
            register_payload["access_token"],
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
        )
        assert decoded["sub"] == register_payload["user_external_id"]

        login = client.post(
            "/api/v1/auth/login/email",
            json={"email": email.upper(), "password": password},
        )
        assert login.status_code == 200
        assert login.json()["user_external_id"] == register_payload["user_external_id"]

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["user_email"] == email.lower()


def test_register_rejects_duplicate_email() -> None:
    email = f"bob-{uuid4()}@example.com"
    password = "secure-pass-123"

    with TestClient(create_app(_auth_settings())) as client:
        first = client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert first.status_code == 200

        second = client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert second.status_code == 409


def test_register_rejects_weak_password() -> None:
    email = f"carol-{uuid4()}@example.com"

    with TestClient(create_app(_auth_settings())) as client:
        response = client.post("/api/v1/auth/register", json={"email": email, "password": "short"})
        assert response.status_code == 422


def test_login_email_rejects_invalid_credentials() -> None:
    email = f"dana-{uuid4()}@example.com"
    password = "secure-pass-123"

    with TestClient(create_app(_auth_settings())) as client:
        client.post("/api/v1/auth/register", json={"email": email, "password": password})

        wrong_password = client.post(
            "/api/v1/auth/login/email",
            json={"email": email, "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401

        unknown_email = client.post(
            "/api/v1/auth/login/email",
            json={"email": f"missing-{uuid4()}@example.com", "password": password},
        )
        assert unknown_email.status_code == 401


def test_password_login_disabled_when_flag_off() -> None:
    email = f"eve-{uuid4()}@example.com"
    settings = _auth_settings(auth_password_login_enabled=False)

    with TestClient(create_app(settings)) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "secure-pass-123"},
        )
        assert register.status_code == 403

        login = client.post(
            "/api/v1/auth/login/email",
            json={"email": email, "password": "secure-pass-123"},
        )
        assert login.status_code == 403


def test_auth_config_exposes_password_and_google_login_flags() -> None:
    settings = _auth_settings(
        auth_password_login_enabled=True,
        auth_google_login_enabled=True,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/auth/config")
        assert response.status_code == 200
        payload = response.json()
        assert payload["password_login_enabled"] is True
        assert payload["google_login_enabled"] is True


def test_register_rate_limit_returns_429_when_exceeded() -> None:
    settings = _auth_settings(
        rate_limit_enabled=True,
        auth_rate_limit_register="2/minute",
    )
    email_base = f"rate-{uuid4()}"

    with TestClient(create_app(settings)) as client:
        for index in range(2):
            response = client.post(
                "/api/v1/auth/register",
                json={"email": f"{email_base}-{index}@example.com", "password": "secure-pass-123"},
            )
            assert response.status_code == 200

        blocked = client.post(
            "/api/v1/auth/register",
            json={"email": f"{email_base}-blocked@example.com", "password": "secure-pass-123"},
        )
        assert blocked.status_code == 429
