from __future__ import annotations

import httpx

from meeting_assistant.services.tools.base import RetryableToolError
from meeting_assistant.services.tools.http import raise_for_response, request_json


class StubSlackToolProvider:
    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Slack delivery failure.")
        return {
            "provider": "stub",
            "delivery_status": "accepted",
            "channel": payload.get("channel") or payload.get("target", "unknown"),
            "provider_message_id": f"stub-slack-{idempotency_key[:12] if idempotency_key else 'local'}",
            "idempotency_key": idempotency_key,
        }


class SlackWebhookToolProvider:
    def __init__(self, *, webhook_url: str, http_client: httpx.Client) -> None:
        self.webhook_url = webhook_url
        self.http_client = http_client

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Slack delivery failure.")

        text = payload.get("body") or payload.get("details") or payload.get("subject", "")
        response = self.http_client.post(
            self.webhook_url,
            json={"text": text, "metadata": {"idempotency_key": idempotency_key}},
        )
        raise_for_response(response, provider="slack-webhook")

        return {
            "provider": "slack-webhook",
            "delivery_status": "accepted",
            "channel": payload.get("channel") or payload.get("target", "webhook"),
            "provider_message_id": response.headers.get("X-Slack-Request-Id"),
            "idempotency_key": idempotency_key,
        }


class SlackApiToolProvider:
    def __init__(
        self,
        *,
        bot_token: str,
        default_channel: str | None,
        http_client: httpx.Client,
    ) -> None:
        self.bot_token = bot_token
        self.default_channel = default_channel
        self.http_client = http_client

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Slack delivery failure.")

        channel = payload.get("channel") or payload.get("target") or self.default_channel
        if not channel:
            raise RuntimeError("slack.notify requires channel or target in payload, or slack_default_channel in settings.")

        text = payload.get("body") or payload.get("details") or payload.get("subject", "")
        response_payload = request_json(
            self.http_client,
            "POST",
            "https://slack.com/api/chat.postMessage",
            provider="slack-api",
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "channel": channel,
                "text": text,
                "metadata": {"event_type": "meeting_assistant_tool", "event_payload": {"idempotency_key": idempotency_key}},
            },
        )
        if not response_payload.get("ok"):
            error = str(response_payload.get("error", "unknown_error"))
            if error in {"ratelimited", "service_unavailable", "internal_error"}:
                raise RetryableToolError(f"Slack API returned retryable error: {error}")
            raise RuntimeError(f"Slack API error: {error}")

        return {
            "provider": "slack-api",
            "delivery_status": "accepted",
            "channel": channel,
            "provider_message_id": response_payload.get("ts"),
            "idempotency_key": idempotency_key,
        }


def normalize_slack_channel(value: str) -> str:
    trimmed = value.strip()
    if trimmed.startswith("#"):
        return trimmed.lower()
    return trimmed


class UserSlackToolProvider:
    """Posts via a user's connected workspace bot token to allowed channels only."""

    def __init__(
        self,
        *,
        bot_token: str,
        workspace_id: str,
        allowed_channels: list[str],
        http_client: httpx.Client,
        bot_display_name: str = "Meeting Assistant",
    ) -> None:
        self.bot_token = bot_token
        self.workspace_id = workspace_id
        self.allowed_channels = {normalize_slack_channel(channel) for channel in allowed_channels if channel.strip()}
        self.http_client = http_client
        self.bot_display_name = bot_display_name

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Slack delivery failure.")

        if not self.allowed_channels:
            raise RuntimeError("Slack workspace is connected but no allowed channels are configured.")

        requested = payload.get("channel") or payload.get("target")
        if requested:
            normalized = normalize_slack_channel(requested)
            if normalized not in self.allowed_channels:
                allowed = ", ".join(sorted(self.allowed_channels))
                raise RuntimeError(
                    f"Slack channel {requested!r} is not in the user's allowed channels: {allowed}"
                )
            channel = requested.strip()
        else:
            channel = next(iter(sorted(self.allowed_channels)))

        text = payload.get("body") or payload.get("details") or payload.get("subject", "")
        response_payload = request_json(
            self.http_client,
            "POST",
            "https://slack.com/api/chat.postMessage",
            provider="slack-user-workspace",
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "channel": channel,
                "text": text,
                "username": self.bot_display_name,
                "metadata": {
                    "event_type": "meeting_assistant_tool",
                    "event_payload": {"idempotency_key": idempotency_key, "workspace_id": self.workspace_id},
                },
            },
        )
        if not response_payload.get("ok"):
            error = str(response_payload.get("error", "unknown_error"))
            if error in {"ratelimited", "service_unavailable", "internal_error"}:
                raise RetryableToolError(f"Slack API returned retryable error: {error}")
            raise RuntimeError(f"Slack API error: {error}")

        return {
            "provider": "slack-user-workspace",
            "delivery_status": "accepted",
            "channel": channel,
            "workspace_id": self.workspace_id,
            "identity": self.bot_display_name,
            "provider_message_id": response_payload.get("ts"),
            "idempotency_key": idempotency_key,
        }
