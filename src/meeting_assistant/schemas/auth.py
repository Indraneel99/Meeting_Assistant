from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    api_key: str | None = Field(default=None, min_length=1)
    user_external_id: str | None = Field(default=None, min_length=1)
    user_email: EmailStr | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_external_id: str
    user_email: str


class SessionResponse(BaseModel):
    user_external_id: str
    user_email: str | None
    auth_type: str


class AuthConfigResponse(BaseModel):
    auth_enabled: bool
    login_allow_dev: bool
    password_login_enabled: bool
    google_login_enabled: bool


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = Field(default=None, max_length=255)


class GoogleConnectResponse(BaseModel):
    authorize_url: str


class EmailLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
