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


class UserEmailToolProvider:
    """Send meeting notifications to a user's configured addresses via deploy-level SendGrid."""

    def __init__(
        self,
        *,
        recipients: list[str],
        from_email: str,
        from_name: str,
        http_client: httpx.Client,
        api_key: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        self.recipients = recipients
        self.from_email = from_email
        self.from_name = from_name
        self.http_client = http_client
        self.api_key = api_key
        self.reply_to = reply_to

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient email delivery failure.")

        recipients = self._resolve_recipients(payload)
        subject = payload.get("subject", "Meeting follow-up")
        body = payload.get("body", "")

        if self.api_key is None:
            return {
                "provider": "stub-user-email",
                "delivery_status": "queued",
                "subject": subject,
                "recipients": recipients,
                "identity": self.from_name,
                "provider_message_id": f"stub-user-email-{idempotency_key[:12] if idempotency_key else 'local'}",
                "idempotency_key": idempotency_key,
            }

        request_body: dict[str, object] = {
            "personalizations": [
                {
                    "to": [{"email": recipient} for recipient in recipients],
                    "custom_args": {"idempotency_key": idempotency_key or ""},
                }
            ],
            "from": {"email": self.from_email, "name": self.from_name},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        if self.reply_to:
            request_body["reply_to"] = {"email": self.reply_to}

        response = self.http_client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        raise_for_response(response, provider="sendgrid-user-email")

        return {
            "provider": "sendgrid-user-preferences",
            "delivery_status": "queued",
            "subject": subject,
            "recipients": recipients,
            "identity": self.from_name,
            "provider_message_id": response.headers.get("X-Message-Id"),
            "idempotency_key": idempotency_key,
        }

    def _resolve_recipients(self, payload: dict[str, str]) -> list[str]:
        requested = payload.get("recipient") or payload.get("target")
        allowed = {recipient.lower() for recipient in self.recipients}
        if requested:
            if requested.lower() not in allowed:
                raise RuntimeError(
                    f"Email recipient {requested!r} is not in the user's notification preferences."
                )
            return [requested]
        if not self.recipients:
            raise RuntimeError("No notification emails configured for this user.")
        return self.recipients
