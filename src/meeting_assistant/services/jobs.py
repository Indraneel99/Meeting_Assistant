from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Protocol

from arq import create_pool
from arq.connections import RedisSettings


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
        self._handler(workflow_run_id, payload)


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
            args=(workflow_run_id, payload),
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
            await pool.enqueue_job("process_batch_workflow", workflow_run_id, payload)
        finally:
            await pool.close()


def build_batch_job_queue(*, batch_processing_mode: str, job_queue_provider: str, redis_url: str) -> BatchJobQueue:
    if batch_processing_mode != "async":
        return SyncBatchJobQueue()
    if job_queue_provider == "arq":
        return ArqBatchJobQueue(redis_url)
    return InProcessBatchJobQueue()
