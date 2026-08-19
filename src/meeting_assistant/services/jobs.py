from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Callable
from typing import Any, Protocol

from arq import create_pool
from arq.connections import RedisSettings

from meeting_assistant.core.telemetry import TRACE_CONTEXT_KEY, inject_trace_context


class BatchJobQueue(Protocol):
    def enqueue_batch(self, workflow_run_id: int, payload: dict[str, Any]) -> None:
        ...


BatchJobHandler = Callable[[int, dict[str, Any]], None]


class SyncBatchJobQueue:
    """Runs batch jobs inline for synchronous development and tests."""

    def __init__(self, handler: BatchJobHandler | None = None) -> None:
        self._handler = handler

    def bind(self, handler: BatchJobHandler) -> None:
        self._handler = handler

    def enqueue_batch(self, workflow_run_id: int, payload: dict[str, Any]) -> None:
        if self._handler is None:
            raise RuntimeError("Batch job handler is not configured.")
        self._handler(workflow_run_id, inject_trace_context(payload))


class InProcessBatchJobQueue:
    """Executes batch jobs on a background thread without Redis."""

    def __init__(self, handler: BatchJobHandler | None = None) -> None:
        self._handler = handler

    def bind(self, handler: BatchJobHandler) -> None:
        self._handler = handler

    def enqueue_batch(self, workflow_run_id: int, payload: dict[str, Any]) -> None:
        if self._handler is None:
            raise RuntimeError("Batch job handler is not configured.")
        thread = threading.Thread(
            target=self._handler,
            args=(workflow_run_id, inject_trace_context(payload)),
            daemon=True,
        )
        thread.start()


class ArqBatchJobQueue:
    """Enqueues batch jobs for the ARQ worker process."""

    def __init__(self, redis_url: str) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)

    def enqueue_batch(self, workflow_run_id: int, payload: dict[str, Any]) -> None:
        asyncio.run(self._enqueue(workflow_run_id, payload))

    async def _enqueue(self, workflow_run_id: int, payload: dict[str, Any]) -> None:
        pool = await create_pool(self._redis_settings)
        try:
            await pool.enqueue_job("process_batch_workflow", workflow_run_id, inject_trace_context(payload))
        finally:
            await pool.close()


class PubSubBatchJobQueue:
    """Publishes batch jobs to a GCP Pub/Sub topic for push delivery to the worker."""

    def __init__(
        self,
        *,
        project: str,
        topic: str,
        emulator_host: str | None = None,
        publisher: Any | None = None,
    ) -> None:
        self._project = project
        self._topic = topic
        self._emulator_host = emulator_host
        self._publisher = publisher

    def _get_publisher(self) -> Any:
        if self._publisher is None:
            if self._emulator_host:
                os.environ["PUBSUB_EMULATOR_HOST"] = self._emulator_host
            from google.cloud import pubsub_v1

            self._publisher = pubsub_v1.PublisherClient()
        return self._publisher

    def enqueue_batch(self, workflow_run_id: int, payload: dict[str, Any]) -> None:
        enriched = inject_trace_context(dict(payload))
        trace_carrier = enriched.pop(TRACE_CONTEXT_KEY, None)
        message = json.dumps({"workflow_run_id": workflow_run_id, "payload": enriched}).encode("utf-8")
        attributes = {str(key): str(value) for key, value in (trace_carrier or {}).items()}

        publisher = self._get_publisher()
        topic_path = publisher.topic_path(self._project, self._topic)
        future = publisher.publish(topic_path, message, **attributes)
        future.result()


def build_batch_job_queue(
    *,
    batch_processing_mode: str,
    job_queue_provider: str,
    redis_url: str,
    pubsub_topic: str | None = None,
    pubsub_project: str | None = None,
    pubsub_emulator_host: str | None = None,
) -> BatchJobQueue:
    if batch_processing_mode != "async":
        return SyncBatchJobQueue()
    if job_queue_provider == "arq":
        return ArqBatchJobQueue(redis_url)
    if job_queue_provider == "pubsub":
        if not pubsub_topic or not pubsub_project:
            raise ValueError("pubsub_topic and pubsub_project are required when job_queue_provider=pubsub")
        return PubSubBatchJobQueue(
            project=pubsub_project,
            topic=pubsub_topic,
            emulator_host=pubsub_emulator_host,
        )
    return InProcessBatchJobQueue()
