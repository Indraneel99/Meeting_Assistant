from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from meeting_assistant.api.auth import AuthPrincipal, require_auth
from meeting_assistant.api.deps import get_container
from meeting_assistant.api.rate_limit import (
    auth_google_callback_rate_limit,
    auth_ip_rate_limit_key,
    auth_login_rate_limit,
    auth_register_rate_limit,
    limiter,
)
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.schemas.auth import (
    AuthConfigResponse,
    EmailLoginRequest,
    GoogleConnectResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    SessionResponse,
)
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
        password_login_enabled=settings.auth_password_login_enabled,
        google_login_enabled=settings.auth_google_login_enabled,
    )


@router.post("/register", response_model=LoginResponse)
@limiter.limit(auth_register_rate_limit, key_func=auth_ip_rate_limit_key)
def register(
    request: Request,
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    return auth_service.register(
        email=str(payload.email),
        password=payload.password,
        display_name=payload.display_name,
    )


@router.post("/login/email", response_model=LoginResponse)
@limiter.limit(auth_login_rate_limit, key_func=auth_ip_rate_limit_key)
def login_email(
    request: Request,
    payload: EmailLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    return auth_service.login_email(email=str(payload.email), password=payload.password)


@router.get("/google/connect", response_model=GoogleConnectResponse)
def google_connect(
    frontend_redirect: str | None = None,
    auth_service: AuthService = Depends(get_auth_service),
) -> GoogleConnectResponse:
    authorize_url = auth_service.google_connect(frontend_redirect=frontend_redirect)
    return GoogleConnectResponse(authorize_url=authorize_url)


@router.get("/google/callback")
@limiter.limit(auth_google_callback_rate_limit, key_func=auth_ip_rate_limit_key)
def google_callback(
    request: Request,
    code: str,
    state: str,
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    redirect_url = auth_service.google_callback(code=code, state=state)
    return RedirectResponse(url=redirect_url, status_code=302)


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
