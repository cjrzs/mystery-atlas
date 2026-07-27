from __future__ import annotations

from typing import Any

from .contracts import AnalysisProgress, ModelAdapter, ProgressCallback
from .model_adapters import ModelConfigurationError, OpenAICompatibleAdapter
from .pipeline import PipelineConfig, analyze_book
from .repository import SQLAlchemyAnalysisRepository
from .settings import AnalyzerSettings


def run_analysis_job(
    job_id: str,
    *,
    settings: AnalyzerSettings | None = None,
    adapter: ModelAdapter | None = None,
    repository: SQLAlchemyAnalysisRepository | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    current_settings = settings or AnalyzerSettings.from_env()
    repo = repository or SQLAlchemyAnalysisRepository(current_settings.database_url)
    loaded = repo.load_job(job_id)

    if adapter is None:
        if not current_settings.is_model_configured:
            repo.update_job(
                job_id,
                status="waiting_configuration",
                stage="waiting_for_ai_configuration",
                progress=0,
                error=(
                    "Configure MYSTERY_ATLAS_AI_BASE_URL and "
                    "MYSTERY_ATLAS_AI_READING_MODEL"
                ),
            )
            raise ModelConfigurationError("AI analysis provider is not configured")
        adapter = OpenAICompatibleAdapter(
            base_url=current_settings.ai_base_url,
            api_key=current_settings.ai_api_key,
            timeout_seconds=current_settings.timeout_seconds,
            max_output_tokens=current_settings.max_output_tokens,
        )

    def progress(update: AnalysisProgress) -> None:
        repo.update_job(
            job_id,
            status="running",
            stage=update.stage,
            progress=update.progress,
            error=None,
        )
        if on_progress:
            on_progress(update)

    repo.update_job(
        job_id,
        status="running",
        stage="source_validation",
        progress=1,
        error=None,
    )
    try:
        report = analyze_book(
            loaded.book,
            adapter,
            PipelineConfig(
                reading_model=current_settings.reading_model or "test-model",
                truth_model=current_settings.truth_model,
                max_chunk_chars=current_settings.max_chunk_chars,
                chunk_overlap_chars=current_settings.chunk_overlap_chars,
                chapters_per_batch=current_settings.chapters_per_batch,
                max_concurrency=current_settings.max_concurrency,
            ),
            on_progress=progress,
        )
        progress(AnalysisProgress(stage="persistence", progress=96, detail="saving report"))
        counts = repo.persist_report(job_id, report)
        return {
            "job_id": job_id,
            "work_id": loaded.work_id,
            "edition_id": loaded.edition_id,
            "status": "completed",
            "audit": report.audit.model_dump(mode="json"),
            "persistence": counts,
        }
    except Exception as exc:
        repo.update_job(
            job_id,
            status="failed",
            stage="failed",
            progress=0,
            error=str(exc)[:4000],
        )
        raise
