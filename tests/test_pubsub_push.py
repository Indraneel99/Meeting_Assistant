from __future__ import annotations

import base64
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from meeting_assistant.core.config import Settings
from meeting_assistant.services.pubsub_push import (
    PubSubPushEnvelope,
    decode_pubsub_push_envelope,
    verify_pubsub_push_authorization,
)
from meeting_assistant.worker_app import create_worker_app


def _encode_push_body(workflow_run_id: int, payload: dict[str, object], attributes: dict[str, str] | None = None) -> dict[str, object]:
    message_bytes = json.dumps({"workflow_run_id": workflow_run_id, "payload": payload}).encode("utf-8")
    return {
        "message": {
            "data": base64.b64encode(message_bytes).decode("ascii"),
            "attributes": attributes or {},
            "messageId": "1",
        },
        "subscription": "projects/test/subscriptions/meeting-assistant-batch-push",
    }


def test_decode_pubsub_push_envelope() -> None:
    workflow_run_id, payload, attributes = decode_pubsub_push_envelope(
        PubSubPushEnvelope.model_validate(
            _encode_push_body(99, {"title": "Demo", "transcript_text": "hello"}, {"traceparent": "00-abc-def-01"})
        )
    )
    assert workflow_run_id == 99
    assert payload["title"] == "Demo"
    assert attributes["traceparent"] == "00-abc-def-01"


def test_verify_pubsub_push_authorization_requires_bearer_token() -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_pubsub_push_authorization(None, audience="https://worker.example.com/internal/jobs/batch", skip_auth=False)
    assert exc_info.value.status_code == 401


def test_push_handler_runs_workflow_with_skip_auth() -> None:
    settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        pubsub_topic="jobs",
        pubsub_project="test-project",
        pubsub_push_skip_auth=True,
        readiness_check_redis=False,
        readiness_check_worker=False,
        readiness_check_embedder=False,
    )
    payload = {
        "user_external_id": f"user-{uuid4()}",
        "user_email": f"{uuid4()}@example.com",
        "title": "Pub/Sub push workflow",
        "transcript_text": "Decision: ship Pub/Sub worker. Action: verify push handler.",
    }

    with patch("meeting_assistant.worker_app.bootstrap_container") as bootstrap_mock:
        container = bootstrap_mock.return_value
        with TestClient(create_worker_app(settings)) as client:
            response = client.post(
                "/internal/jobs/batch",
                json=_encode_push_body(42, payload),
            )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    container.orchestrator.run_batch_workflow.assert_called_once_with(42, payload)


def test_push_handler_rejects_when_auth_required_and_missing_token() -> None:
    settings = Settings(
        job_queue_provider="pubsub",
        pubsub_push_audience="https://worker.example.com/internal/jobs/batch",
        pubsub_push_skip_auth=False,
        readiness_check_redis=False,
        readiness_check_worker=False,
        readiness_check_embedder=False,
    )

    with TestClient(create_worker_app(settings)) as client:
        response = client.post(
            "/internal/jobs/batch",
            json=_encode_push_body(1, {"title": "x", "transcript_text": "y", "user_external_id": "u", "user_email": "u@example.com"}),
        )

    assert response.status_code == 401


def test_push_handler_returns_500_on_processing_error() -> None:
    settings = Settings(
        job_queue_provider="pubsub",
        pubsub_push_skip_auth=True,
        readiness_check_redis=False,
        readiness_check_worker=False,
        readiness_check_embedder=False,
    )

    with patch("meeting_assistant.worker_app.bootstrap_container") as bootstrap_mock:
        container = bootstrap_mock.return_value
        container.orchestrator.run_batch_workflow.side_effect = RuntimeError("db unavailable")

        with TestClient(create_worker_app(settings)) as client:
            response = client.post(
                "/internal/jobs/batch",
                json=_encode_push_body(
                    42,
                    {
                        "user_external_id": "user-1",
                        "user_email": "user@example.com",
                        "title": "Fail",
                        "transcript_text": "hello",
                    },
                ),
            )

    assert response.status_code == 500


def test_push_handler_is_idempotent_for_completed_workflow() -> None:
    from meeting_assistant.bootstrap import bootstrap_container
    from meeting_assistant.schemas.batch import BatchMeetingRequest

    submit_settings = Settings(
        auth_enabled=False,
        batch_processing_mode="async",
        job_queue_provider="inprocess",
        queue_provider="memory",
    )
    container = bootstrap_container(submit_settings)
    payload = BatchMeetingRequest(
        user_external_id=f"user-{uuid4()}",
        user_email=f"{uuid4()}@example.com",
        title="Idempotent push",
        transcript_text="Decision: ship. Action: verify idempotency.",
    )
    accepted = container.orchestrator.submit_batch_meeting(payload)
    workflow_run_id = int(accepted["workflow_run_id"])

    worker_settings = Settings(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        pubsub_topic="meeting-assistant-batch-jobs",
        pubsub_project="test-project",
        pubsub_push_skip_auth=True,
        readiness_check_redis=False,
        readiness_check_worker=False,
        readiness_check_embedder=False,
    )
    push_payload = payload.model_dump(mode="json")

    with TestClient(create_worker_app(worker_settings)) as client:
        first = client.post("/internal/jobs/batch", json=_encode_push_body(workflow_run_id, push_payload))
        second = client.post("/internal/jobs/batch", json=_encode_push_body(workflow_run_id, push_payload))

    assert first.status_code == 200
    assert second.status_code == 200

    status = container.orchestrator.get_workflow_status(workflow_run_id)
    assert status.status in {"done", "awaiting_approval"}


def test_cloudrun_entrypoint_uses_uvicorn_for_pubsub_mode() -> None:
    from pathlib import Path

    content = Path("scripts/cloudrun_worker_entrypoint.sh").read_text()
    assert 'MEETING_ASSISTANT_JOB_QUEUE_PROVIDER:-arq}" = "pubsub"' in content
    assert "uvicorn meeting_assistant.worker_app:app" in content
