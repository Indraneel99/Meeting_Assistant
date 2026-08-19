from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret_file(path: str | Path) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8").strip()


def _settings_env_files() -> tuple[str, ...]:
    """Load optional override file first, then `.env` (later entries win in pydantic-settings)."""
    files: list[str] = []
    override = os.getenv("MEETING_ASSISTANT_ENV_FILE", "").strip()
    if override:
        files.append(override)
    files.append(".env")
    return tuple(dict.fromkeys(files))


class Settings(BaseSettings):
    # --- Data layer ---
    database_url: str = "sqlite:///./meeting_assistant.db"
    database_url_file: str | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # --- Embeddings ---
    embedding_provider: str = "heuristic"
    embedding_fallback_provider: str = "heuristic"
    embedding_dimensions: int = 1536
    embedding_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEETING_ASSISTANT_EMBEDDING_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    embedding_openai_api_key_file: str | None = None
    embedding_openai_base_url: str = "https://api.openai.com/v1"
    embedding_openai_model: str = "text-embedding-3-small"
    embedding_openai_timeout_seconds: float = 30.0
    chunk_size_words: int = 120
    recent_summary_limit: int = 3
    semantic_context_limit: int = 5

    # --- Query / RAG ---
    query_provider: str = "heuristic"
    query_openai_model: str = "gpt-5.4-mini"
    query_top_k_meetings: int = 3
    query_top_k_chunks: int = 5
    query_top_k_decisions: int = 3

    # --- Agent / planner ---
    max_tool_calls_per_session: int = 10
    llm_provider: str = "heuristic"
    llm_fallback_provider: str = "heuristic"
    llm_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEETING_ASSISTANT_LLM_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    llm_openai_api_key_file: str | None = None
    llm_openai_base_url: str = "https://api.openai.com/v1"
    llm_openai_model: str = "gpt-5.4-mini"
    llm_openai_timeout_seconds: float = 90.0
    openai_api_key_file: str | None = Field(
        default=None,
        description="Shared OpenAI key file used when per-service keys are unset.",
    )

    # --- Tool execution ---
    tool_execution_max_retries: int = 3
    tool_execution_backoff_seconds: float = 1.0
    tool_execution_backoff_mode: str = "inline"
    tool_http_timeout_seconds: float = 30.0

    # --- Email ---
    email_provider: str = "stub"
    email_sendgrid_api_key: str | None = None
    email_sendgrid_api_key_file: str | None = None
    email_from_address: str = "noreply@example.com"
    email_from_name: str = "Meeting Assistant"
    email_default_recipient: str | None = None

    # --- Calendar ---
    calendar_provider: str = "stub"
    calendar_google_service_account_json: str | None = None
    calendar_google_service_account_json_file: str | None = None
    calendar_google_calendar_id: str = "primary"
    calendar_google_impersonate_subject: str | None = None
    calendar_assistant_organizer_name: str = "Meeting Assistant"

    # --- Slack ---
    slack_provider: str = "stub"
    slack_webhook_url: str | None = None
    slack_webhook_url_file: str | None = None
    slack_bot_token: str | None = None
    slack_bot_token_file: str | None = None
    slack_default_channel: str | None = None
    slack_bot_display_name: str = "Meeting Assistant"

    # --- Jira ---
    jira_provider: str = "stub"
    jira_base_url: str | None = None
    jira_user_email: str | None = None
    jira_api_token: str | None = None
    jira_api_token_file: str | None = None
    jira_project_key: str | None = None
    jira_default_issue_type: str = "Task"

    # --- ASR ---
    asr_provider: str = "openai"
    asr_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEETING_ASSISTANT_ASR_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    asr_openai_api_key_file: str | None = None
    asr_openai_base_url: str = "https://api.openai.com/v1"
    asr_openai_model: str = "gpt-4o-transcribe-diarize"
    asr_openai_language: str | None = None
    asr_openai_timeout_seconds: float = 120.0
    asr_openai_chunking_strategy: str = "auto"
    asr_upload_backend: str = "local"
    asr_upload_dir: str = "./uploads/audio"
    asr_max_upload_bytes: int = 100 * 1024 * 1024
    asr_s3_bucket: str | None = None
    asr_s3_region: str | None = None
    asr_s3_upload_prefix: str = "audio/"
    asr_gcs_bucket: str | None = None
    asr_gcs_upload_prefix: str = "audio/"

    # --- Async / queues ---
    batch_processing_mode: str = "sync"
    queue_provider: str = "memory"
    job_queue_provider: str = "inprocess"
    redis_url: str = "redis://localhost:6379/0"
    pubsub_topic: str | None = None
    pubsub_project: str | None = None
    pubsub_emulator_host: str | None = None
    pubsub_push_audience: str | None = None
    pubsub_push_skip_auth: bool = False

    # --- Auth ---
    auth_enabled: bool = False
    auth_mode: str = "api_key"
    auth_api_keys: str = ""
    auth_api_keys_file: str | None = None
    auth_jwt_secret: str | None = None
    auth_jwt_secret_file: str | None = None
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_audience: str | None = None
    auth_jwt_expiry_seconds: int = 3600
    auth_login_allow_dev: bool = False
    auth_password_login_enabled: bool = True
    auth_google_login_enabled: bool = False
    auth_google_login_client_id: str | None = None
    auth_google_login_client_secret: str | None = None
    auth_google_login_client_secret_file: str | None = None
    auth_google_login_redirect_base: str = "http://127.0.0.1:8000"
    auth_rate_limit_register: str = "10/hour"
    auth_rate_limit_login: str = "20/minute"
    auth_rate_limit_google_callback: str = "30/minute"

    # --- Approval locking ---
    approval_lock_ttl_seconds: int = 120

    # --- User integrations (Phase 13) ---
    integrations_encryption_key: str | None = None
    integrations_encryption_key_file: str | None = None
    integrations_oauth_redirect_base: str = "http://127.0.0.1:8000"
    integrations_oauth_state_secret: str | None = None
    slack_oauth_client_id: str | None = None
    slack_oauth_client_secret: str | None = None
    slack_oauth_client_secret_file: str | None = None
    slack_oauth_scopes: str = "chat:write,channels:read,groups:read"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_client_secret_file: str | None = None
    google_oauth_scopes: str = "openid email profile https://www.googleapis.com/auth/calendar.readonly"

    # --- Observability / limits ---
    log_level: str = "INFO"
    log_json: bool = False
    otel_enabled: bool = False
    otel_service_name: str = "meeting-assistant"
    otel_worker_service_name: str = "meeting-assistant-worker"
    otel_exporter_endpoint: str | None = None
    rate_limit_enabled: bool = False
    rate_limit_default: str = "120/minute"
    rate_limit_batch: str = "10/minute"
    rate_limit_query: str = "30/minute"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    readiness_check_redis: bool = True
    readiness_check_embedder: bool = False
    readiness_check_worker: bool = True
    worker_health_check_interval_seconds: int = 30
    arq_queue_name: str | None = None
    arq_health_check_key: str | None = None
    stale_workflow_alert_enabled: bool = True
    stale_workflow_threshold_minutes: int = 15
    failed_tool_alert_enabled: bool = True
    failed_tool_alert_lookback_minutes: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        if not self.cors_origins.strip():
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_file_encoding="utf-8",
        env_prefix="MEETING_ASSISTANT_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _hydrate_from_files(self) -> Self:
        shared_openai_key = self._resolve_optional_file(self.openai_api_key_file)

        if self.database_url_file and self.database_url == Settings.model_fields["database_url"].default:
            object.__setattr__(self, "database_url", _read_secret_file(self.database_url_file))

        if shared_openai_key:
            if self.llm_openai_api_key is None:
                object.__setattr__(self, "llm_openai_api_key", shared_openai_key)
            if self.embedding_openai_api_key is None:
                object.__setattr__(self, "embedding_openai_api_key", shared_openai_key)
            if self.asr_openai_api_key is None:
                object.__setattr__(self, "asr_openai_api_key", shared_openai_key)

        self._apply_file_override("llm_openai_api_key", self.llm_openai_api_key_file)
        self._apply_file_override("embedding_openai_api_key", self.embedding_openai_api_key_file)
        self._apply_file_override("asr_openai_api_key", self.asr_openai_api_key_file)
        self._apply_file_override("auth_api_keys", self.auth_api_keys_file)
        self._apply_file_override("auth_jwt_secret", self.auth_jwt_secret_file)
        self._apply_file_override("auth_google_login_client_secret", self.auth_google_login_client_secret_file)
        self._apply_file_override("integrations_encryption_key", self.integrations_encryption_key_file)
        self._apply_file_override("slack_oauth_client_secret", self.slack_oauth_client_secret_file)
        self._apply_file_override("google_oauth_client_secret", self.google_oauth_client_secret_file)
        self._apply_file_override("email_sendgrid_api_key", self.email_sendgrid_api_key_file)
        self._apply_file_override("calendar_google_service_account_json", self.calendar_google_service_account_json_file)
        self._apply_file_override("jira_api_token", self.jira_api_token_file)
        self._apply_file_override("slack_webhook_url", self.slack_webhook_url_file)
        self._apply_file_override("slack_bot_token", self.slack_bot_token_file)
        return self

    def _resolve_optional_file(self, path: str | None) -> str | None:
        if not path:
            return None
        return _read_secret_file(path)

    def _apply_file_override(self, field_name: str, file_path: str | None) -> None:
        if not file_path:
            return
        current = getattr(self, field_name)
        default = Settings.model_fields[field_name].default
        if current in (None, "", default):
            object.__setattr__(self, field_name, _read_secret_file(file_path))


@lru_cache
def get_settings() -> Settings:
    return Settings()
