from fastapi import Request

from meeting_assistant.api.auth import AuthPrincipal
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings or Settings()


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_principal(request: Request) -> AuthPrincipal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return AuthPrincipal(auth_type="disabled", user_external_id=None)
    return principal
