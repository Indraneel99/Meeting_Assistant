from __future__ import annotations

from uuid import uuid4

import httpx
import jwt
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.services.integrations.oauth_state import issue_google_login_state


def _google_auth_settings(**overrides: object) -> Settings:
    defaults = {
        "auth_enabled": True,
        "auth_mode": "jwt",
        "auth_jwt_secret": "jwt-test-secret-key-with-32-bytes-minimum",
        "auth_jwt_algorithm": "HS256",
        "auth_jwt_expiry_seconds": 3600,
        "auth_google_login_enabled": True,
        "auth_google_login_client_id": "google-login-client-id",
        "auth_google_login_client_secret": "google-login-client-secret",
        "auth_google_login_redirect_base": "http://testserver",
        "readiness_check_redis": False,
        "readiness_check_embedder": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _mock_google_oauth(*, sub: str, email: str, name: str = "Google User") -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "access_token": "google-access-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if request.url.host == "www.googleapis.com":
            return httpx.Response(
                200,
                json={"sub": sub, "email": email, "name": name},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    httpx.post = httpx.Client(transport=transport).post  # type: ignore[method-assign]
    httpx.get = httpx.Client(transport=transport).get  # type: ignore[method-assign]


def test_google_connect_returns_authorize_url(monkeypatch) -> None:
    settings = _google_auth_settings()
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/v1/auth/google/connect",
            params={"frontend_redirect": "http://localhost:5173/login"},
        )
        assert response.status_code == 200
        authorize_url = response.json()["authorize_url"]
        assert "accounts.google.com/o/oauth2/v2/auth" in authorize_url
        assert "client_id=google-login-client-id" in authorize_url
        assert "scope=openid+email+profile" in authorize_url


def test_google_callback_creates_user_and_redirects_with_token(monkeypatch) -> None:
    settings = _google_auth_settings()
    google_sub = f"google-{uuid4()}"
    email = f"google-user-{uuid4()}@example.com"
    frontend_redirect = "http://localhost:5173/login"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json={"sub": google_sub, "email": email, "name": "G User"})
        return httpx.Response(404)

    client_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "post", client_transport.post)
    monkeypatch.setattr(httpx, "get", client_transport.get)

    state = issue_google_login_state(settings, frontend_redirect=frontend_redirect)

    with TestClient(create_app(settings), follow_redirects=False) as client:
        response = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "auth-code", "state": state},
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith(f"{frontend_redirect}#")
        assert "access_token=" in location
        assert "token_type=bearer" in location

        token = location.split("access_token=")[1].split("&")[0]
        decoded = jwt.decode(token, settings.auth_jwt_secret, algorithms=[settings.auth_jwt_algorithm])
        assert decoded["sub"].startswith("usr_")

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["user_email"] == email.lower()


def test_google_callback_links_existing_email_user(monkeypatch) -> None:
    settings = _google_auth_settings(auth_password_login_enabled=True)
    email = f"linked-{uuid4()}@example.com"
    password = "secure-pass-123"
    google_sub = f"google-{uuid4()}"
    frontend_redirect = "http://localhost:5173/login"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json={"sub": google_sub, "email": email})
        return httpx.Response(404)

    client_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "post", client_transport.post)
    monkeypatch.setattr(httpx, "get", client_transport.get)

    with TestClient(create_app(settings), follow_redirects=False) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert register.status_code == 200
        existing_external_id = register.json()["user_external_id"]

        state = issue_google_login_state(settings, frontend_redirect=frontend_redirect)
        callback = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "auth-code", "state": state},
        )
        assert callback.status_code == 302
        location = callback.headers["location"]
        assert f"user_external_id={existing_external_id}" in location


def test_google_connect_disabled_when_flag_off() -> None:
    settings = _google_auth_settings(auth_google_login_enabled=False)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/auth/google/connect")
        assert response.status_code == 403
