from __future__ import annotations

from typing import Any

from .contracts import (
    AnalysisCheckpoint,
    AnalysisProgress,
    ModelAdapter,
    ProgressCallback,
)
from .model_adapters import (
    AIRequestProgress,
    ModelConfigurationError,
    OpenAICompatibleAdapter,
)
from .pipeline import PipelineConfig, analyze_book
from .repository import SQLAlchemyAnalysisRepository
from .settings import AnalyzerSettings


def _resume_stage(
    checkpoint: AnalysisCheckpoint,
    *,
    total_chapters: int,
) -> tuple[str, int]:
    if checkpoint.reconciliation is not None:
        return "persistence", 96
    if checkpoint.synthesis is not None:
        return "evidence_verification", 78
    if checkpoint.parts or len(checkpoint.chapters) >= total_chapters:
        return "book_synthesis", 65
    if checkpoint.chapters or checkpoint.chapter_work:
        progress = 5 + round(len(checkpoint.chapters) / total_chapters * 45)
        return "segment_analysis", progress
    return "source_validation", 1


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

    def stream_progress(update: AIRequestProgress) -> None:
        repo.heartbeat_job(
            job_id,
            call_id=update.call_id,
            task=update.task,
            response_chars=update.response_chars,
            content_idle_seconds=update.content_idle_seconds,
        )

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
            job_id=job_id,
            work_id=loaded.work_id,
            edition_id=loaded.edition_id,
            timeout_seconds=current_settings.timeout_seconds,
            content_idle_timeout_seconds=(
                current_settings.content_idle_timeout_seconds
            ),
            progress_callback=stream_progress,
        )

    resume_stage, resume_progress = _resume_stage(
        loaded.checkpoint,
        total_chapters=len(loaded.book.chapters),
    )
    current_stage = resume_stage
    current_progress = max(resume_progress, loaded.progress if loaded.status == "failed" else 0)
    current_detail = "resuming from the latest safe checkpoint"
    active_checkpoint = loaded.checkpoint

    def progress(update: AnalysisProgress) -> None:
        nonlocal current_stage, current_progress, current_detail
        current_stage = update.stage
        current_progress = update.progress
        current_detail = update.detail
        repo.update_job(
            job_id,
            status="running",
            stage=update.stage,
            progress=update.progress,
            error=None,
            stage_detail=update.detail,
        )
        if on_progress:
            on_progress(update)

    def checkpoint(update: AnalysisCheckpoint) -> None:
        nonlocal active_checkpoint
        active_checkpoint = update
        repo.save_checkpoint(job_id, update)

    repo.update_job(
        job_id,
        status="running",
        stage=current_stage,
        progress=current_progress,
        error=None,
        stage_detail=current_detail,
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
                synthesis_batch_chars=current_settings.synthesis_batch_chars,
            ),
            on_progress=progress,
            checkpoint=active_checkpoint,
            on_checkpoint=checkpoint,
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
            stage=current_stage,
            progress=current_progress,
            error=str(exc)[:4000],
            stage_detail=current_detail,
        )
        raise
