from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base, ToolExecutionAttempt, ToolExecutionStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.services.failed_tools import FailedToolMonitor


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def _create_failed_execution(repository: Repository) -> tuple[int, int]:
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")
    meeting = repository.create_meeting(user.id, "Failed tool test", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    execution = repository.create_tool_execution(
        workflow_run.id,
        tool_name="email.send",
        payload='{"subject":"Hi","body":"Test"}',
        idempotency_key=f"key-{uuid4()}",
        status=ToolExecutionStatus.FAILED.value,
        result=json.dumps({"error": "SendGrid unavailable", "dlq": True, "max_retries": 3}),
    )
    repository.create_tool_execution_attempt(
        execution.id,
        1,
        ToolExecutionStatus.FAILED.value,
        None,
        "SendGrid unavailable",
    )
    repository.create_tool_execution_attempt(
        execution.id,
        2,
        ToolExecutionStatus.FAILED.value,
        None,
        "SendGrid unavailable",
    )
    repository.create_tool_execution_attempt(
        execution.id,
        3,
        ToolExecutionStatus.FAILED.value,
        None,
        "SendGrid unavailable",
    )
    with repository.session_factory() as session:
        attempts = session.scalars(
            select(ToolExecutionAttempt).where(ToolExecutionAttempt.tool_execution_id == execution.id)
        ).all()
        for item in attempts:
            item.created_at = datetime.now(UTC) - timedelta(minutes=5)
        session.commit()
    return workflow_run.id, execution.id


def test_failed_tools_endpoint_returns_empty_when_none_failed() -> None:
    settings = Settings(
        failed_tool_alert_enabled=True,
        failed_tool_alert_lookback_minutes=60,
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/admin/ops/failed-tools")
        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is True
        assert payload["count"] == 0
        assert payload["executions"] == []


def test_list_failed_tool_executions_finds_recent_failures() -> None:
    repository = build_repository()
    workflow_run_id, execution_id = _create_failed_execution(repository)

    since = datetime.now(UTC) - timedelta(minutes=60)
    records = repository.list_failed_tool_executions(since=since)
    assert len(records) == 1
    assert records[0].tool_execution_id == execution_id
    assert records[0].workflow_run_id == workflow_run_id
    assert records[0].tool_name == "email.send"
    assert records[0].attempt_count == 3


def test_list_failed_tool_executions_ignores_old_failures() -> None:
    repository = build_repository()
    _create_failed_execution(repository)

    with repository.session_factory() as session:
        attempts = session.scalars(select(ToolExecutionAttempt)).all()
        for attempt in attempts:
            attempt.created_at = datetime.now(UTC) - timedelta(hours=3)
        session.commit()

    since = datetime.now(UTC) - timedelta(minutes=60)
    assert repository.list_failed_tool_executions(since=since) == []


def test_failed_tool_monitor_returns_alert_payload() -> None:
    repository = build_repository()
    workflow_run_id, execution_id = _create_failed_execution(repository)

    settings = Settings(
        failed_tool_alert_enabled=True,
        failed_tool_alert_lookback_minutes=60,
        tool_execution_max_retries=3,
    )
    response = FailedToolMonitor(repository, settings).check_and_alert()

    assert response.enabled is True
    assert response.count == 1
    item = response.executions[0]
    assert item.tool_execution_id == execution_id
    assert item.workflow_run_id == workflow_run_id
    assert item.dlq is True
    assert item.error_message == "SendGrid unavailable"
    assert item.attempt_count == 3
    assert item.max_retries == 3


def test_failed_tool_check_disabled() -> None:
    settings = Settings(
        failed_tool_alert_enabled=False,
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/admin/ops/failed-tools")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
