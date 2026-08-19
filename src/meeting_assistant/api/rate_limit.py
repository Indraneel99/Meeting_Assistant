from __future__ import annotations

import hashlib

import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from meeting_assistant.api.auth import parse_api_key_scopes
from meeting_assistant.core.config import Settings


def _credential_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _jwt_user_external_id(token: str, settings: Settings) -> str | None:
    if not settings.auth_jwt_secret:
        return None
    try:
        decode_kwargs: dict[str, object] = {
            "algorithms": [settings.auth_jwt_algorithm],
        }
        if settings.auth_jwt_audience:
            decode_kwargs["audience"] = settings.auth_jwt_audience
        payload = jwt.decode(token, settings.auth_jwt_secret, **decode_kwargs)
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    if isinstance(subject, str) and subject.strip():
        return subject.strip()
    return None


def get_rate_limit_key(request: Request) -> str:
    """Prefer API key / JWT user identity over client IP for fair per-tenant quotas."""
    settings: Settings = request.app.state.settings or Settings()

    api_key = request.headers.get("X-API-Key")
    if api_key and settings.auth_enabled:
        scopes = parse_api_key_scopes(settings.auth_api_keys)
        scoped_user = scopes.get(api_key)
        if scoped_user:
            return f"user:{scoped_user}"
        return f"api_key:{_credential_fingerprint(api_key)}"

    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer ") and settings.auth_enabled:
        token = authorization[7:].strip()
        if token:
            subject = _jwt_user_external_id(token, settings)
            if subject:
                return f"user:{subject}"
            return f"jwt:{_credential_fingerprint(token)}"

    user_external_id = request.query_params.get("user_external_id")
    if user_external_id:
        return f"user:{user_external_id}"

    return _client_ip(request)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=get_rate_limit_key, default_limits=[], enabled=False)


_batch_limit = "10/minute"
_query_limit = "30/minute"
_auth_register_limit = "10/hour"
_auth_login_limit = "20/minute"
_auth_google_callback_limit = "30/minute"


def batch_rate_limit() -> str:
    return _batch_limit


def query_rate_limit() -> str:
    return _query_limit


def auth_register_rate_limit() -> str:
    return _auth_register_limit


def auth_login_rate_limit() -> str:
    return _auth_login_limit


def auth_google_callback_rate_limit() -> str:
    return _auth_google_callback_limit


def auth_ip_rate_limit_key(request: Request) -> str:
    return f"auth:{_client_ip(request)}:{request.url.path}"


def configure_limiter(settings: Settings) -> Limiter:
    global _batch_limit, _query_limit, _auth_register_limit, _auth_login_limit, _auth_google_callback_limit
    _batch_limit = settings.rate_limit_batch
    _query_limit = settings.rate_limit_query
    _auth_register_limit = settings.auth_rate_limit_register
    _auth_login_limit = settings.auth_rate_limit_login
    _auth_google_callback_limit = settings.auth_rate_limit_google_callback
    limiter.enabled = settings.rate_limit_enabled
    limiter._default_limits = [settings.rate_limit_default] if settings.rate_limit_enabled else []
    return limiter
