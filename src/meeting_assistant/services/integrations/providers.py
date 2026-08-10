from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import httpx

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import IntegrationProvider

STUB_OAUTH_CODE = "stub-oauth-code"


@dataclass(slots=True)
class OAuthExchangeResult:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None
    provider_account_id: str


@dataclass(slots=True)
class IntegrationOptionItem:
    id: str
    label: str
    metadata: dict[str, object]


class IntegrationOAuthProvider(Protocol):
    provider: IntegrationProvider
    requires_oauth: bool

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthExchangeResult: ...

    def list_options(self, *, access_token: str) -> list[IntegrationOptionItem]: ...


class EmailPrefsProvider:
    provider = IntegrationProvider.EMAIL_PREFS
    requires_oauth = False

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        raise NotImplementedError("Email preferences do not use OAuth.")

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthExchangeResult:
        raise NotImplementedError("Email preferences do not use OAuth.")

    def list_options(self, *, access_token: str) -> list[IntegrationOptionItem]:
        return []


class StubOAuthProvider:
    def __init__(self, provider: IntegrationProvider) -> None:
        self.provider = provider
        self.requires_oauth = True

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode({"code": STUB_OAUTH_CODE, "state": state})
        separator = "&" if "?" in redirect_uri else "?"
        return f"{redirect_uri}{separator}{query}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthExchangeResult:
        if code != STUB_OAUTH_CODE:
            raise ValueError("Invalid OAuth authorization code.")
        account_id = {
            IntegrationProvider.SLACK: "T-STUB",
            IntegrationProvider.GOOGLE: "google-sub-stub",
            IntegrationProvider.JIRA: "jira-site-stub",
        }[self.provider]
        return OAuthExchangeResult(
            access_token=f"stub-access-{self.provider.value}",
            refresh_token=f"stub-refresh-{self.provider.value}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes='["stub"]',
            provider_account_id=account_id,
        )

    def list_options(self, *, access_token: str) -> list[IntegrationOptionItem]:
        if self.provider == IntegrationProvider.SLACK:
            return [
                IntegrationOptionItem(id="C001", label="#product", metadata={"is_private": False}),
                IntegrationOptionItem(id="C002", label="#general", metadata={"is_private": False}),
            ]
        if self.provider == IntegrationProvider.GOOGLE:
            return [
                IntegrationOptionItem(id="primary", label="Primary Calendar", metadata={}),
            ]
        return []


class SlackOAuthProvider:
    provider = IntegrationProvider.SLACK
    requires_oauth = True

    def __init__(self, settings: Settings) -> None:
        if not settings.slack_oauth_client_id or not settings.slack_oauth_client_secret:
            raise ValueError("Slack OAuth credentials are not configured.")
        self._client_id = settings.slack_oauth_client_id
        self._client_secret = settings.slack_oauth_client_secret
        self._scopes = settings.slack_oauth_scopes
        self._timeout = settings.tool_http_timeout_seconds

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "scope": self._scopes,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"https://slack.com/oauth/v2/authorize?{query}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthExchangeResult:
        response = httpx.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise ValueError(str(payload.get("error", "Slack OAuth token exchange failed.")))

        team = payload.get("team") or {}
        team_id = team.get("id")
        if not isinstance(team_id, str) or not team_id:
            raise ValueError("Slack OAuth response did not include team id.")

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Slack OAuth response did not include access token.")

        scope = payload.get("scope")
        return OAuthExchangeResult(
            access_token=access_token,
            refresh_token=None,
            expires_at=None,
            scopes=str(scope) if scope is not None else None,
            provider_account_id=team_id,
        )

    def list_options(self, *, access_token: str) -> list[IntegrationOptionItem]:
        channel_types = ("public_channel,private_channel", "public_channel")
        last_error = "Slack channel list failed."

        for types in channel_types:
            response = httpx.get(
                "https://slack.com/api/conversations.list",
                params={"types": types, "exclude_archived": "true", "limit": 200},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok"):
                return self._slack_channel_options(payload)

            last_error = str(payload.get("error", last_error))
            if last_error == "missing_scope" and types != channel_types[-1]:
                continue
            break

        raise ValueError(last_error)

    @staticmethod
    def _slack_channel_options(payload: dict[str, object]) -> list[IntegrationOptionItem]:
        options: list[IntegrationOptionItem] = []
        for channel in payload.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            channel_id = channel.get("id")
            name = channel.get("name")
            if not isinstance(channel_id, str) or not isinstance(name, str):
                continue
            options.append(
                IntegrationOptionItem(
                    id=channel_id,
                    label=f"#{name}",
                    metadata={"is_private": bool(channel.get("is_private"))},
                )
            )
        return options


class GoogleOAuthProvider:
    provider = IntegrationProvider.GOOGLE
    requires_oauth = True

    def __init__(self, settings: Settings) -> None:
        if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
            raise ValueError("Google OAuth credentials are not configured.")
        self._client_id = settings.google_oauth_client_id
        self._client_secret = settings.google_oauth_client_secret
        self._scopes = settings.google_oauth_scopes
        self._timeout = settings.tool_http_timeout_seconds

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": self._scopes,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthExchangeResult:
        response = httpx.post(
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
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Google OAuth response did not include access token.")

        expires_in = payload.get("expires_in")
        expires_at = None
        if isinstance(expires_in, int):
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        refresh_token = payload.get("refresh_token")
        userinfo = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self._timeout,
        )
        userinfo.raise_for_status()
        profile = userinfo.json()
        subject = profile.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("Google OAuth profile did not include subject.")

        scope = payload.get("scope")
        return OAuthExchangeResult(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            expires_at=expires_at,
            scopes=str(scope) if scope is not None else None,
            provider_account_id=subject,
        )

    def list_options(self, *, access_token: str) -> list[IntegrationOptionItem]:
        response = httpx.get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        options: list[IntegrationOptionItem] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            calendar_id = item.get("id")
            summary = item.get("summary")
            if not isinstance(calendar_id, str) or not isinstance(summary, str):
                continue
            options.append(
                IntegrationOptionItem(
                    id=calendar_id,
                    label=summary,
                    metadata={"primary": bool(item.get("primary"))},
                )
            )
        return options


def build_integration_oauth_providers(settings: Settings) -> dict[IntegrationProvider, IntegrationOAuthProvider]:
    providers: dict[IntegrationProvider, IntegrationOAuthProvider] = {
        IntegrationProvider.EMAIL_PREFS: EmailPrefsProvider(),
    }

    if settings.slack_oauth_client_id and settings.slack_oauth_client_secret:
        providers[IntegrationProvider.SLACK] = SlackOAuthProvider(settings)
    else:
        providers[IntegrationProvider.SLACK] = StubOAuthProvider(IntegrationProvider.SLACK)

    if settings.google_oauth_client_id and settings.google_oauth_client_secret:
        providers[IntegrationProvider.GOOGLE] = GoogleOAuthProvider(settings)
    else:
        providers[IntegrationProvider.GOOGLE] = StubOAuthProvider(IntegrationProvider.GOOGLE)

    providers[IntegrationProvider.JIRA] = StubOAuthProvider(IntegrationProvider.JIRA)
    return providers
