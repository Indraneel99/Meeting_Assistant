import time
from uuid import uuid4

from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.schemas.batch import BatchMeetingRequest


def build_async_settings() -> Settings:
    return Settings(
        batch_processing_mode="async",
        job_queue_provider="inprocess",
        queue_provider="memory",
    )


def test_async_batch_submission_returns_accepted_job() -> None:
    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"

    with TestClient(create_app(build_async_settings())) as client:
        response = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Async planning sync",
                "transcript_text": (
                    "Decision: ship async processing. "
                    "Action: prepare rollout checklist. "
                    "Please email the summary to the team. "
                    "Schedule a calendar follow-up next Tuesday."
                ),
            },
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["job_id"] == payload["workflow_run_id"]


def test_workflow_status_polls_until_completion() -> None:
    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"

    with TestClient(create_app(build_async_settings())) as client:
        accepted = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Async workflow status",
                "transcript_text": (
                    "Decision: ship async processing. "
                    "Action: prepare rollout checklist. "
                    "Please email the summary to the team. "
                    "Schedule a calendar follow-up next Tuesday."
                ),
            },
        )
        workflow_run_id = accepted.json()["workflow_run_id"]

        terminal_status = None
        for _ in range(100):
            status_response = client.get(f"/api/v1/workflows/{workflow_run_id}")
            assert status_response.status_code == 200
            terminal_status = status_response.json()["status"]
            if terminal_status in {"done", "awaiting_approval", "failed"}:
                break
            time.sleep(0.05)

        assert terminal_status == "awaiting_approval"
        payload = client.get(f"/api/v1/workflows/{workflow_run_id}").json()
        assert payload["tool_executions"]
        assert payload["tasks_created"] >= 1


def test_workflow_status_not_found() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/workflows/999999")
        assert response.status_code == 404


def test_run_batch_workflow_uses_existing_workflow_record() -> None:
    from meeting_assistant.bootstrap import bootstrap_container

    class CaptureOnlyQueue:
        def __init__(self) -> None:
            self.jobs: list[tuple[int, dict[str, object]]] = []

        def enqueue_batch(self, workflow_run_id: int, payload: dict[str, object]) -> None:
            self.jobs.append((workflow_run_id, payload))

    settings = build_async_settings()
    container = bootstrap_container(settings)
    capture_queue = CaptureOnlyQueue()
    container.orchestrator.job_queue = capture_queue
    payload = BatchMeetingRequest(
        user_external_id=f"user-{uuid4()}",
        user_email=f"{uuid4()}@example.com",
        title="Worker replay",
        transcript_text="Decision: keep the worker path simple. Action: send recap.",
    )
    accepted = container.orchestrator.submit_batch_meeting(payload)
    assert len(capture_queue.jobs) == 1

    result = container.orchestrator.run_batch_workflow(
        workflow_run_id=accepted["workflow_run_id"],
        payload=payload,
    )

    assert result["status"] == "done"
    status = container.orchestrator.get_workflow_status(accepted["workflow_run_id"])
    assert status.status == "done"
