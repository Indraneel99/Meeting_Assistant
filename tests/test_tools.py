from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import ToolCall
from meeting_assistant.services.tools import ToolExecutor, build_tool_providers


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_calendar_tool_requires_approval() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=build_tool_providers(Settings()), sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="calendar.create_event", payload={"title": "Sync", "details": "Book it"}),
    )

    assert execution.status == "approval_required"
    assert execution.attempts == 1
    assert execution.result["approval_required"] is True

    approvals = repository.list_approval_requests(workflow_run.id)
    assert len(approvals) == 1
    assert approvals[0].tool_name == "calendar.create_event"


def test_retryable_failure_moves_to_dlq_style_failure() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(
        repository,
        providers=build_tool_providers(Settings()),
        max_retries=3,
        backoff_seconds=0,
        sleep_fn=lambda _: None,
    )

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(
            tool_name="email.send",
            payload={
                "subject": "Follow-up",
                "body": "Please send this",
                "simulate_retryable_failure": "true",
            },
        ),
    )

    assert execution.status == "failed"
    assert execution.attempts == 3
    assert execution.result["dlq"] is True


def test_duplicate_execution_reuses_existing_terminal_result() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=build_tool_providers(Settings()), sleep_fn=lambda _: None)
    tool_call = ToolCall(tool_name="email.send", payload={"subject": "Follow-up", "body": "Please send this"})

    first = executor.execute(workflow_run_id=workflow_run.id, tool_call=tool_call)
    second = executor.execute(workflow_run_id=workflow_run.id, tool_call=tool_call)

    assert first.status == "executed"
    assert second.status == "executed"
    assert second.reused is True
    assert second.idempotency_key == first.idempotency_key
