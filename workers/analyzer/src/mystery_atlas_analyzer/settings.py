from __future__ import annotations

from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


class _DotenvSettings(BaseSettings):
    database_url: str = "sqlite:///./.data/mystery-atlas.db"
    ai_provider: str = "openai-compatible"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_reading_model: str = ""
    ai_truth_model: str = ""
    ai_timeout_seconds: int = 90
    ai_max_output_tokens: int = 8000
    ai_max_chunk_chars: int = 12_000
    ai_chunk_overlap_chars: int = 500
    ai_chapters_per_batch: int = 6
    ai_max_concurrency: int = 10

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="MYSTERY_ATLAS_",
        extra="ignore",
    )


@dataclass(frozen=True)
class AnalyzerSettings:
    database_url: str
    ai_provider: str
    ai_base_url: str
    ai_api_key: str
    reading_model: str
    truth_model: str
    timeout_seconds: int
    max_output_tokens: int
    max_chunk_chars: int
    chunk_overlap_chars: int
    chapters_per_batch: int
    max_concurrency: int = 10

    @classmethod
    def from_env(cls) -> AnalyzerSettings:
        dotenv = _DotenvSettings()
        return cls(
            database_url=dotenv.database_url,
            ai_provider=dotenv.ai_provider,
            ai_base_url=dotenv.ai_base_url,
            ai_api_key=dotenv.ai_api_key,
            reading_model=dotenv.ai_reading_model,
            truth_model=dotenv.ai_truth_model,
            timeout_seconds=dotenv.ai_timeout_seconds,
            max_output_tokens=dotenv.ai_max_output_tokens,
            max_chunk_chars=dotenv.ai_max_chunk_chars,
            chunk_overlap_chars=dotenv.ai_chunk_overlap_chars,
            chapters_per_batch=dotenv.ai_chapters_per_batch,
            max_concurrency=dotenv.ai_max_concurrency,
        )

    @property
    def is_model_configured(self) -> bool:
        return (
            self.ai_provider == "openai-compatible"
            and bool(self.ai_base_url)
            and bool(self.reading_model)
        )
