from __future__ import annotations

import httpx

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import IntegrationProvider, IntegrationStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.services.token_encryption import TokenEncryptor, build_token_encryptor
from meeting_assistant.services.tools.base import ToolProvider
from meeting_assistant.services.tools.google_auth import build_google_access_token_provider
from meeting_assistant.services.tools.providers.calendar import AssistantCalendarToolProvider
from meeting_assistant.services.tools.providers.email import UserEmailToolProvider
from meeting_assistant.services.tools.providers.slack import UserSlackToolProvider

USER_INTEGRATION_TOOLS: frozenset[str] = frozenset(
    {"slack.notify", "email.send", "calendar.create_event"}
)


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _read_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


class UserToolProviderFactory:
    """Resolve per-user tool providers from connected integrations."""

    def __init__(
        self,
        repository: Repository,
        *,
        encryptor: TokenEncryptor,
        settings: Settings,
        http_client: httpx.Client,
    ) -> None:
        self.repository = repository
        self.encryptor = encryptor
        self.settings = settings
        self.http_client = http_client

    def for_user(self, user_id: int, tool_name: str) -> ToolProvider | None:
        if tool_name == "slack.notify":
            return self.slack_provider_for_user(user_id)
        if tool_name == "email.send":
            return self.email_provider_for_user(user_id)
        if tool_name == "calendar.create_event":
            return self.calendar_provider_for_user(user_id)
        return None

    def for_workflow(self, workflow_run_id: int, tool_name: str) -> ToolProvider | None:
        user_id = self.repository.get_user_id_for_workflow(workflow_run_id)
        if user_id is None:
            return None
        return self.for_user(user_id, tool_name)

    def available_tools(self, user_id: int) -> frozenset[str]:
        """Tools the planner may suggest for this user (connected integrations + deploy fallback)."""
        has_any_integration = self._user_has_any_integration(user_id)
        tools: set[str] = set()
        if self._tool_available(
            user_id,
            "slack.notify",
            user_connected=self.user_has_connected_slack(user_id),
            deploy_kind="slack",
            has_any_integration=has_any_integration,
        ):
            tools.add("slack.notify")
        if self._tool_available(
            user_id,
            "email.send",
            user_connected=self.user_has_email_preferences(user_id),
            deploy_kind="email",
            has_any_integration=has_any_integration,
        ):
            tools.add("email.send")
        if self._tool_available(
            user_id,
            "calendar.create_event",
            user_connected=self.calendar_provider_for_user(user_id) is not None,
            deploy_kind="calendar",
            has_any_integration=has_any_integration,
        ):
            tools.add("calendar.create_event")
        return frozenset(tools)

    def user_integration_connected(self, user_id: int, tool_name: str) -> bool:
        return self.for_user(user_id, tool_name) is not None

    def _user_has_any_integration(self, user_id: int) -> bool:
        return (
            self.user_has_connected_slack(user_id)
            or self.user_has_email_preferences(user_id)
            or self.user_has_connected_google(user_id)
        )

    def _tool_available(
        self,
        user_id: int,
        tool_name: str,
        *,
        user_connected: bool,
        deploy_kind: str,
        has_any_integration: bool,
    ) -> bool:
        del user_id, tool_name
        if user_connected:
            return True
        deploy_provider = {
            "slack": self.settings.slack_provider,
            "email": self.settings.email_provider,
            "calendar": self.settings.calendar_provider,
        }[deploy_kind]
        if deploy_provider != "stub":
            return True
        return not has_any_integration

    def _deploy_fallback_available(self, kind: str) -> bool:
        provider = {
            "slack": self.settings.slack_provider,
            "email": self.settings.email_provider,
            "calendar": self.settings.calendar_provider,
        }[kind]
        # Stub deploy providers remain valid org fallback for local dev and single-tenant setups.
        return provider in {"stub", "webhook", "api", "sendgrid", "google"}

    def slack_provider_for_user(self, user_id: int) -> UserSlackToolProvider | None:
        integration = self.repository.get_connected_integration(user_id, IntegrationProvider.SLACK)
        if integration is None:
            return None

        access_token, _ = self.repository.decrypt_integration_tokens(integration, encryptor=self.encryptor)
        if not access_token:
            return None

        allowed_channels = _read_string_list(integration.settings_json.get("channels"))
        return UserSlackToolProvider(
            bot_token=access_token,
            workspace_id=integration.provider_account_id,
            allowed_channels=allowed_channels,
            http_client=self.http_client,
            bot_display_name=self.settings.slack_bot_display_name,
        )

    def user_has_connected_slack(self, user_id: int) -> bool:
        integration = self.repository.get_connected_integration(user_id, IntegrationProvider.SLACK)
        return integration is not None and integration.status == IntegrationStatus.CONNECTED

    def email_provider_for_user(self, user_id: int) -> UserEmailToolProvider | None:
        integration = self.repository.get_connected_integration(user_id, IntegrationProvider.EMAIL_PREFS)
        if integration is None:
            return None

        settings_json = integration.settings_json or {}
        if not _read_bool(settings_json.get("notifications_enabled"), default=True):
            return None

        recipients = _read_string_list(settings_json.get("notification_emails"))
        if not recipients:
            return None

        user = self.repository.get_user_by_id(user_id)
        api_key = None
        if self.settings.email_provider == "sendgrid":
            api_key = self.settings.email_sendgrid_api_key

        return UserEmailToolProvider(
            recipients=recipients,
            from_email=self.settings.email_from_address,
            from_name=self.settings.email_from_name,
            http_client=self.http_client,
            api_key=api_key,
            reply_to=user.email if user else None,
        )

    def user_has_email_preferences(self, user_id: int) -> bool:
        return self.email_provider_for_user(user_id) is not None

    def calendar_provider_for_user(self, user_id: int) -> AssistantCalendarToolProvider | None:
        integration = self.repository.get_connected_integration(user_id, IntegrationProvider.GOOGLE)
        if integration is None:
            return None

        user = self.repository.get_user_by_id(user_id)
        settings_json = integration.settings_json or {}
        invite_email = settings_json.get("invite_email")
        if not isinstance(invite_email, str) or not invite_email.strip():
            invite_email = user.email if user else None
        if not isinstance(invite_email, str) or not invite_email.strip():
            return None

        access_token_provider = None
        if (
            self.settings.calendar_provider == "google"
            and self.settings.calendar_google_service_account_json
        ):
            access_token_provider = build_google_access_token_provider(
                service_account_json=self.settings.calendar_google_service_account_json,
                impersonate_subject=self.settings.calendar_google_impersonate_subject,
            )

        return AssistantCalendarToolProvider(
            access_token_provider=access_token_provider,
            assistant_calendar_id=self.settings.calendar_google_calendar_id,
            invite_email=invite_email.strip(),
            http_client=self.http_client,
            organizer_name=self.settings.calendar_assistant_organizer_name,
        )

    def user_has_connected_google(self, user_id: int) -> bool:
        integration = self.repository.get_connected_integration(user_id, IntegrationProvider.GOOGLE)
        return integration is not None and integration.status == IntegrationStatus.CONNECTED


def build_user_tool_provider_factory(
    repository: Repository,
    settings: Settings,
    *,
    http_client: httpx.Client,
) -> UserToolProviderFactory:
    return UserToolProviderFactory(
        repository,
        encryptor=build_token_encryptor(settings),
        settings=settings,
        http_client=http_client,
    )
