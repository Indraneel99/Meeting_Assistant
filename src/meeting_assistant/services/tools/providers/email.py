from __future__ import annotations

import httpx

from meeting_assistant.services.tools.base import RetryableToolError
from meeting_assistant.services.tools.http import raise_for_response


class StubEmailToolProvider:
    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient email delivery failure.")
        return {
            "provider": "stub",
            "delivery_status": "queued",
            "subject": payload.get("subject", ""),
            "provider_message_id": f"stub-email-{idempotency_key[:12] if idempotency_key else 'local'}",
            "idempotency_key": idempotency_key,
        }


class SendGridEmailToolProvider:
    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        default_recipient: str | None,
        http_client: httpx.Client,
    ) -> None:
        self.api_key = api_key
        self.from_address = from_address
        self.default_recipient = default_recipient
        self.http_client = http_client

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient email delivery failure.")

        recipient = payload.get("recipient") or payload.get("target") or self.default_recipient
        if not recipient:
            raise RuntimeError("email.send requires recipient or target in payload, or email_default_recipient in settings.")

        request_body: dict[str, object] = {
            "personalizations": [
                {
                    "to": [{"email": recipient}],
                    "custom_args": {"idempotency_key": idempotency_key or ""},
                }
            ],
            "from": {"email": self.from_address},
            "subject": payload.get("subject", "Meeting follow-up"),
            "content": [
                {
                    "type": "text/plain",
                    "value": payload.get("body", ""),
                }
            ],
        }

        response = self.http_client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        raise_for_response(response, provider="sendgrid")

        provider_message_id = response.headers.get("X-Message-Id")
        return {
            "provider": "sendgrid",
            "delivery_status": "queued",
            "subject": payload.get("subject", ""),
            "recipient": recipient,
            "provider_message_id": provider_message_id,
            "idempotency_key": idempotency_key,
        }
