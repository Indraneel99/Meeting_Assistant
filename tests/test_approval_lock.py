from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base, WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import ToolCall
from meeting_assistant.services.approval_lock import (
    ApprovalLockBusy,
    InMemoryApprovalLock,
    NoOpApprovalLock,
    RedisApprovalLock,
    build_approval_lock,
    hold_approval_lock,
)
from meeting_assistant.services.tools import ToolExecutor, build_tool_providers


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del ex
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        del script, numkeys
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_build_approval_lock_uses_redis_when_auth_enabled() -> None:
    lock = build_approval_lock(
        Settings(
            auth_enabled=True,
            redis_url="redis://localhost:6379/0",
        )
    )
    assert isinstance(lock, RedisApprovalLock)


def test_build_approval_lock_is_noop_when_auth_disabled() -> None:
    lock = build_approval_lock(Settings(auth_enabled=False, redis_url="redis://localhost:6379/0"))
    assert isinstance(lock, NoOpApprovalLock)


def test_redis_approval_lock_uses_set_nx() -> None:
    fake = FakeRedis()
    lock = RedisApprovalLock(fake, ttl_seconds=30)

    assert lock.acquire(42) is True
    assert lock.acquire(42) is False

    lock.release(42)
    assert lock.acquire(42) is True


def test_hold_approval_lock_raises_when_already_held() -> None:
    lock = InMemoryApprovalLock()
    lock.acquire(7)

    with pytest.raises(ApprovalLockBusy):
        with hold_approval_lock(lock, 7):
            pass


def test_approve_returns_conflict_when_lock_is_held() -> None:
    user_external_id = f"user-{uuid4()}"
    lock = InMemoryApprovalLock()
    settings = Settings(
        auth_enabled=True,
        auth_mode="api_key",
        auth_api_keys=f"{user_external_id}:secret",
        auth_jwt_secret="jwt-test-secret-key-with-32-bytes-minimum",
        readiness_check_redis=False,
        readiness_check_embedder=False,
    )

    with TestClient(create_app(settings)) as client:
        client.app.state.container.approval_service.approval_lock = lock

        ingest = client.post(
            "/api/v1/meetings/batch",
            json={
                "user_external_id": user_external_id,
                "user_email": f"{user_external_id}@example.com",
                "title": "Lock test",
                "transcript_text": "Please email the team. Schedule a calendar follow-up next Tuesday.",
            },
            headers={"X-API-Key": "secret"},
        )
        assert ingest.status_code == 200
        workflow_run_id = ingest.json()["workflow_run_id"]
        approval_request_id = client.get(
            f"/api/v1/workflows/{workflow_run_id}/approvals",
            headers={"X-API-Key": "secret"},
        ).json()[0]["approval_request_id"]

        assert lock.acquire(approval_request_id) is True
        blocked = client.post(
            f"/api/v1/approvals/{approval_request_id}/approve",
            json={"resolved_by": "second-reviewer"},
            headers={"X-API-Key": "secret"},
        )
        assert blocked.status_code == 409
        assert "in progress" in blocked.json()["detail"]


def test_concurrent_approve_only_one_worker_enters_lock() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("lock-user", "lock-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Schedule a calendar follow-up.")
    workflow_run = repository.create_workflow_run(meeting.id)
    repository.update_workflow_status(workflow_run.id, WorkflowStatus.AWAITING_APPROVAL)
    executor = ToolExecutor(repository, providers=build_tool_providers(Settings()), sleep_fn=lambda _: None)
    executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="calendar.create_event", payload={"title": "Sync", "details": "Book it"}),
    )
    approval_request_id = repository.list_approval_requests(workflow_run.id)[0].id

    lock = InMemoryApprovalLock()
    entered = threading.Barrier(2, timeout=2)
    results: list[bool] = []

    def worker() -> None:
        entered.wait()
        results.append(lock.acquire(approval_request_id))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(results) == [False, True]
