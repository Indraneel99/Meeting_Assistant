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
from meeting_assistant.services.tools.providers.slack import UserSlackToolProvider, normalize_slack_channel
from meeting_assistant.services.tools.user_factory import UserToolProviderFactory


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_normalize_slack_channel() -> None:
    assert normalize_slack_channel("#Product") == "#product"
    assert normalize_slack_channel("C123") == "C123"


def test_user_slack_provider_posts_as_meeting_assistant() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True, "ts": "1234.5678"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = UserSlackToolProvider(
        bot_token="xoxb-user",
        workspace_id="T123",
        allowed_channels=["#product"],
        http_client=client,
        bot_display_name="Meeting Assistant",
    )

    result = provider.execute({"channel": "#product", "body": "Recap ready"}, idempotency_key="idem-1")

    assert result["provider"] == "slack-user-workspace"
    assert result["identity"] == "Meeting Assistant"
    assert result["workspace_id"] == "T123"
    assert captured["body"]["username"] == "Meeting Assistant"
    assert captured["body"]["channel"] == "#product"


def test_user_slack_provider_rejects_disallowed_channel() -> None:
    provider = UserSlackToolProvider(
        bot_token="xoxb-user",
        workspace_id="T123",
        allowed_channels=["#product"],
        http_client=httpx.Client(),
    )

    try:
        provider.execute({"channel": "#secret", "body": "Nope"})
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "not in the user's allowed channels" in str(exc)


def test_user_slack_provider_uses_first_allowed_channel_when_unspecified() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True, "ts": "1234.5678"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = UserSlackToolProvider(
        bot_token="xoxb-user",
        workspace_id="T123",
        allowed_channels=["#general", "#product"],
        http_client=client,
    )

    provider.execute({"body": "Default channel post"})

    assert captured["body"]["channel"] == "#general"


def test_tool_executor_uses_connected_user_slack_integration() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True, "ts": "9999.0001"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("slack-user", "slack-user@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.SLACK,
        provider_account_id="T-WORKSPACE",
        access_token="xoxb-connected",
        settings_json={"channels": ["#product"]},
    )
    meeting = repository.create_meeting(user.id, "Sync", None, "Post recap to slack")
    workflow_run = repository.create_workflow_run(meeting.id)

    factory = UserToolProviderFactory(
        repository,
        encryptor=encryptor,
        settings=Settings(slack_bot_display_name="Meeting Assistant"),
        http_client=mock_client,
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
            tool_name="slack.notify",
            payload={"channel": "#product", "body": "Recap from meeting"},
        ),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "slack-user-workspace"
    assert execution.result["workspace_id"] == "T-WORKSPACE"
    assert captured["body"]["text"] == "Recap from meeting"


def test_tool_executor_falls_back_to_deploy_slack_when_user_not_connected() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, text="ok", headers={"X-Slack-Request-Id": "req-deploy"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    from meeting_assistant.services.tools.providers.slack import SlackWebhookToolProvider

    repository = build_repository()
    user = repository.get_or_create_user("slack-user", "slack-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Post recap to slack")
    workflow_run = repository.create_workflow_run(meeting.id)

    providers = build_tool_providers(Settings())
    providers["slack.notify"] = SlackWebhookToolProvider(
        webhook_url="https://hooks.slack.com/services/test",
        http_client=mock_client,
    )
    factory = UserToolProviderFactory(
        repository,
        encryptor=TokenEncryptor(Fernet.generate_key().decode()),
        settings=Settings(),
        http_client=mock_client,
    )
    executor = ToolExecutor(repository, providers=providers, user_tool_factory=factory, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="slack.notify", payload={"body": "Deploy-level message"}),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "slack-webhook"
    assert captured["body"]["text"] == "Deploy-level message"
