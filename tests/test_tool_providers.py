import json
import time

import httpx

from meeting_assistant.core.config import Settings
from meeting_assistant.services.tools.factory import build_sleep_fn, build_tool_providers
from meeting_assistant.services.tools.providers.email import SendGridEmailToolProvider
from meeting_assistant.services.tools.providers.jira import JiraRestToolProvider
from meeting_assistant.services.tools.providers.slack import SlackWebhookToolProvider


def test_build_tool_providers_defaults_to_stub_implementations() -> None:
    providers = build_tool_providers(Settings())
    assert set(providers) == {"email.send", "calendar.create_event", "slack.notify", "jira.create_issue"}

    email_result = providers["email.send"].execute({"subject": "Hello", "body": "World"}, idempotency_key="abc123")
    assert email_result["provider"] == "stub"
    assert email_result["provider_message_id"] == "stub-email-abc123"


def test_sendgrid_provider_propagates_idempotency_and_message_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content.decode())
        assert body["personalizations"][0]["custom_args"]["idempotency_key"] == "idem-123"
        return httpx.Response(202, headers={"X-Message-Id": "sg-message-42"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = SendGridEmailToolProvider(
        api_key="test-key",
        from_address="noreply@example.com",
        default_recipient="team@example.com",
        http_client=client,
    )

    result = provider.execute(
        {"subject": "Recap", "body": "Summary"},
        idempotency_key="idem-123",
    )

    assert result["provider"] == "sendgrid"
    assert result["provider_message_id"] == "sg-message-42"
    assert result["idempotency_key"] == "idem-123"


def test_slack_webhook_provider_posts_message() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = SlackWebhookToolProvider(webhook_url="https://hooks.slack.com/services/test", http_client=client)

    result = provider.execute(
        {"channel": "alerts", "body": "Meeting recap ready"},
        idempotency_key="slack-idem",
    )

    assert result["provider"] == "slack-webhook"
    assert captured["body"]["text"] == "Meeting recap ready"
    assert captured["body"]["metadata"]["idempotency_key"] == "slack-idem"


def test_jira_provider_creates_issue_with_provider_ids() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": "10001", "key": "ENG-42"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = JiraRestToolProvider(
        base_url="https://example.atlassian.net",
        user_email="bot@example.com",
        api_token="token",
        project_key="ENG",
        default_issue_type="Task",
        http_client=client,
    )

    result = provider.execute(
        {
            "issue_summary": "Follow up from meeting",
            "issue_description": "Send launch checklist",
        },
        idempotency_key="jira-idem-1234567890",
    )

    assert result["provider"] == "jira"
    assert result["issue_key"] == "ENG-42"
    assert result["provider_message_id"] == "10001"
    assert "idempotency-jira-idem-1234567890" in captured["body"]["fields"]["labels"][0]


def test_background_backoff_runs_sleep_off_calling_thread() -> None:
    settings = Settings(tool_execution_backoff_mode="background")
    sleep_fn = build_sleep_fn(settings)
    started = time.monotonic()
    sleep_fn(0.05)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.04
