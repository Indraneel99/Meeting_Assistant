from __future__ import annotations

import json
from collections.abc import Callable


def build_google_access_token_provider(
    *,
    service_account_json: str,
    impersonate_subject: str | None,
) -> Callable[[], str]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Google Calendar provider requires google-auth. Install with: uv sync --extra tools"
        ) from exc

    info = json.loads(service_account_json)
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
    )
    if impersonate_subject:
        credentials = credentials.with_subject(impersonate_subject)

    def get_access_token() -> str:
        credentials.refresh(Request())
        if not credentials.token:
            raise RuntimeError("Unable to obtain Google Calendar access token.")
        return str(credentials.token)

    return get_access_token
