from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Protocol

from meeting_assistant.core.config import Settings
from meeting_assistant.services.redis_client import redis_from_url

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class ApprovalLockBusy(Exception):
    """Raised when another worker is already resolving this approval request."""


class ApprovalLock(Protocol):
    def acquire(self, approval_request_id: int) -> bool:
        ...

    def release(self, approval_request_id: int) -> None:
        ...


class NoOpApprovalLock:
    def acquire(self, approval_request_id: int) -> bool:
        del approval_request_id
        return True

    def release(self, approval_request_id: int) -> None:
        del approval_request_id


class InMemoryApprovalLock:
    """Process-local NX lock for tests."""

    def __init__(self) -> None:
        self._held: set[int] = set()

    def acquire(self, approval_request_id: int) -> bool:
        if approval_request_id in self._held:
            return False
        self._held.add(approval_request_id)
        return True

    def release(self, approval_request_id: int) -> None:
        self._held.discard(approval_request_id)


class RedisApprovalLock:
    def __init__(self, client, *, ttl_seconds: int, key_prefix: str = "meeting-assistant:approval-lock") -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self._tokens: dict[int, str] = {}

    def _key(self, approval_request_id: int) -> str:
        return f"{self.key_prefix}:{approval_request_id}"

    def acquire(self, approval_request_id: int) -> bool:
        token = uuid.uuid4().hex
        acquired = bool(
            self.client.set(self._key(approval_request_id), token, nx=True, ex=self.ttl_seconds)
        )
        if acquired:
            self._tokens[approval_request_id] = token
        return acquired

    def release(self, approval_request_id: int) -> None:
        token = self._tokens.pop(approval_request_id, None)
        if token is None:
            return
        self.client.eval(_RELEASE_LOCK_SCRIPT, 1, self._key(approval_request_id), token)


@contextmanager
def hold_approval_lock(lock: ApprovalLock, approval_request_id: int):
    if not lock.acquire(approval_request_id):
        raise ApprovalLockBusy(
            f"Approval request {approval_request_id} resolution is already in progress."
        )
    try:
        yield
    finally:
        lock.release(approval_request_id)


def build_approval_lock(settings: Settings) -> ApprovalLock:
    if settings.auth_enabled and settings.redis_url:
        client = redis_from_url(settings.redis_url, decode_responses=True)
        return RedisApprovalLock(client, ttl_seconds=settings.approval_lock_ttl_seconds)
    return NoOpApprovalLock()
