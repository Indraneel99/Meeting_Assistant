from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./meeting_assistant.db"
    database_pool_size: int = 5
    database_max_overflow: int = 10
    embedding_provider: str = "heuristic"
    embedding_fallback_provider: str = "heuristic"
    embedding_dimensions: int = 1536
    embedding_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEETING_ASSISTANT_EMBEDDING_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    embedding_openai_base_url: str = "https://api.openai.com/v1"
    embedding_openai_model: str = "text-embedding-3-small"
    embedding_openai_timeout_seconds: float = 30.0
    chunk_size_words: int = 120
    recent_summary_limit: int = 3
    semantic_context_limit: int = 5
    query_provider: str = "heuristic"
    query_openai_model: str = "gpt-5.4-mini"
    query_top_k_meetings: int = 3
    query_top_k_chunks: int = 5
    query_top_k_decisions: int = 3
    max_tool_calls_per_session: int = 10
    llm_provider: str = "openai"
    llm_fallback_provider: str = "heuristic"
    llm_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEETING_ASSISTANT_LLM_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    llm_openai_base_url: str = "https://api.openai.com/v1"
    llm_openai_model: str = "gpt-5.4-mini"
    llm_openai_timeout_seconds: float = 90.0
    tool_execution_max_retries: int = 3
    tool_execution_backoff_seconds: float = 1.0
    tool_execution_backoff_mode: str = "inline"
    tool_http_timeout_seconds: float = 30.0
    email_provider: str = "stub"
    email_sendgrid_api_key: str | None = None
    email_from_address: str = "noreply@example.com"
    email_default_recipient: str | None = None
    calendar_provider: str = "stub"
    calendar_google_service_account_json: str | None = None
    calendar_google_calendar_id: str = "primary"
    calendar_google_impersonate_subject: str | None = None
    slack_provider: str = "stub"
    slack_webhook_url: str | None = None
    slack_bot_token: str | None = None
    slack_default_channel: str | None = None
    jira_provider: str = "stub"
    jira_base_url: str | None = None
    jira_user_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    jira_default_issue_type: str = "Task"
    asr_provider: str = "openai"
    asr_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEETING_ASSISTANT_ASR_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
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
    batch_processing_mode: str = "sync"
    queue_provider: str = "memory"
    job_queue_provider: str = "inprocess"
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MEETING_ASSISTANT_",
    )
