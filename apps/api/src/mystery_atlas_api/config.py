from functools import lru_cache

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
    upload_dir: str = ".data/uploads"
    max_upload_mb: int = 50

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="MYSTERY_ATLAS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
