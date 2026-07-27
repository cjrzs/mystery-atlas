from mystery_atlas_analyzer.settings import AnalyzerSettings


def test_analyzer_settings_load_project_dotenv(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MYSTERY_ATLAS_AI_BASE_URL", raising=False)
    monkeypatch.delenv("MYSTERY_ATLAS_AI_API_KEY", raising=False)
    monkeypatch.delenv("MYSTERY_ATLAS_AI_READING_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        """MYSTERY_ATLAS_AI_BASE_URL=https://api.example.test/v1
MYSTERY_ATLAS_AI_API_KEY=test-key
MYSTERY_ATLAS_AI_READING_MODEL=test-reading-model
MYSTERY_ATLAS_AI_MAX_CONCURRENCY=10
MYSTERY_ATLAS_AI_SYNTHESIS_BATCH_CHARS=30000
MYSTERY_ATLAS_AI_CONTENT_IDLE_TIMEOUT_SECONDS=180
""",
        encoding="utf-8",
    )

    settings = AnalyzerSettings.from_env()

    assert settings.is_model_configured
    assert settings.ai_base_url == "https://api.example.test/v1"
    assert settings.ai_api_key == "test-key"
    assert settings.reading_model == "test-reading-model"
    assert settings.max_concurrency == 10
    assert settings.synthesis_batch_chars == 30_000
    assert settings.content_idle_timeout_seconds == 180
