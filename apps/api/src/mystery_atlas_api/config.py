from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "谜案经纬 API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://mystery_atlas:mystery_atlas@localhost:5432/mystery_atlas"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="MYSTERY_ATLAS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
