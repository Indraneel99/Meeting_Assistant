from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException, status

from meeting_assistant.api.auth import AuthPrincipal, parse_api_key_scopes
from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import AuthProvider, User
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.auth import LoginResponse, SessionResponse
from meeting_assistant.services.auth_identity import normalize_auth_email
from meeting_assistant.services.google_login_oauth import (
    GoogleLoginOAuthClient,
    GoogleLoginProfile,
    build_google_login_oauth_client,
)
from meeting_assistant.services.integrations.oauth_state import issue_google_login_state, verify_google_login_state
from meeting_assistant.services.password import hash_password, validate_password_strength, verify_password


@dataclass(slots=True)
class AuthService:
    repository: Repository
    settings: Settings
    google_login_client: GoogleLoginOAuthClient | None = None

    def __post_init__(self) -> None:
        if self.google_login_client is None:
            object.__setattr__(
                self,
                "google_login_client",
                build_google_login_oauth_client(self.settings),
            )

    def _google_login_callback_url(self) -> str:
        base = self.settings.auth_google_login_redirect_base.rstrip("/")
        return f"{base}/api/v1/auth/google/callback"

    def google_connect(self, *, frontend_redirect: str | None = None) -> str:
        if not self.settings.auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auth is disabled.",
            )
        if not self.settings.auth_google_login_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google login is disabled.",
            )
        if self.google_login_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google login is not configured.",
            )

        state = issue_google_login_state(self.settings, frontend_redirect=frontend_redirect)
        return self.google_login_client.build_authorize_url(
            state=state,
            redirect_uri=self._google_login_callback_url(),
        )

    def google_callback(self, *, code: str, state: str) -> str:
        if not self.settings.auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auth is disabled.",
            )
        if not self.settings.auth_google_login_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google login is disabled.",
            )
        if self.google_login_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google login is not configured.",
            )

        try:
            state_payload = verify_google_login_state(self.settings, state)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        try:
            profile = self.google_login_client.exchange_code(
                code=code,
                redirect_uri=self._google_login_callback_url(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google login token exchange failed.",
            ) from exc

        user = self._resolve_google_login_user(profile)
        access_token, expires_in = self.issue_access_token(user.external_id)

        frontend_redirect = state_payload.get("frontend_redirect")
        redirect_base = (
            frontend_redirect.strip()
            if isinstance(frontend_redirect, str) and frontend_redirect.strip()
            else "http://localhost:5173/login"
        )
        fragment = urlencode(
            {
                "access_token": access_token,
                "expires_in": str(expires_in),
                "token_type": "bearer",
                "user_external_id": user.external_id,
            }
        )
        return f"{redirect_base}#{fragment}"

    def _resolve_google_login_user(self, profile: GoogleLoginProfile) -> User:
        existing_identity = self.repository.get_auth_identity(AuthProvider.GOOGLE, profile.sub)
        if existing_identity is not None:
            user = self.repository.get_user_by_id(existing_identity.user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Google login identity is orphaned.",
                )
            return user

        normalized_email = normalize_auth_email(profile.email)
        metadata: dict[str, object] = {}
        if profile.name:
            metadata["name"] = profile.name

        user = self.repository.get_user_by_email(normalized_email)
        if user is not None:
            self.repository.link_auth_identity_to_user(
                user.id,
                provider=AuthProvider.GOOGLE,
                provider_subject=profile.sub,
                metadata_json=metadata or None,
            )
            return user

        user, _ = self.repository.create_user_with_auth_identity(
            email=normalized_email,
            provider=AuthProvider.GOOGLE,
            provider_subject=profile.sub,
            metadata_json=metadata or None,
        )
        return user

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

    def register(self, *, email: str, password: str, display_name: str | None = None) -> LoginResponse:
        if not self.settings.auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auth is disabled.",
            )
        if not self.settings.auth_password_login_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email and password registration is disabled.",
            )

        normalized_email = normalize_auth_email(email)
        validate_password_strength(password)

        if self.repository.get_user_by_email(normalized_email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )
        if self.repository.get_auth_identity(AuthProvider.EMAIL_PASSWORD, normalized_email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        metadata: dict[str, object] = {}
        if display_name:
            metadata["display_name"] = display_name.strip()

        user, _ = self.repository.create_user_with_auth_identity(
            email=normalized_email,
            provider=AuthProvider.EMAIL_PASSWORD,
            provider_subject=normalized_email,
            password_hash=hash_password(password),
            metadata_json=metadata or None,
        )
        access_token, expires_in = self.issue_access_token(user.external_id)
        return LoginResponse(
            access_token=access_token,
            expires_in=expires_in,
            user_external_id=user.external_id,
            user_email=user.email,
        )

    def login_email(self, *, email: str, password: str) -> LoginResponse:
        if not self.settings.auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auth is disabled.",
            )
        if not self.settings.auth_password_login_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email and password login is disabled.",
            )

        normalized_email = normalize_auth_email(email)
        identity = self.repository.get_auth_identity(AuthProvider.EMAIL_PASSWORD, normalized_email)
        if identity is None or not identity.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        if not verify_password(password, identity.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        user = self.repository.get_user_by_id(identity.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        access_token, expires_in = self.issue_access_token(user.external_id)
        return LoginResponse(
            access_token=access_token,
            expires_in=expires_in,
            user_external_id=user.external_id,
            user_email=user.email,
        )
