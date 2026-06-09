from uuid import uuid4

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app


def test_healthcheck() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_batch_ingestion_and_retrieval() -> None:
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
        payload = ingest.json()
        assert payload["status"] == "awaiting_approval"
        assert payload["tasks_created"] >= 1
        assert payload["decisions_logged"] >= 1
        assert payload["iterations_used"] >= 1
        assert len(payload["tool_executions"]) == 2
        assert {item["status"] for item in payload["tool_executions"]} == {"executed", "approval_required"}

        search = client.get(
            "/api/v1/meetings/search",
            params={"user_external_id": user_external_id, "query": "batch pipeline", "limit": 5},
        )
        assert search.status_code == 200
        assert len(search.json()["results"]) == 1

        meeting_id = search.json()["results"][0]["meeting_id"]
        tasks = client.get(f"/api/v1/meetings/{meeting_id}/tasks")
        assert tasks.status_code == 200
        assert tasks.json()["tasks"]

        decisions = client.get(
            "/api/v1/decisions",
            params={"user_external_id": user_external_id, "topic": "ship", "limit": 5},
        )
        assert decisions.status_code == 200
        assert decisions.json()["results"]

        answer = client.post(
            "/api/v1/query",
            json={"user_external_id": user_external_id, "question": "What did we decide about the batch pipeline?"},
        )
        assert answer.status_code == 200
        answer_payload = answer.json()
        assert "batch pipeline" in answer_payload["answer"].lower()
        assert answer_payload["citations"]
        assert answer_payload["chunks"] or answer_payload["meetings"]
