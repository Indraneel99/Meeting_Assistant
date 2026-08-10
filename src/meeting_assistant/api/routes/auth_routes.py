from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from meeting_assistant.api.auth import AuthPrincipal, require_auth
from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.schemas.auth import AuthConfigResponse, LoginRequest, LoginResponse, SessionResponse
from meeting_assistant.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings or Settings()


def get_auth_service(container: Container = Depends(get_container), settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(repository=container.repository, settings=settings)


@router.get("/config", response_model=AuthConfigResponse)
def auth_config(settings: Settings = Depends(get_settings)) -> AuthConfigResponse:
    return AuthConfigResponse(
        auth_enabled=settings.auth_enabled,
        login_allow_dev=settings.auth_login_allow_dev,
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, auth_service: AuthService = Depends(get_auth_service)) -> LoginResponse:
    return auth_service.login(
        api_key=payload.api_key,
        user_external_id=payload.user_external_id,
        user_email=str(payload.user_email) if payload.user_email else None,
    )


@router.get("/me", response_model=SessionResponse)
def current_session(
    principal: AuthPrincipal = Depends(require_auth),
    auth_service: AuthService = Depends(get_auth_service),
) -> SessionResponse:
    return auth_service.session_for_principal(principal)
