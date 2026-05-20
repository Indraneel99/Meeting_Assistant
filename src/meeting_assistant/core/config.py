from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./meeting_assistant.db"
    chunk_size_words: int = 120
    recent_summary_limit: int = 3
    semantic_context_limit: int = 5
    max_tool_calls_per_session: int = 10
    llm_provider: str = "openai"
    llm_fallback_provider: str = "heuristic"
    llm_openai_api_key: str | None = None
    llm_openai_base_url: str = "https://api.openai.com/v1"
    llm_openai_model: str = "gpt-5.4-mini"
    llm_openai_timeout_seconds: float = 90.0
    tool_execution_max_retries: int = 3
    tool_execution_backoff_seconds: float = 1.0
    asr_provider: str = "openai"
    asr_openai_api_key: str | None = None
    asr_openai_base_url: str = "https://api.openai.com/v1"
    asr_openai_model: str = "gpt-4o-transcribe-diarize"
    asr_openai_language: str | None = None
    asr_openai_timeout_seconds: float = 120.0
    asr_openai_chunking_strategy: str = "auto"

    model_config = SettingsConfigDict(env_prefix="MEETING_ASSISTANT_")
