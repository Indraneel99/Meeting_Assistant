from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IntegrationSummary(BaseModel):
    provider: str
    status: str
    provider_account_id: str
    scopes: str | None = None
    settings_json: dict[str, object] = Field(default_factory=dict)
    connected_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class IntegrationListResponse(BaseModel):
    integrations: list[IntegrationSummary] = Field(default_factory=list)


class ConnectIntegrationResponse(BaseModel):
    authorize_url: str | None = None
    state: str | None = None
    status: str | None = None


class IntegrationSettingsUpdate(BaseModel):
    settings_json: dict[str, object]


class IntegrationOption(BaseModel):
    id: str
    label: str
    metadata: dict[str, object] = Field(default_factory=dict)


class IntegrationOptionsResponse(BaseModel):
    options: list[IntegrationOption] = Field(default_factory=list)


class IntegrationCallbackResponse(BaseModel):
    provider: str
    status: str
    provider_account_id: str
