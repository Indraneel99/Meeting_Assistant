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
    if not trimmed:
        return trimmed
    if trimmed.startswith("#"):
        return trimmed.lower()
    upper = trimmed.upper()
    if (
        len(upper) >= 9
        and upper[0] in {"C", "G", "D"}
        and upper[1:].isalnum()
    ):
        return upper
    return f"#{trimmed.lower()}"


def slack_api_channel(value: str) -> str:
    """Format a stored channel label or ID for chat.postMessage."""
    normalized = normalize_slack_channel(value)
    if normalized.startswith("#"):
        return normalized[1:]
    return normalized


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
        self._allowed_by_normalized = {
            normalize_slack_channel(channel): channel.strip()
            for channel in allowed_channels
            if channel.strip()
        }
        self.http_client = http_client
        self.bot_display_name = bot_display_name

    def _resolve_channel(self, payload: dict[str, str]) -> tuple[str, str]:
        if not self._allowed_by_normalized:
            raise RuntimeError("Slack workspace is connected but no allowed channels are configured.")

        requested = payload.get("channel") or payload.get("target")
        if requested:
            normalized = normalize_slack_channel(requested)
            if normalized in self._allowed_by_normalized:
                stored = self._allowed_by_normalized[normalized]
                return slack_api_channel(stored), stored

        stored = sorted(self._allowed_by_normalized.values())[0]
        return slack_api_channel(stored), stored

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Slack delivery failure.")

        api_channel, display_channel = self._resolve_channel(payload)

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
                "channel": api_channel,
                "text": text,
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
            "channel": display_channel,
            "workspace_id": self.workspace_id,
            "identity": self.bot_display_name,
            "provider_message_id": response_payload.get("ts"),
            "idempotency_key": idempotency_key,
        }
