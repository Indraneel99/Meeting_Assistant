from __future__ import annotations

from collections import defaultdict
from typing import Protocol

import redis


class TranscriptQueue(Protocol):
    def publish(self, meeting_id: int, chunks: list[str]) -> None:
        ...

    def consume(self, meeting_id: int, count: int = 1) -> list[str]:
        ...

    def ack(self, meeting_id: int, message_ids: list[str]) -> None:
        ...

    def nack(self, meeting_id: int, message_ids: list[str]) -> None:
        ...

    def drain(self, meeting_id: int) -> list[str]:
        ...


def _chunk_key(meeting_id: int) -> str:
    return f"meeting-assistant:transcript:{meeting_id}:chunks"


class InMemoryTranscriptQueue:
    def __init__(self) -> None:
        self._messages: dict[int, list[str]] = defaultdict(list)
        self._pending: dict[int, list[str]] = defaultdict(list)

    def publish(self, meeting_id: int, chunks: list[str]) -> None:
        self._messages[meeting_id].extend(chunks)

    def consume(self, meeting_id: int, count: int = 1) -> list[str]:
        if not self._messages[meeting_id]:
            return []
        consumed = self._messages[meeting_id][:count]
        self._messages[meeting_id] = self._messages[meeting_id][count:]
        self._pending[meeting_id].extend(consumed)
        return consumed

    def ack(self, meeting_id: int, message_ids: list[str]) -> None:
        if not message_ids:
            self._pending[meeting_id].clear()
            return
        pending = self._pending[meeting_id]
        self._pending[meeting_id] = [item for item in pending if item not in set(message_ids)]

    def nack(self, meeting_id: int, message_ids: list[str]) -> None:
        if not message_ids:
            requeue = self._pending[meeting_id][:]
            self._pending[meeting_id].clear()
            self._messages[meeting_id] = requeue + self._messages[meeting_id]
            return
        requeue: list[str] = []
        pending = self._pending[meeting_id]
        self._pending[meeting_id] = []
        for item in pending:
            if item in message_ids:
                requeue.append(item)
            else:
                self._pending[meeting_id].append(item)
        self._messages[meeting_id] = requeue + self._messages[meeting_id]

    def drain(self, meeting_id: int) -> list[str]:
        chunks = list(self._messages[meeting_id])
        self._messages[meeting_id].clear()
        self._pending[meeting_id].clear()
        return chunks


class RedisTranscriptQueue:
    def __init__(self, redis_url: str) -> None:
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def publish(self, meeting_id: int, chunks: list[str]) -> None:
        if chunks:
            self._redis.rpush(_chunk_key(meeting_id), *chunks)

    def consume(self, meeting_id: int, count: int = 1) -> list[str]:
        chunks: list[str] = []
        for _ in range(count):
            chunk = self._redis.lpop(_chunk_key(meeting_id))
            if chunk is None:
                break
            chunks.append(chunk)
        if chunks:
            self._redis.rpush(_pending_key(meeting_id), *chunks)
        return chunks

    def ack(self, meeting_id: int, message_ids: list[str]) -> None:
        if message_ids:
            self._redis.lrem(_pending_key(meeting_id), 0, *message_ids)
        else:
            self._redis.delete(_pending_key(meeting_id))

    def nack(self, meeting_id: int, message_ids: list[str]) -> None:
        pending_key = _pending_key(meeting_id)
        if not message_ids:
            requeue = self._redis.lrange(pending_key, 0, -1)
            if requeue:
                self._redis.rpush(_chunk_key(meeting_id), *requeue)
            self._redis.delete(pending_key)
            return

        for message_id in message_ids:
            removed = self._redis.lrem(pending_key, 1, message_id)
            if removed:
                self._redis.rpush(_chunk_key(meeting_id), message_id)

    def drain(self, meeting_id: int) -> list[str]:
        key = _chunk_key(meeting_id)
        chunks = self._redis.lrange(key, 0, -1)
        self._redis.delete(key)
        self._redis.delete(_pending_key(meeting_id))
        return chunks


def _pending_key(meeting_id: int) -> str:
    return f"meeting-assistant:transcript:{meeting_id}:pending"


def build_transcript_queue(*, queue_provider: str, redis_url: str) -> TranscriptQueue:
    if queue_provider == "redis":
        return RedisTranscriptQueue(redis_url)
    return InMemoryTranscriptQueue()
