from __future__ import annotations

from urllib.parse import urlencode, urlparse

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import IntegrationProvider, IntegrationStatus, UserIntegration
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.integration import (
    ConnectIntegrationResponse,
    IntegrationCallbackResponse,
    IntegrationListResponse,
    IntegrationOption,
    IntegrationOptionsResponse,
    IntegrationSummary,
)
from meeting_assistant.services.integrations.oauth_state import issue_oauth_state, verify_oauth_state
from meeting_assistant.services.integrations.providers import (
    IntegrationOAuthProvider,
    build_integration_oauth_providers,
)
from meeting_assistant.services.token_encryption import TokenEncryptor, build_token_encryptor


class IntegrationService:
    def __init__(
        self,
        repository: Repository,
        encryptor: TokenEncryptor,
        settings: Settings,
        providers: dict[IntegrationProvider, IntegrationOAuthProvider] | None = None,
    ) -> None:
        self.repository = repository
        self.encryptor = encryptor
        self.settings = settings
        self.providers = providers or build_integration_oauth_providers(settings)

    def list_integrations(self, user_external_id: str) -> IntegrationListResponse:
        user = self._require_user(user_external_id)
        integrations = self.repository.list_user_integrations(user.id)
        return IntegrationListResponse(integrations=[self._to_summary(item) for item in integrations])

    def start_connect(
        self,
        user_external_id: str,
        provider: IntegrationProvider,
        *,
        frontend_redirect: str | None = None,
    ) -> ConnectIntegrationResponse:
        user = self._require_user(user_external_id)
        handler = self._provider_handler(provider)

        if not handler.requires_oauth:
            integration = self.repository.upsert_user_integration(
                encryptor=self.encryptor,
                user_id=user.id,
                provider=provider,
                status=IntegrationStatus.CONNECTED,
                settings_json={"notification_emails": [], "notifications_enabled": True},
            )
            return ConnectIntegrationResponse(status=integration.status.value)

        state = issue_oauth_state(
            self.settings,
            user_external_id=user.external_id,
            provider=provider.value,
            frontend_redirect=frontend_redirect,
        )
        redirect_uri = self._callback_url(provider)
        return ConnectIntegrationResponse(
            authorize_url=handler.build_authorize_url(state=state, redirect_uri=redirect_uri),
            state=state,
        )

    def handle_callback(
        self,
        provider: IntegrationProvider,
        *,
        code: str,
        state: str,
    ) -> tuple[IntegrationCallbackResponse, str | None]:
        payload = verify_oauth_state(self.settings, state)
        if payload.get("provider") != provider.value:
            raise ValueError("OAuth state provider mismatch.")

        user_external_id = str(payload["sub"])
        user = self._require_user(user_external_id)
        handler = self._provider_handler(provider)
        if not handler.requires_oauth:
            raise ValueError(f"Provider {provider.value} does not support OAuth callback.")

        redirect_uri = self._callback_url(provider)
        exchange = handler.exchange_code(code=code, redirect_uri=redirect_uri)
        settings_json = self._merge_provider_settings(
            user.id,
            provider,
            provider_account_id=exchange.provider_account_id,
            user_email=user.email,
        )
        integration = self.repository.upsert_user_integration(
            encryptor=self.encryptor,
            user_id=user.id,
            provider=provider,
            provider_account_id=exchange.provider_account_id,
            status=IntegrationStatus.CONNECTED,
            scopes=exchange.scopes,
            access_token=exchange.access_token,
            refresh_token=exchange.refresh_token,
            expires_at=exchange.expires_at,
            settings_json=settings_json,
        )
        response = IntegrationCallbackResponse(
            provider=provider.value,
            status=integration.status.value,
            provider_account_id=integration.provider_account_id,
        )
        frontend_redirect = payload.get("frontend_redirect")
        if isinstance(frontend_redirect, str) and frontend_redirect.strip():
            return response, self._append_query(
                frontend_redirect,
                {
                    "provider": provider.value,
                    "status": integration.status.value,
                    "provider_account_id": integration.provider_account_id,
                },
            )
        return response, None

    def disconnect(
        self,
        user_external_id: str,
        provider: IntegrationProvider,
        *,
        provider_account_id: str = "",
    ) -> IntegrationSummary:
        user = self._require_user(user_external_id)
        integration = self.repository.revoke_user_integration(
            user.id,
            provider,
            provider_account_id=provider_account_id,
        )
        return self._to_summary(integration)

    def update_settings(
        self,
        user_external_id: str,
        provider: IntegrationProvider,
        settings_json: dict[str, object],
        *,
        provider_account_id: str = "",
    ) -> IntegrationSummary:
        user = self._require_user(user_external_id)
        integration = self.repository.update_user_integration_settings(
            user.id,
            provider,
            settings_json,
            provider_account_id=provider_account_id,
        )
        return self._to_summary(integration)

    def get_options(
        self,
        user_external_id: str,
        provider: IntegrationProvider,
        *,
        provider_account_id: str = "",
    ) -> IntegrationOptionsResponse:
        user = self._require_user(user_external_id)
        integration = self._require_connected_integration(
            user.id,
            provider,
            provider_account_id=provider_account_id,
        )
        handler = self._provider_handler(provider)
        if not handler.requires_oauth:
            return IntegrationOptionsResponse(options=[])

        access_token, _ = self.repository.decrypt_integration_tokens(integration, encryptor=self.encryptor)
        if not access_token:
            raise ValueError(f"Integration {provider.value} is missing an access token.")

        options = [
            IntegrationOption(id=item.id, label=item.label, metadata=item.metadata)
            for item in handler.list_options(access_token=access_token)
        ]
        return IntegrationOptionsResponse(options=options)

    def _provider_handler(self, provider: IntegrationProvider) -> IntegrationOAuthProvider:
        handler = self.providers.get(provider)
        if handler is None:
            raise ValueError(f"Unsupported integration provider: {provider.value}")
        return handler

    def _require_user(self, user_external_id: str):
        user = self.repository.get_user_by_external_id(user_external_id)
        if user is None:
            raise ValueError(f"User {user_external_id} not found.")
        return user

    def _require_connected_integration(
        self,
        user_id: int,
        provider: IntegrationProvider,
        *,
        provider_account_id: str,
    ) -> UserIntegration:
        integration = self.repository.get_user_integration(
            user_id,
            provider,
            provider_account_id=provider_account_id,
        )
        if integration is None or integration.status != IntegrationStatus.CONNECTED:
            raise ValueError(f"Integration {provider.value} is not connected.")
        return integration

    def _callback_url(self, provider: IntegrationProvider) -> str:
        base = self.settings.integrations_oauth_redirect_base.rstrip("/")
        return f"{base}/api/v1/integrations/{provider.value}/callback"

    def _merge_provider_settings(
        self,
        user_id: int,
        provider: IntegrationProvider,
        *,
        provider_account_id: str,
        user_email: str,
    ) -> dict[str, object] | None:
        if provider != IntegrationProvider.GOOGLE:
            return None

        existing = self.repository.get_user_integration(
            user_id,
            provider,
            provider_account_id=provider_account_id,
        )
        settings = dict(existing.settings_json) if existing else {}
        if user_email and not settings.get("invite_email"):
            settings["invite_email"] = user_email
        settings.setdefault("calendar_ids", [])
        return settings

    @staticmethod
    def _to_summary(integration: UserIntegration) -> IntegrationSummary:
        return IntegrationSummary(
            provider=integration.provider.value,
            status=integration.status.value,
            provider_account_id=integration.provider_account_id,
            scopes=integration.scopes,
            settings_json=dict(integration.settings_json or {}),
            connected_at=integration.connected_at,
            updated_at=integration.updated_at,
            expires_at=integration.expires_at,
        )

    @staticmethod
    def _append_query(url: str, params: dict[str, str]) -> str:
        parsed = urlparse(url)
        separator = "&" if parsed.query else "?"
        return f"{url}{separator}{urlencode(params)}"


def build_integration_service(
    repository: Repository,
    settings: Settings,
) -> IntegrationService:
    return IntegrationService(
        repository=repository,
        encryptor=build_token_encryptor(settings),
        settings=settings,
    )
