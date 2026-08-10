from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, status

from meeting_assistant.api.auth import AuthPrincipal, parse_api_key_scopes
from meeting_assistant.core.config import Settings
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.auth import LoginResponse, SessionResponse


@dataclass(slots=True)
class AuthService:
    repository: Repository
    settings: Settings

    def issue_access_token(self, user_external_id: str) -> tuple[str, int]:
        if not self.settings.auth_jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT auth is not configured.",
            )

        expires_in = self.settings.auth_jwt_expiry_seconds
        now = datetime.now(UTC)
        payload: dict[str, object] = {
            "sub": user_external_id,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        }
        if self.settings.auth_jwt_audience:
            payload["aud"] = self.settings.auth_jwt_audience

        token = jwt.encode(
            payload,
            self.settings.auth_jwt_secret,
            algorithm=self.settings.auth_jwt_algorithm,
        )
        return token, expires_in

    def login(
        self,
        *,
        api_key: str | None,
        user_external_id: str | None,
        user_email: str | None,
    ) -> LoginResponse:
        if not self.settings.auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auth is disabled; configure user identity in the client.",
            )

        resolved_external_id: str | None = None
        resolved_email: str | None = None

        if api_key:
            scopes = parse_api_key_scopes(self.settings.auth_api_keys)
            if api_key not in scopes:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
            scoped_user = scopes[api_key]
            if scoped_user:
                resolved_external_id = scoped_user
            elif user_external_id:
                resolved_external_id = user_external_id
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user_external_id is required for unscoped API keys.",
                )
            if not user_email:
                existing = self.repository.get_user_by_external_id(resolved_external_id)
                resolved_email = existing.email if existing else f"{resolved_external_id}@example.com"
            else:
                resolved_email = user_email
        elif self.settings.auth_login_allow_dev and user_external_id and user_email:
            resolved_external_id = user_external_id
            resolved_email = user_email
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid API key or dev login credentials required.",
            )

        user = self.repository.get_or_create_user(resolved_external_id, resolved_email)
        access_token, expires_in = self.issue_access_token(user.external_id)
        return LoginResponse(
            access_token=access_token,
            expires_in=expires_in,
            user_external_id=user.external_id,
            user_email=user.email,
        )

    def session_for_principal(self, principal: AuthPrincipal) -> SessionResponse:
        if not principal.user_external_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session is not scoped to a user.",
            )
        user = self.repository.get_user_by_external_id(principal.user_external_id)
        return SessionResponse(
            user_external_id=principal.user_external_id,
            user_email=user.email if user else None,
            auth_type=principal.auth_type,
        )
