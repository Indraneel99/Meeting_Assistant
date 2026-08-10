from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from meeting_assistant.api.auth import AuthPrincipal, assert_user_scope, require_auth
from meeting_assistant.api.deps import get_container, get_settings
from meeting_assistant.container import Container
from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import IntegrationProvider
from meeting_assistant.schemas.integration import (
    ConnectIntegrationResponse,
    IntegrationCallbackResponse,
    IntegrationListResponse,
    IntegrationOptionsResponse,
    IntegrationSettingsUpdate,
    IntegrationSummary,
)

router = APIRouter(tags=["integrations"])


def _parse_provider(provider: str) -> IntegrationProvider:
    try:
        return IntegrationProvider(provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown integration provider: {provider}") from exc


def _resolve_user_external_id(
    settings: Settings,
    principal: AuthPrincipal,
    user_external_id: str | None,
) -> str:
    if principal.user_external_id:
        if user_external_id and user_external_id != principal.user_external_id:
            raise HTTPException(
                status_code=403,
                detail="Credential is not authorized for the requested user.",
            )
        return principal.user_external_id
    if not settings.auth_enabled:
        if not user_external_id:
            raise HTTPException(
                status_code=400,
                detail="user_external_id is required when auth is disabled.",
            )
        return user_external_id
    raise HTTPException(status_code=401, detail="Scoped authentication is required for integrations.")


def _integration_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message.lower():
        return HTTPException(status_code=404, detail=message)
    if "not connected" in message.lower() or "missing" in message.lower():
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=400, detail=message)


@router.get("/integrations", response_model=IntegrationListResponse)
def list_integrations(
    request: Request,
    user_external_id: str | None = None,
    settings: Settings = Depends(get_settings),
    principal: AuthPrincipal = Depends(require_auth),
    container: Container = Depends(get_container),
) -> IntegrationListResponse:
    resolved_user = _resolve_user_external_id(settings, principal, user_external_id)
    assert_user_scope(principal, resolved_user)
    return container.integration_service.list_integrations(resolved_user)


@router.get("/integrations/{provider}/connect", response_model=ConnectIntegrationResponse)
def connect_integration(
    request: Request,
    provider: str,
    user_external_id: str | None = None,
    frontend_redirect: str | None = None,
    settings: Settings = Depends(get_settings),
    principal: AuthPrincipal = Depends(require_auth),
    container: Container = Depends(get_container),
) -> ConnectIntegrationResponse:
    resolved_user = _resolve_user_external_id(settings, principal, user_external_id)
    assert_user_scope(principal, resolved_user)
    try:
        return container.integration_service.start_connect(
            resolved_user,
            _parse_provider(provider),
            frontend_redirect=frontend_redirect,
        )
    except ValueError as exc:
        raise _integration_error(exc) from exc


@router.get("/integrations/{provider}/callback", response_model=IntegrationCallbackResponse)
def integration_oauth_callback(
    provider: str,
    code: str,
    state: str,
    container: Container = Depends(get_container),
):
    try:
        response, redirect_url = container.integration_service.handle_callback(
            _parse_provider(provider),
            code=code,
            state=state,
        )
    except ValueError as exc:
        raise _integration_error(exc) from exc

    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=302)
    return response


@router.delete("/integrations/{provider}", response_model=IntegrationSummary)
def disconnect_integration(
    request: Request,
    provider: str,
    user_external_id: str | None = None,
    provider_account_id: str = Query(default=""),
    settings: Settings = Depends(get_settings),
    principal: AuthPrincipal = Depends(require_auth),
    container: Container = Depends(get_container),
) -> IntegrationSummary:
    resolved_user = _resolve_user_external_id(settings, principal, user_external_id)
    assert_user_scope(principal, resolved_user)
    try:
        return container.integration_service.disconnect(
            resolved_user,
            _parse_provider(provider),
            provider_account_id=provider_account_id,
        )
    except ValueError as exc:
        raise _integration_error(exc) from exc


@router.patch("/integrations/{provider}/settings", response_model=IntegrationSummary)
def update_integration_settings(
    request: Request,
    provider: str,
    payload: IntegrationSettingsUpdate,
    user_external_id: str | None = None,
    provider_account_id: str = Query(default=""),
    settings: Settings = Depends(get_settings),
    principal: AuthPrincipal = Depends(require_auth),
    container: Container = Depends(get_container),
) -> IntegrationSummary:
    resolved_user = _resolve_user_external_id(settings, principal, user_external_id)
    assert_user_scope(principal, resolved_user)
    try:
        return container.integration_service.update_settings(
            resolved_user,
            _parse_provider(provider),
            payload.settings_json,
            provider_account_id=provider_account_id,
        )
    except ValueError as exc:
        raise _integration_error(exc) from exc


@router.get("/integrations/{provider}/options", response_model=IntegrationOptionsResponse)
def list_integration_options(
    request: Request,
    provider: str,
    user_external_id: str | None = None,
    provider_account_id: str = Query(default=""),
    settings: Settings = Depends(get_settings),
    principal: AuthPrincipal = Depends(require_auth),
    container: Container = Depends(get_container),
) -> IntegrationOptionsResponse:
    resolved_user = _resolve_user_external_id(settings, principal, user_external_id)
    assert_user_scope(principal, resolved_user)
    try:
        return container.integration_service.get_options(
            resolved_user,
            _parse_provider(provider),
            provider_account_id=provider_account_id,
        )
    except ValueError as exc:
        raise _integration_error(exc) from exc
