from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from meeting_assistant.services.tools.http import request_json


class StubCalendarToolProvider:
    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        return {
            "provider": "stub",
            "approval_required": True,
            "approval_request_id": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()[:12],
            "idempotency_key": idempotency_key,
        }

    def execute_after_approval(
        self,
        payload: dict[str, str],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        event_key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
        return {
            "provider": "stub",
            "event_id": f"evt_{event_key}",
            "status": "created",
            "title": payload.get("title", ""),
            "provider_message_id": f"evt_{event_key}",
            "message": "Calendar event created after approval.",
            "idempotency_key": idempotency_key,
        }


class GoogleCalendarToolProvider:
    def __init__(
        self,
        *,
        access_token_provider: Callable[[], str],
        calendar_id: str,
        http_client: httpx.Client,
    ) -> None:
        self.access_token_provider = access_token_provider
        self.calendar_id = calendar_id
        self.http_client = http_client

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        return {
            "provider": "google-calendar",
            "approval_required": True,
            "approval_request_id": (idempotency_key or hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest())[:12],
            "title": payload.get("title", ""),
            "idempotency_key": idempotency_key,
        }

    def execute_after_approval(
        self,
        payload: dict[str, str],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        start = datetime.now(UTC) + timedelta(days=1)
        end = start + timedelta(hours=1)
        event_body = {
            "summary": payload.get("title", "Meeting follow-up"),
            "description": payload.get("details", ""),
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            "iCalUID": _ical_uid(idempotency_key, payload),
        }

        access_token = self.access_token_provider()
        response_payload = request_json(
            self.http_client,
            "POST",
            f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events",
            provider="google-calendar",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=event_body,
        )

        event_id = str(response_payload.get("id", ""))
        html_link = str(response_payload.get("htmlLink", ""))
        return {
            "provider": "google-calendar",
            "event_id": event_id,
            "status": response_payload.get("status", "created"),
            "title": payload.get("title", ""),
            "html_link": html_link,
            "provider_message_id": event_id,
            "message": "Calendar event created after approval.",
            "idempotency_key": idempotency_key,
        }


def _ical_uid(idempotency_key: str | None, payload: dict[str, str]) -> str:
    seed = idempotency_key or json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return f"{digest[:24]}@meeting-assistant.local"
