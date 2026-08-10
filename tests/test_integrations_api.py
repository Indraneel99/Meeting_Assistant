from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


def _integration_settings(**overrides: object) -> Settings:
    defaults = {
        "integrations_oauth_redirect_base": "http://testserver",
        "readiness_check_redis": False,
        "readiness_check_embedder": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _auth_settings(**overrides: object) -> Settings:
    return _integration_settings(
        auth_enabled=True,
        auth_mode="api_key",
        auth_api_keys="alice:alice-secret,bob:bob-secret",
        **overrides,
    )


def _ensure_user(client: TestClient, user_external_id: str, *, api_key: str | None = None) -> None:
    headers = {"X-API-Key": api_key} if api_key else {}
    response = client.post(
        "/api/v1/meetings/batch",
        json={
            "user_external_id": user_external_id,
            "user_email": f"{user_external_id}@example.com",
            "title": "Integration bootstrap",
            "transcript_text": "Decision: connect integrations.",
        },
        headers=headers,
    )
    assert response.status_code == 200


def test_list_integrations_empty_when_auth_disabled() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        response = client.get("/api/v1/integrations", params={"user_external_id": user_external_id})
        assert response.status_code == 200
        assert response.json()["integrations"] == []


def test_email_prefs_connects_without_oauth() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        connect = client.get(
            "/api/v1/integrations/email_prefs/connect",
            params={"user_external_id": user_external_id},
        )
        assert connect.status_code == 200
        payload = connect.json()
        assert payload["status"] == "connected"
        assert payload["authorize_url"] is None

        listed = client.get("/api/v1/integrations", params={"user_external_id": user_external_id})
        assert listed.status_code == 200
        integrations = listed.json()["integrations"]
        assert len(integrations) == 1
        assert integrations[0]["provider"] == "email_prefs"
        assert integrations[0]["status"] == "connected"
        assert "access_token" not in integrations[0]
        assert "refresh_token" not in integrations[0]


def test_stub_slack_oauth_callback_stores_encrypted_tokens_without_api_key() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        connect = client.get(
            "/api/v1/integrations/slack/connect",
            params={"user_external_id": user_external_id},
        )
        assert connect.status_code == 200
        authorize_url = connect.json()["authorize_url"]
        assert authorize_url is not None

        callback = client.get(authorize_url, follow_redirects=False)
        assert callback.status_code == 200
        payload = callback.json()
        assert payload["provider"] == "slack"
        assert payload["status"] == "connected"
        assert payload["provider_account_id"] == "T-STUB"
        assert "access_token" not in payload

        listed = client.get("/api/v1/integrations", params={"user_external_id": user_external_id})
        slack = listed.json()["integrations"][0]
        assert slack["provider"] == "slack"
        assert slack["provider_account_id"] == "T-STUB"


def test_oauth_callback_redirects_to_frontend_when_configured() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        connect = client.get(
            "/api/v1/integrations/slack/connect",
            params={
                "user_external_id": user_external_id,
                "frontend_redirect": "http://localhost:5173/settings/integrations",
            },
        )
        authorize_url = connect.json()["authorize_url"]
        callback = client.get(authorize_url, follow_redirects=False)
        assert callback.status_code == 302
        location = callback.headers["location"]
        assert location.startswith("http://localhost:5173/settings/integrations")
        assert "provider=slack" in location
        assert "status=connected" in location


def test_update_settings_and_list_options() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        client.get(
            "/api/v1/integrations/slack/connect",
            params={"user_external_id": user_external_id},
        )
        callback = client.get(
            client.get(
                "/api/v1/integrations/slack/connect",
                params={"user_external_id": user_external_id},
            ).json()["authorize_url"]
        )
        provider_account_id = callback.json()["provider_account_id"]

        patch = client.patch(
            "/api/v1/integrations/slack/settings",
            params={"user_external_id": user_external_id, "provider_account_id": provider_account_id},
            json={"settings_json": {"channels": ["#product"]}},
        )
        assert patch.status_code == 200
        assert patch.json()["settings_json"] == {"channels": ["#product"]}

        options = client.get(
            "/api/v1/integrations/slack/options",
            params={"user_external_id": user_external_id, "provider_account_id": provider_account_id},
        )
        assert options.status_code == 200
        assert len(options.json()["options"]) >= 1


def test_disconnect_revokes_integration() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        authorize_url = client.get(
            "/api/v1/integrations/slack/connect",
            params={"user_external_id": user_external_id},
        ).json()["authorize_url"]
        provider_account_id = client.get(authorize_url).json()["provider_account_id"]

        deleted = client.delete(
            "/api/v1/integrations/slack",
            params={"user_external_id": user_external_id, "provider_account_id": provider_account_id},
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "revoked"


def test_scoped_api_key_required_when_auth_enabled() -> None:
    with TestClient(create_app(_auth_settings())) as client:
        response = client.get("/api/v1/integrations", params={"user_external_id": "alice"})
        assert response.status_code == 401


def test_scoped_api_key_limits_integrations_to_owner() -> None:
    with TestClient(create_app(_auth_settings())) as client:
        _ensure_user(client, "alice", api_key="alice-secret")
        _ensure_user(client, "bob", api_key="bob-secret")

        alice_list = client.get("/api/v1/integrations", headers={"X-API-Key": "alice-secret"})
        assert alice_list.status_code == 200

        bob_list = client.get(
            "/api/v1/integrations",
            params={"user_external_id": "alice"},
            headers={"X-API-Key": "bob-secret"},
        )
        assert bob_list.status_code == 403


def test_oauth_callback_rejects_invalid_state() -> None:
    with TestClient(create_app(_integration_settings())) as client:
        response = client.get(
            "/api/v1/integrations/slack/callback",
            params={"code": "stub-oauth-code", "state": "invalid-state"},
        )
        assert response.status_code == 400


def test_unknown_provider_returns_404() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app(_integration_settings())) as client:
        _ensure_user(client, user_external_id)
        response = client.get(
            "/api/v1/integrations/unknown/connect",
            params={"user_external_id": user_external_id},
        )
        assert response.status_code == 404
