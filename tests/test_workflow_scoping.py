from uuid import uuid4

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings

CALENDAR_TRANSCRIPT = (
    "Decision: ship the batch pipeline first. "
    "Action: prepare the launch checklist. "
    "Please email the summary to the team. "
    "Schedule a calendar follow-up next Tuesday."
)


def _auth_settings() -> Settings:
    return Settings(
        auth_enabled=True,
        auth_mode="api_key",
        auth_api_keys="alice:alice-secret,bob:bob-secret",
    )


def _create_awaiting_approval_workflow(client: TestClient, user_external_id: str) -> tuple[int, int]:
    ingest = client.post(
        "/api/v1/meetings/batch",
        json={
            "user_external_id": user_external_id,
            "user_email": f"{user_external_id}@example.com",
            "title": "Scoped workflow test",
            "transcript_text": CALENDAR_TRANSCRIPT,
        },
        headers={"X-API-Key": f"{user_external_id}-secret"},
    )
    assert ingest.status_code == 200
    payload = ingest.json()
    assert payload["status"] == "awaiting_approval"
    workflow_run_id = payload["workflow_run_id"]

    approvals = client.get(
        f"/api/v1/workflows/{workflow_run_id}/approvals",
        headers={"X-API-Key": f"{user_external_id}-secret"},
    )
    assert approvals.status_code == 200
    approval_request_id = approvals.json()[0]["approval_request_id"]
    return workflow_run_id, approval_request_id


def test_owner_can_access_workflow_and_approvals() -> None:
    with TestClient(create_app(_auth_settings())) as client:
        workflow_run_id, approval_request_id = _create_awaiting_approval_workflow(client, "alice")

        workflow = client.get(
            f"/api/v1/workflows/{workflow_run_id}",
            headers={"X-API-Key": "alice-secret"},
        )
        assert workflow.status_code == 200
        assert workflow.json()["workflow_run_id"] == workflow_run_id

        approvals = client.get(
            f"/api/v1/workflows/{workflow_run_id}/approvals",
            headers={"X-API-Key": "alice-secret"},
        )
        assert approvals.status_code == 200
        assert approvals.json()[0]["approval_request_id"] == approval_request_id


def test_other_user_cannot_access_workflow_or_approvals() -> None:
    with TestClient(create_app(_auth_settings())) as client:
        workflow_run_id, approval_request_id = _create_awaiting_approval_workflow(client, "alice")

        workflow = client.get(
            f"/api/v1/workflows/{workflow_run_id}",
            headers={"X-API-Key": "bob-secret"},
        )
        assert workflow.status_code == 403

        approvals = client.get(
            f"/api/v1/workflows/{workflow_run_id}/approvals",
            headers={"X-API-Key": "bob-secret"},
        )
        assert approvals.status_code == 403

        approve = client.post(
            f"/api/v1/approvals/{approval_request_id}/approve",
            headers={"X-API-Key": "bob-secret"},
            json={"resolved_by": "bob"},
        )
        assert approve.status_code == 403


def test_missing_workflow_returns_404_before_scope_check() -> None:
    with TestClient(create_app(_auth_settings())) as client:
        response = client.get(
            "/api/v1/workflows/999999",
            headers={"X-API-Key": "alice-secret"},
        )
        assert response.status_code == 404


def test_unscoped_api_key_can_access_any_workflow_when_auth_enabled() -> None:
    settings = Settings(
        auth_enabled=True,
        auth_mode="api_key",
        auth_api_keys="admin-key,alice:alice-secret",
    )
    with TestClient(create_app(settings)) as client:
        workflow_run_id, _ = _create_awaiting_approval_workflow(client, "alice")

        workflow = client.get(
            f"/api/v1/workflows/{workflow_run_id}",
            headers={"X-API-Key": "admin-key"},
        )
        assert workflow.status_code == 200


def test_workflow_scoping_disabled_when_auth_disabled() -> None:
    user_external_id = f"user-{uuid4()}"
    with TestClient(create_app()) as client:
        ingest = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
                "title": "No auth scope test",
                "transcript_text": CALENDAR_TRANSCRIPT,
            },
        )
        workflow_run_id = ingest.json()["workflow_run_id"]

        workflow = client.get(f"/api/v1/workflows/{workflow_run_id}")
        assert workflow.status_code == 200
