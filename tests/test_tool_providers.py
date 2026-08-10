import json
import time

import httpx

from meeting_assistant.core.config import Settings
from meeting_assistant.services.tools.factory import (
    build_calendar_provider,
    build_email_provider,
    build_jira_provider,
    build_slack_provider,
    build_sleep_fn,
    build_tool_http_client,
    build_tool_providers,
)
from meeting_assistant.services.tools.providers.calendar import GoogleCalendarToolProvider
from meeting_assistant.services.tools.providers.email import SendGridEmailToolProvider
from meeting_assistant.services.tools.providers.jira import JiraRestToolProvider
from meeting_assistant.services.tools.providers.slack import SlackApiToolProvider, SlackWebhookToolProvider


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


def test_build_email_provider_sendgrid_mode() -> None:
    settings = Settings(
        email_provider="sendgrid",
        email_sendgrid_api_key="SG.test",
        email_from_address="noreply@example.com",
        email_default_recipient="team@example.com",
    )
    provider = build_email_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, SendGridEmailToolProvider)
    assert provider.from_address == "noreply@example.com"
    assert provider.default_recipient == "team@example.com"


def test_build_email_provider_sendgrid_requires_api_key() -> None:
    import pytest

    settings = Settings(email_provider="sendgrid")
    with pytest.raises(ValueError, match="EMAIL_SENDGRID_API_KEY"):
        build_email_provider(settings, build_tool_http_client(settings))


def test_email_sendgrid_api_key_loads_from_file(tmp_path) -> None:
    secret_file = tmp_path / "sendgrid-key.txt"
    secret_file.write_text("SG.from-file", encoding="utf-8")
    settings = Settings(
        email_provider="sendgrid",
        email_sendgrid_api_key_file=str(secret_file),
        email_from_address="noreply@example.com",
        email_default_recipient="team@example.com",
    )
    provider = build_email_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, SendGridEmailToolProvider)
    assert provider.api_key == "SG.from-file"


def test_google_calendar_provider_requires_approval() -> None:
    provider = GoogleCalendarToolProvider(
        access_token_provider=lambda: "access-token",
        calendar_id="primary",
        http_client=httpx.Client(),
    )

    result = provider.execute(
        {"title": "Sync", "details": "Book follow-up"},
        idempotency_key="cal-idem",
    )

    assert result["provider"] == "google-calendar"
    assert result["approval_required"] is True
    assert result["idempotency_key"] == "cal-idem"


def test_google_calendar_execute_after_approval_creates_event() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"id": "evt-123", "status": "confirmed", "htmlLink": "https://calendar.google.com/event?eid=123"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GoogleCalendarToolProvider(
        access_token_provider=lambda: "access-token",
        calendar_id="primary",
        http_client=client,
    )

    result = provider.execute_after_approval(
        {"title": "Sync", "details": "Book follow-up"},
        idempotency_key="cal-idem",
    )

    assert result["provider"] == "google-calendar"
    assert result["event_id"] == "evt-123"
    assert result["provider_message_id"] == "evt-123"
    assert result["html_link"] == "https://calendar.google.com/event?eid=123"
    assert captured["headers"]["authorization"] == "Bearer access-token"
    assert captured["body"]["summary"] == "Sync"
    assert captured["body"]["iCalUID"].endswith("@meeting-assistant.local")


def test_build_calendar_provider_google_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "meeting_assistant.services.tools.factory.build_google_access_token_provider",
        lambda **kwargs: lambda: "token",
    )
    settings = Settings(
        calendar_provider="google",
        calendar_google_service_account_json='{"type":"service_account"}',
        calendar_google_calendar_id="team@example.com",
    )
    provider = build_calendar_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, GoogleCalendarToolProvider)
    assert provider.calendar_id == "team@example.com"


def test_build_calendar_provider_google_requires_service_account_json() -> None:
    import pytest

    settings = Settings(calendar_provider="google")
    with pytest.raises(ValueError, match="CALENDAR_GOOGLE_SERVICE_ACCOUNT_JSON"):
        build_calendar_provider(settings, build_tool_http_client(settings))


def test_calendar_service_account_json_loads_from_file(tmp_path, monkeypatch) -> None:
    secret_file = tmp_path / "google-calendar-sa.json"
    secret_file.write_text('{"type":"service_account","project_id":"from-file"}', encoding="utf-8")
    monkeypatch.setattr(
        "meeting_assistant.services.tools.factory.build_google_access_token_provider",
        lambda **kwargs: lambda: "token",
    )
    settings = Settings(
        calendar_provider="google",
        calendar_google_service_account_json_file=str(secret_file),
    )
    provider = build_calendar_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, GoogleCalendarToolProvider)


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


def test_slack_api_provider_posts_message() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True, "ts": "1234.5678"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = SlackApiToolProvider(
        bot_token="xoxb-test-token",
        default_channel="#alerts",
        http_client=client,
    )

    result = provider.execute(
        {"body": "Meeting recap ready"},
        idempotency_key="slack-api-idem",
    )

    assert result["provider"] == "slack-api"
    assert result["channel"] == "#alerts"
    assert result["provider_message_id"] == "1234.5678"
    assert captured["headers"]["authorization"] == "Bearer xoxb-test-token"
    assert captured["body"]["text"] == "Meeting recap ready"
    assert captured["body"]["metadata"]["event_payload"]["idempotency_key"] == "slack-api-idem"


def test_build_slack_provider_webhook_mode() -> None:
    settings = Settings(
        slack_provider="webhook",
        slack_webhook_url="https://hooks.slack.com/services/test",
    )
    provider = build_slack_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, SlackWebhookToolProvider)


def test_build_slack_provider_api_mode() -> None:
    settings = Settings(
        slack_provider="api",
        slack_bot_token="xoxb-test",
        slack_default_channel="#general",
    )
    provider = build_slack_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, SlackApiToolProvider)


def test_build_slack_provider_webhook_requires_url() -> None:
    import pytest

    settings = Settings(slack_provider="webhook")
    with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL"):
        build_slack_provider(settings, build_tool_http_client(settings))


def test_slack_webhook_url_loads_from_file(tmp_path) -> None:
    secret_file = tmp_path / "slack-webhook.txt"
    secret_file.write_text("https://hooks.slack.com/services/from-file", encoding="utf-8")
    settings = Settings(slack_provider="webhook", slack_webhook_url_file=str(secret_file))
    provider = build_slack_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, SlackWebhookToolProvider)
    assert provider.webhook_url == "https://hooks.slack.com/services/from-file"


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


def test_build_jira_provider_rest_mode() -> None:
    settings = Settings(
        jira_provider="rest",
        jira_base_url="https://example.atlassian.net",
        jira_user_email="bot@example.com",
        jira_api_token="token",
        jira_project_key="ENG",
        jira_default_issue_type="Task",
    )
    provider = build_jira_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, JiraRestToolProvider)
    assert provider.project_key == "ENG"


def test_build_jira_provider_rest_requires_settings() -> None:
    import pytest

    settings = Settings(jira_provider="rest", jira_base_url="https://example.atlassian.net")
    with pytest.raises(ValueError, match="jira_user_email"):
        build_jira_provider(settings, build_tool_http_client(settings))


def test_jira_api_token_loads_from_file(tmp_path) -> None:
    secret_file = tmp_path / "jira-token.txt"
    secret_file.write_text("token-from-file", encoding="utf-8")
    settings = Settings(
        jira_provider="rest",
        jira_base_url="https://example.atlassian.net",
        jira_user_email="bot@example.com",
        jira_api_token_file=str(secret_file),
        jira_project_key="ENG",
    )
    provider = build_jira_provider(settings, build_tool_http_client(settings))
    assert isinstance(provider, JiraRestToolProvider)
    assert provider.api_token == "token-from-file"


def test_background_backoff_runs_sleep_off_calling_thread() -> None:
    settings = Settings(tool_execution_backoff_mode="background")
    sleep_fn = build_sleep_fn(settings)
    started = time.monotonic()
    sleep_fn(0.05)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.04
