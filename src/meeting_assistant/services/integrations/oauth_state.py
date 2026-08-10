from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from meeting_assistant.core.config import Settings

_STATE_TTL = timedelta(minutes=10)
_DEV_STATE_SECRET = "integrations-oauth-state-dev-secret"


def _state_secret(settings: Settings) -> str:
    return (
        settings.integrations_oauth_state_secret
        or settings.auth_jwt_secret
        or _DEV_STATE_SECRET
    )


def issue_oauth_state(
    settings: Settings,
    *,
    user_external_id: str,
    provider: str,
    frontend_redirect: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "sub": user_external_id,
        "provider": provider,
        "exp": datetime.now(UTC) + _STATE_TTL,
    }
    if frontend_redirect:
        payload["frontend_redirect"] = frontend_redirect
    return jwt.encode(payload, _state_secret(settings), algorithm="HS256")


def verify_oauth_state(settings: Settings, state: str) -> dict[str, object]:
    try:
        payload = jwt.decode(state, _state_secret(settings), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid or expired OAuth state.") from exc

    subject = payload.get("sub")
    provider = payload.get("provider")
    if not isinstance(subject, str) or not subject:
        raise ValueError("OAuth state is missing user identity.")
    if not isinstance(provider, str) or not provider:
        raise ValueError("OAuth state is missing provider.")
    return payload
