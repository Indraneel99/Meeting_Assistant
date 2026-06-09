from uuid import uuid4

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app


def test_approval_resume_flow_completes_workflow() -> None:
    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"

    with TestClient(create_app()) as client:
        ingest = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Weekly product sync",
                "transcript_text": (
                    "Decision: ship the batch pipeline first. "
                    "Action: prepare the launch checklist. "
                    "Please email the summary to the team. "
                    "Schedule a calendar follow-up next Tuesday."
                ),
            },
        )
        assert ingest.status_code == 200
        workflow_run_id = ingest.json()["workflow_run_id"]
        assert ingest.json()["status"] == "awaiting_approval"

        approvals = client.get(f"/api/v1/workflows/{workflow_run_id}/approvals")
        assert approvals.status_code == 200
        pending = approvals.json()
        assert len(pending) == 1
        assert pending[0]["status"] == "pending"
        assert pending[0]["tool_name"] == "calendar.create_event"

        approval_request_id = pending[0]["approval_request_id"]
        approved = client.post(
            f"/api/v1/approvals/{approval_request_id}/approve",
            json={"resolved_by": "test-reviewer"},
        )
        assert approved.status_code == 200
        payload = approved.json()
        assert payload["approval_status"] == "approved"
        assert payload["tool_status"] == "executed"
        assert payload["workflow_status"] == "done"
        assert payload["tool_result"]["event_id"]

        workflow = client.get(f"/api/v1/workflows/{workflow_run_id}")
        assert workflow.status_code == 200
        assert workflow.json()["status"] == "done"
        tool_statuses = {item["status"] for item in workflow.json()["tool_executions"]}
        assert tool_statuses == {"executed"}


def test_reject_approval_skips_calendar_and_completes_workflow() -> None:
    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"

    with TestClient(create_app()) as client:
        ingest = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Planning sync",
                "transcript_text": (
                    "Decision: defer launch. "
                    "Please email the summary to the team. "
                    "Schedule a calendar follow-up next Tuesday."
                ),
            },
        )
        workflow_run_id = ingest.json()["workflow_run_id"]
        approval_request_id = client.get(f"/api/v1/workflows/{workflow_run_id}/approvals").json()[0][
            "approval_request_id"
        ]

        rejected = client.post(
            f"/api/v1/approvals/{approval_request_id}/reject",
            json={"resolved_by": "test-reviewer"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["tool_status"] == "skipped"
        assert rejected.json()["workflow_status"] == "done"

        workflow = client.get(f"/api/v1/workflows/{workflow_run_id}").json()
        assert workflow["status"] == "done"
        calendar = next(item for item in workflow["tool_executions"] if item["tool_name"] == "calendar.create_event")
        assert calendar["status"] == "skipped"


def test_double_approve_returns_conflict() -> None:
    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"

    with TestClient(create_app()) as client:
        ingest = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Conflict test",
                "transcript_text": "Please email the team. Schedule a calendar follow-up next Tuesday.",
            },
        )
        workflow_run_id = ingest.json()["workflow_run_id"]
        approval_request_id = client.get(f"/api/v1/workflows/{workflow_run_id}/approvals").json()[0][
            "approval_request_id"
        ]

        first = client.post(f"/api/v1/approvals/{approval_request_id}/approve", json={})
        assert first.status_code == 200
        second = client.post(f"/api/v1/approvals/{approval_request_id}/approve", json={})
        assert second.status_code == 409
