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
from meeting_assistant.services.tools.providers.email import SendGridEmailToolProvider, UserEmailToolProvider
from meeting_assistant.services.tools.user_factory import UserToolProviderFactory


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_user_email_provider_sends_to_configured_recipients_with_branded_from() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(202, headers={"X-Message-Id": "sg-user-1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = UserEmailToolProvider(
        recipients=["alice@example.com", "bob@example.com"],
        from_email="notifications@example.com",
        from_name="Meeting Assistant",
        http_client=client,
        api_key="SG.test",
        reply_to="owner@example.com",
    )

    result = provider.execute(
        {"subject": "Meeting recap", "body": "Summary attached"},
        idempotency_key="email-idem",
    )

    assert result["provider"] == "sendgrid-user-preferences"
    assert result["identity"] == "Meeting Assistant"
    assert result["recipients"] == ["alice@example.com", "bob@example.com"]
    body = captured["body"]
    assert body["from"] == {"email": "notifications@example.com", "name": "Meeting Assistant"}
    assert body["reply_to"] == {"email": "owner@example.com"}
    assert body["personalizations"][0]["to"] == [
        {"email": "alice@example.com"},
        {"email": "bob@example.com"},
    ]


def test_user_email_provider_rejects_disallowed_recipient() -> None:
    provider = UserEmailToolProvider(
        recipients=["alice@example.com"],
        from_email="notifications@example.com",
        from_name="Meeting Assistant",
        http_client=httpx.Client(),
        api_key="SG.test",
    )

    try:
        provider.execute({"recipient": "stranger@example.com", "body": "Hi"})
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "not in the user's notification preferences" in str(exc)


def test_user_email_provider_stub_mode_without_sendgrid_key() -> None:
    provider = UserEmailToolProvider(
        recipients=["alice@example.com"],
        from_email="notifications@example.com",
        from_name="Meeting Assistant",
        http_client=httpx.Client(),
        api_key=None,
    )

    result = provider.execute({"subject": "Recap", "body": "Notes"})

    assert result["provider"] == "stub-user-email"
    assert result["recipients"] == ["alice@example.com"]
    assert result["identity"] == "Meeting Assistant"


def test_tool_executor_uses_user_email_preferences() -> None:
    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("email-user", "owner@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.EMAIL_PREFS,
        settings_json={
            "notification_emails": ["alice@example.com", "bob@example.com"],
            "notifications_enabled": True,
        },
    )
    meeting = repository.create_meeting(user.id, "Sync", None, "Email the team a recap")
    workflow_run = repository.create_workflow_run(meeting.id)

    factory = UserToolProviderFactory(
        repository,
        encryptor=encryptor,
        settings=Settings(email_provider="stub"),
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
        tool_call=ToolCall(
            tool_name="email.send",
            payload={"subject": "Recap", "body": "Launch checklist agreed"},
        ),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "stub-user-email"
    assert execution.result["recipients"] == ["alice@example.com", "bob@example.com"]


def test_tool_executor_skips_user_email_when_notifications_disabled() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(202, headers={"X-Message-Id": "sg-deploy"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("email-user", "owner@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.EMAIL_PREFS,
        settings_json={
            "notification_emails": ["alice@example.com"],
            "notifications_enabled": False,
        },
    )
    meeting = repository.create_meeting(user.id, "Sync", None, "Email the team")
    workflow_run = repository.create_workflow_run(meeting.id)

    providers = build_tool_providers(Settings())
    providers["email.send"] = SendGridEmailToolProvider(
        api_key="SG.test",
        from_address="noreply@example.com",
        default_recipient="deploy@example.com",
        http_client=mock_client,
    )
    factory = UserToolProviderFactory(
        repository,
        encryptor=encryptor,
        settings=Settings(email_provider="sendgrid", email_sendgrid_api_key="SG.test"),
        http_client=mock_client,
    )
    executor = ToolExecutor(repository, providers=providers, user_tool_factory=factory, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="email.send", payload={"subject": "Recap", "body": "Notes"}),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "sendgrid"
    assert execution.result["recipient"] == "deploy@example.com"
