from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.core.telemetry import TRACE_CONTEXT_KEY
from meeting_assistant.services.jobs import PubSubBatchJobQueue, build_batch_job_queue


def test_build_batch_job_queue_returns_pubsub_queue() -> None:
    queue = build_batch_job_queue(
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        redis_url="redis://localhost:6379/0",
        pubsub_topic="meeting-assistant-batch-jobs",
        pubsub_project="test-project",
    )
    assert isinstance(queue, PubSubBatchJobQueue)


def test_build_batch_job_queue_pubsub_requires_topic_and_project() -> None:
    with pytest.raises(ValueError, match="pubsub_topic and pubsub_project"):
        build_batch_job_queue(
            batch_processing_mode="async",
            job_queue_provider="pubsub",
            redis_url="redis://localhost:6379/0",
            pubsub_topic=None,
            pubsub_project="test-project",
        )


def test_pubsub_enqueue_publishes_json_message() -> None:
    publisher = MagicMock()
    future = MagicMock()
    publisher.publish.return_value = future
    publisher.topic_path.return_value = "projects/test-project/topics/meeting-assistant-batch-jobs"

    queue = PubSubBatchJobQueue(
        project="test-project",
        topic="meeting-assistant-batch-jobs",
        publisher=publisher,
    )
    queue.enqueue_batch(42, {"title": "Weekly sync", "transcript_text": "Decision: ship it."})

    publisher.topic_path.assert_called_once_with("test-project", "meeting-assistant-batch-jobs")
    publisher.publish.assert_called_once()
    call_args = publisher.publish.call_args
    assert call_args.args[0] == "projects/test-project/topics/meeting-assistant-batch-jobs"
    body = json.loads(call_args.args[1].decode("utf-8"))
    assert body["workflow_run_id"] == 42
    assert body["payload"]["title"] == "Weekly sync"
    assert TRACE_CONTEXT_KEY not in body["payload"]
    future.result.assert_called_once()


def test_pubsub_enqueue_includes_trace_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = MagicMock()
    future = MagicMock()
    publisher.publish.return_value = future
    publisher.topic_path.return_value = "projects/test-project/topics/jobs"

    monkeypatch.setattr(
        "meeting_assistant.services.jobs.inject_trace_context",
        lambda payload: {
            **payload,
            TRACE_CONTEXT_KEY: {"traceparent": "00-abc-def-01"},
        },
    )

    queue = PubSubBatchJobQueue(project="test-project", topic="jobs", publisher=publisher)
    queue.enqueue_batch(7, {"title": "Trace test"})

    assert publisher.publish.call_args.kwargs == {"traceparent": "00-abc-def-01"}


def test_async_batch_submission_uses_pubsub_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[tuple[int, dict[str, object]]] = []

    class RecordingPubSubQueue:
        def enqueue_batch(self, workflow_run_id: int, payload: dict[str, object]) -> None:
            published.append((workflow_run_id, payload))

    settings = Settings(
        auth_enabled=False,
        rate_limit_enabled=False,
        batch_processing_mode="async",
        job_queue_provider="pubsub",
        pubsub_topic="meeting-assistant-batch-jobs",
        pubsub_project="test-project",
        queue_provider="memory",
    )

    def fake_build_batch_job_queue(**kwargs: object) -> RecordingPubSubQueue:
        assert kwargs["job_queue_provider"] == "pubsub"
        assert kwargs["pubsub_topic"] == "meeting-assistant-batch-jobs"
        assert kwargs["pubsub_project"] == "test-project"
        return RecordingPubSubQueue()

    monkeypatch.setattr("meeting_assistant.bootstrap.build_batch_job_queue", fake_build_batch_job_queue)

    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Pub/Sub async batch",
                "transcript_text": "Decision: migrate to Pub/Sub. Action: verify publish path.",
            },
        )

    assert response.status_code == 202
    assert len(published) == 1
    workflow_run_id, payload = published[0]
    assert workflow_run_id == response.json()["workflow_run_id"]
    assert payload["title"] == "Pub/Sub async batch"
