from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from meeting_assistant.core.config import Settings

_GOOGLE_LOGIN_SCOPES = "openid email profile"


@dataclass(frozen=True, slots=True)
class GoogleLoginProfile:
    sub: str
    email: str
    name: str | None = None


class GoogleLoginOAuthClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.auth_google_login_client_id or not settings.auth_google_login_client_secret:
            raise ValueError("Google login OAuth credentials are not configured.")
        self._client_id = settings.auth_google_login_client_id
        self._client_secret = settings.auth_google_login_client_secret
        self._timeout = settings.tool_http_timeout_seconds

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": _GOOGLE_LOGIN_SCOPES,
                "access_type": "online",
                "prompt": "select_account",
                "state": state,
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> GoogleLoginProfile:
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=self._timeout,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Google login token response did not include access token.")

        id_token = token_payload.get("id_token")
        if isinstance(id_token, str) and id_token:
            profile = self._profile_from_id_token(id_token)
            if profile is not None:
                return profile

        userinfo_response = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self._timeout,
        )
        userinfo_response.raise_for_status()
        return self._profile_from_userinfo(userinfo_response.json())

    @staticmethod
    def _profile_from_userinfo(payload: object) -> GoogleLoginProfile:
        if not isinstance(payload, dict):
            raise ValueError("Google login profile response was invalid.")
        subject = payload.get("sub")
        email = payload.get("email")
        if not isinstance(subject, str) or not subject:
            raise ValueError("Google login profile did not include subject.")
        if not isinstance(email, str) or not email:
            raise ValueError("Google login profile did not include email.")
        name = payload.get("name")
        return GoogleLoginProfile(
            sub=subject,
            email=email,
            name=name if isinstance(name, str) else None,
        )

    def _profile_from_id_token(self, id_token: str) -> GoogleLoginProfile | None:
        try:
            import jwt as pyjwt
        except ImportError:
            return None

        try:
            payload = pyjwt.decode(
                id_token,
                options={"verify_signature": False, "verify_aud": False},
            )
        except pyjwt.PyJWTError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return self._profile_from_userinfo(payload)
        except ValueError:
            return None


def build_google_login_oauth_client(settings: Settings) -> GoogleLoginOAuthClient | None:
    if not settings.auth_google_login_enabled:
        return None
    if not settings.auth_google_login_client_id or not settings.auth_google_login_client_secret:
        return None
    return GoogleLoginOAuthClient(settings)
