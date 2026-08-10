from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base, WorkflowRun, WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.services.stale_workflows import StaleWorkflowMonitor


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_stale_workflow_endpoint_returns_empty_when_none_pending() -> None:
    settings = Settings(
        stale_workflow_alert_enabled=True,
        stale_workflow_threshold_minutes=15,
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/admin/ops/stale-workflows")
        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is True
        assert payload["count"] == 0
        assert payload["workflows"] == []


def test_list_stale_pending_workflows_finds_old_runs() -> None:
    repository = build_repository()
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")
    meeting = repository.create_meeting(user.id, "Stale test", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)

    with repository.session_factory() as session:
        run = session.get(WorkflowRun, workflow_run.id)
        assert run is not None
        run.created_at = datetime.now(UTC) - timedelta(minutes=30)
        session.commit()

    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    records = repository.list_stale_pending_workflows(older_than=cutoff)
    assert len(records) == 1
    assert records[0].workflow_run_id == workflow_run.id
    assert records[0].user_external_id == user.external_id
    assert records[0].status == WorkflowStatus.PENDING.value


def test_list_stale_pending_workflows_ignores_recent_runs() -> None:
    repository = build_repository()
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")
    meeting = repository.create_meeting(user.id, "Fresh test", None, "Transcript")
    repository.create_workflow_run(meeting.id)

    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    assert repository.list_stale_pending_workflows(older_than=cutoff) == []


def test_stale_workflow_monitor_returns_alert_payload() -> None:
    repository = build_repository()
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")
    meeting = repository.create_meeting(user.id, "Stale test", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)

    with repository.session_factory() as session:
        run = session.get(WorkflowRun, workflow_run.id)
        assert run is not None
        run.created_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()

    settings = Settings(stale_workflow_alert_enabled=True, stale_workflow_threshold_minutes=15)
    response = StaleWorkflowMonitor(repository, settings).check_and_alert()

    assert response.enabled is True
    assert response.count == 1
    assert response.workflows[0].workflow_run_id == workflow_run.id
    assert response.workflows[0].pending_minutes >= 20


def test_stale_workflow_check_disabled() -> None:
    settings = Settings(
        stale_workflow_alert_enabled=False,
        readiness_check_redis=False,
        readiness_check_embedder=False,
        readiness_check_worker=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/admin/ops/stale-workflows")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
