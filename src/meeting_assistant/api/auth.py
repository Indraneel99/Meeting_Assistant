from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from meeting_assistant.core.config import Settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True, frozen=True)
class AuthPrincipal:
    auth_type: str
    user_external_id: str | None = None


def parse_api_key_scopes(raw: str) -> dict[str, str | None]:
    scopes: dict[str, str | None] = {}
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        if ":" in entry:
            user_external_id, api_key = entry.split(":", 1)
            scopes[api_key.strip()] = user_external_id.strip()
        else:
            scopes[entry] = None
    return scopes


def _authenticate_api_key(settings: Settings, api_key: str) -> AuthPrincipal:
    scopes = parse_api_key_scopes(settings.auth_api_keys)
    if api_key not in scopes:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    return AuthPrincipal(auth_type="api_key", user_external_id=scopes[api_key])


def _authenticate_jwt(settings: Settings, token: str) -> AuthPrincipal:
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="JWT auth is not configured.")

    try:
        if settings.auth_jwt_audience:
            payload = jwt.decode(
                token,
                settings.auth_jwt_secret,
                algorithms=[settings.auth_jwt_algorithm],
                audience=settings.auth_jwt_audience,
            )
        else:
            payload = jwt.decode(
                token,
                settings.auth_jwt_secret,
                algorithms=[settings.auth_jwt_algorithm],
            )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT.") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT subject is required.")
    return AuthPrincipal(auth_type="jwt", user_external_id=subject)


def resolve_principal(
    settings: Settings,
    *,
    api_key: str | None,
    bearer: HTTPAuthorizationCredentials | None,
) -> AuthPrincipal:
    if not settings.auth_enabled:
        return AuthPrincipal(auth_type="disabled", user_external_id=None)

    if settings.auth_mode == "jwt":
        if bearer is None or bearer.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")
        return _authenticate_jwt(settings, bearer.credentials)

    if api_key:
        return _authenticate_api_key(settings, api_key)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")


def require_auth(
    request: Request,
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthPrincipal:
    settings: Settings = request.app.state.settings or Settings()
    principal = resolve_principal(settings, api_key=api_key, bearer=bearer)
    request.state.principal = principal
    return principal


def assert_user_scope(principal: AuthPrincipal, user_external_id: str) -> None:
    if not principal.user_external_id:
        return
    if principal.user_external_id != user_external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Credential is not authorized for the requested user.",
        )
