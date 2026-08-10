from __future__ import annotations

import json

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base, IntegrationProvider
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import ToolCall
from meeting_assistant.services.token_encryption import TokenEncryptor
from meeting_assistant.services.tools import ToolExecutor, build_tool_providers
from meeting_assistant.services.tools.providers.calendar import (
    AssistantCalendarToolProvider,
    StubCalendarToolProvider,
)
from meeting_assistant.services.tools.user_factory import UserToolProviderFactory


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_assistant_calendar_requires_approval() -> None:
    provider = AssistantCalendarToolProvider(
        access_token_provider=lambda: "token",
        assistant_calendar_id="assistant@example.com",
        invite_email="user@example.com",
        http_client=httpx.Client(),
    )

    result = provider.execute({"title": "Follow-up", "details": "Sync next week"})

    assert result["provider"] == "assistant-calendar"
    assert result["approval_required"] is True
    assert result["invite_email"] == "user@example.com"
    assert result["organizer"] == "Meeting Assistant"


def test_assistant_calendar_creates_event_with_attendee_after_approval() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"id": "evt-assistant-1", "status": "confirmed", "htmlLink": "https://calendar.google.com/event?eid=1"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AssistantCalendarToolProvider(
        access_token_provider=lambda: "assistant-token",
        assistant_calendar_id="assistant@example.com",
        invite_email="alice@example.com",
        http_client=client,
        organizer_name="Meeting Assistant",
    )

    result = provider.execute_after_approval(
        {"title": "Product sync", "details": "Review launch checklist"},
        idempotency_key="cal-assistant-idem",
    )

    assert result["provider"] == "assistant-calendar"
    assert result["invite_email"] == "alice@example.com"
    assert result["organizer"] == "Meeting Assistant"
    assert result["event_id"] == "evt-assistant-1"
    body = captured["body"]
    assert body["attendees"] == [{"email": "alice@example.com"}]
    assert "Meeting Assistant" in body["description"]
    assert "assistant@example.com" in captured["url"]


def test_assistant_calendar_stub_mode_without_service_account() -> None:
    provider = AssistantCalendarToolProvider(
        access_token_provider=None,
        assistant_calendar_id="assistant@example.com",
        invite_email="alice@example.com",
        http_client=httpx.Client(),
    )

    result = provider.execute_after_approval({"title": "Sync", "details": "Notes"})

    assert result["provider"] == "stub-assistant-calendar"
    assert result["invite_email"] == "alice@example.com"


def test_tool_executor_uses_assistant_calendar_when_google_connected() -> None:
    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("cal-user", "alice@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.GOOGLE,
        provider_account_id="google-sub-1",
        access_token="google-read-token",
        settings_json={"invite_email": "alice@example.com", "calendar_ids": ["primary"]},
    )
    meeting = repository.create_meeting(user.id, "Sync", None, "Schedule a calendar follow-up")
    workflow_run = repository.create_workflow_run(meeting.id)

    factory = UserToolProviderFactory(
        repository,
        encryptor=encryptor,
        settings=Settings(calendar_provider="stub"),
        http_client=httpx.Client(),
    )
    executor = ToolExecutor(
        repository,
        providers=build_tool_providers(Settings()),
        user_tool_factory=factory,
        sleep_fn=lambda _: None,
    )

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="calendar.create_event", payload={"title": "Sync", "details": "Follow-up"}),
    )

    assert execution.status == "approval_required"
    assert execution.result["provider"] == "assistant-calendar"
    assert execution.result["invite_email"] == "alice@example.com"


def test_tool_executor_falls_back_to_deploy_calendar_when_google_not_connected() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("cal-user", "alice@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Schedule a calendar follow-up")
    workflow_run = repository.create_workflow_run(meeting.id)

    factory = UserToolProviderFactory(
        repository,
        encryptor=TokenEncryptor(Fernet.generate_key().decode()),
        settings=Settings(),
        http_client=httpx.Client(),
    )
    providers = build_tool_providers(Settings())
    providers["calendar.create_event"] = StubCalendarToolProvider()
    executor = ToolExecutor(repository, providers=providers, user_tool_factory=factory, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="calendar.create_event", payload={"title": "Sync", "details": "Follow-up"}),
    )

    assert execution.status == "approval_required"
    assert execution.result["provider"] == "stub"
