from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx

from meeting_assistant.core.config import Settings
from meeting_assistant.services.tools.base import ToolProvider
from meeting_assistant.services.tools.google_auth import build_google_access_token_provider
from meeting_assistant.services.tools.providers.calendar import GoogleCalendarToolProvider, StubCalendarToolProvider
from meeting_assistant.services.tools.providers.email import SendGridEmailToolProvider, StubEmailToolProvider
from meeting_assistant.services.tools.providers.jira import JiraRestToolProvider, StubJiraToolProvider
from meeting_assistant.services.tools.providers.slack import (
    SlackApiToolProvider,
    SlackWebhookToolProvider,
    StubSlackToolProvider,
)


def build_sleep_fn(settings: Settings) -> Callable[[float], None]:
    if settings.tool_execution_backoff_mode == "background":
        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-backoff")

        def sleep_fn(seconds: float) -> None:
            future = pool.submit(time.sleep, seconds)
            future.result()

        return sleep_fn
    return time.sleep


def build_tool_http_client(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=settings.tool_http_timeout_seconds)


def build_email_provider(settings: Settings, http_client: httpx.Client) -> ToolProvider:
    if settings.email_provider == "sendgrid":
        if not settings.email_sendgrid_api_key:
            raise ValueError("email_provider=sendgrid requires MEETING_ASSISTANT_EMAIL_SENDGRID_API_KEY")
        return SendGridEmailToolProvider(
            api_key=settings.email_sendgrid_api_key,
            from_address=settings.email_from_address,
            default_recipient=settings.email_default_recipient,
            http_client=http_client,
        )
    if settings.email_provider != "stub":
        raise ValueError(f"Unsupported email provider: {settings.email_provider}")
    return StubEmailToolProvider()


def build_calendar_provider(settings: Settings, http_client: httpx.Client) -> ToolProvider:
    if settings.calendar_provider == "google":
        if not settings.calendar_google_service_account_json:
            raise ValueError(
                "calendar_provider=google requires MEETING_ASSISTANT_CALENDAR_GOOGLE_SERVICE_ACCOUNT_JSON"
            )
        access_token_provider = build_google_access_token_provider(
            service_account_json=settings.calendar_google_service_account_json,
            impersonate_subject=settings.calendar_google_impersonate_subject,
        )
        return GoogleCalendarToolProvider(
            access_token_provider=access_token_provider,
            calendar_id=settings.calendar_google_calendar_id,
            http_client=http_client,
        )
    if settings.calendar_provider != "stub":
        raise ValueError(f"Unsupported calendar provider: {settings.calendar_provider}")
    return StubCalendarToolProvider()


def build_slack_provider(settings: Settings, http_client: httpx.Client) -> ToolProvider:
    if settings.slack_provider == "webhook":
        if not settings.slack_webhook_url:
            raise ValueError("slack_provider=webhook requires MEETING_ASSISTANT_SLACK_WEBHOOK_URL")
        return SlackWebhookToolProvider(webhook_url=settings.slack_webhook_url, http_client=http_client)
    if settings.slack_provider == "api":
        if not settings.slack_bot_token:
            raise ValueError("slack_provider=api requires MEETING_ASSISTANT_SLACK_BOT_TOKEN")
        return SlackApiToolProvider(
            bot_token=settings.slack_bot_token,
            default_channel=settings.slack_default_channel,
            http_client=http_client,
        )
    if settings.slack_provider != "stub":
        raise ValueError(f"Unsupported slack provider: {settings.slack_provider}")
    return StubSlackToolProvider()


def build_jira_provider(settings: Settings, http_client: httpx.Client) -> ToolProvider:
    if settings.jira_provider == "rest":
        missing = [
            name
            for name, value in {
                "jira_base_url": settings.jira_base_url,
                "jira_user_email": settings.jira_user_email,
                "jira_api_token": settings.jira_api_token,
                "jira_project_key": settings.jira_project_key,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"jira_provider=rest requires settings: {', '.join(missing)}")
        return JiraRestToolProvider(
            base_url=settings.jira_base_url or "",
            user_email=settings.jira_user_email or "",
            api_token=settings.jira_api_token or "",
            project_key=settings.jira_project_key or "",
            default_issue_type=settings.jira_default_issue_type,
            http_client=http_client,
        )
    if settings.jira_provider != "stub":
        raise ValueError(f"Unsupported jira provider: {settings.jira_provider}")
    return StubJiraToolProvider()


def build_tool_providers(settings: Settings) -> dict[str, ToolProvider]:
    http_client = build_tool_http_client(settings)
    return {
        "email.send": build_email_provider(settings, http_client),
        "calendar.create_event": build_calendar_provider(settings, http_client),
        "slack.notify": build_slack_provider(settings, http_client),
        "jira.create_issue": build_jira_provider(settings, http_client),
    }
