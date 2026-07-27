from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "谜案经纬 API"
    environment: str = "development"
    database_url: str = "sqlite:///./.data/mystery-atlas.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]
    session_secret: str = "development-only-change-me-please-2026"
    session_ttl_hours: int = 168
    session_cookie_secure: bool | None = None
    first_user_admin: bool = False
    upload_dir: str = ".data/uploads"
    max_upload_mb: int = 50
    ai_provider: str = "openai-compatible"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_reading_model: str = ""
    ai_truth_model: str = ""
    ai_timeout_seconds: int = 20
    ai_max_output_tokens: int = 8000
    ai_max_chunk_chars: int = 12000
    ai_chunk_overlap_chars: int = 500
    ai_chapters_per_batch: int = 6
    ai_max_concurrency: int = 10
    analysis_execution: Literal["inline", "celery"] = "inline"

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="MYSTERY_ATLAS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
