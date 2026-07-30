from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

from fastapi import BackgroundTasks
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import AnalysisJob

logger = logging.getLogger(__name__)


def mark_stale_running_analyses(
    session: Session,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 300,
) -> int:
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(seconds=stale_after_seconds)
    jobs = list(
        session.scalars(
            select(AnalysisJob).where(
                AnalysisJob.status == "running",
                or_(
                    AnalysisJob.heartbeat_at < cutoff,
                    AnalysisJob.heartbeat_at.is_(None)
                    & (AnalysisJob.updated_at < cutoff),
                ),
            )
        )
    )
    for job in jobs:
        job.status = "failed"
        job.error = "analysis worker heartbeat expired; resume from checkpoint"
        job.stage_detail = "worker heartbeat expired"
        job.current_call_id = None
        job.content_idle_seconds = 0
    return len(jobs)


def recover_stale_running_analyses() -> int:
    from .database import SessionLocal

    with SessionLocal() as session:
        recovered = mark_stale_running_analyses(session)
        session.commit()
    if recovered:
        logger.warning(
            "Marked %d analysis job(s) failed after heartbeat expiry",
            recovered,
        )
    return recovered


def start_stale_analysis_watchdog(
    *,
    interval_seconds: float = 60,
) -> Callable[[], None]:
    stopped = Event()

    def run() -> None:
        while not stopped.is_set():
            try:
                recover_stale_running_analyses()
            except Exception:
                logger.exception("Analysis heartbeat watchdog failed")
            if stopped.wait(interval_seconds):
                break

    thread = Thread(
        target=run,
        name="analysis-heartbeat-watchdog",
        daemon=True,
    )
    thread.start()

    def stop() -> None:
        stopped.set()
        thread.join(timeout=1)

    return stop


def ai_analysis_configured(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    return (
        current.ai_provider == "openai-compatible"
        and bool(current.ai_base_url)
        and bool(current.ai_reading_model)
    )


def _run_inline(job_id: str) -> None:
    from mystery_atlas_analyzer.runner import run_analysis_job

    try:
        run_analysis_job(job_id)
    except Exception as exc:
        # The runner persists full diagnostics for backend troubleshooting.
        # Keep background failures out of the ASGI response and browser logs.
        logger.error(
            "Analysis job %s failed (%s)",
            job_id,
            type(exc).__name__,
        )


def _claim_inline_job(job_id: str) -> bool:
    from .database import SessionLocal

    with SessionLocal() as session:
        result = session.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.id == job_id,
                AnalysisJob.status == "queued",
            )
            .values(
                status="running",
                error=None,
            )
        )
        session.commit()
        return result.rowcount == 1


def _fail_inline_launch(job_id: str) -> None:
    from .database import SessionLocal

    with SessionLocal() as session:
        session.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job_id)
            .values(
                status="failed",
                stage="failed",
                progress=0,
                error="analysis worker process could not start",
            )
        )
        session.commit()


def _spawn_inline(job_id: str) -> None:
    if not _claim_inline_job(job_id):
        return

    project_root = Path(__file__).resolve().parents[4]
    api_source = project_root / "apps" / "api" / "src"
    analyzer_source = project_root / "workers" / "analyzer" / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(api_source),
            str(analyzer_source),
            env.get("PYTHONPATH", ""),
        ]
    ).rstrip(os.pathsep)
    command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "from mystery_atlas_api.analysis_dispatch import _run_inline; "
            "_run_inline(sys.argv[1])"
        ),
        job_id,
    ]
    process_options: dict[str, object] = {
        "cwd": project_root,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        process_options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        process_options["start_new_session"] = True
    try:
        subprocess.Popen(command, **process_options)
    except Exception:
        _fail_inline_launch(job_id)
        logger.error("Could not start analysis worker for job %s", job_id)


def _send_to_celery(job_id: str) -> None:
    from mystery_atlas_analyzer.tasks import app

    app.send_task("analyzer.analyze_edition", args=[job_id])


def _reset_runtime_telemetry(job: AnalysisJob) -> None:
    job.heartbeat_at = None
    job.current_call_id = None
    job.response_chars = 0
    job.content_idle_seconds = 0


def schedule_analysis(
    job: AnalysisJob,
    background_tasks: BackgroundTasks,
    settings: Settings | None = None,
    *,
    resume: bool = False,
) -> str:
    current = settings or get_settings()
    if not ai_analysis_configured(current):
        job.status = "waiting_configuration"
        if not resume:
            job.stage = "waiting_for_ai_configuration"
            job.progress = 0
        job.error = (
            "Configure MYSTERY_ATLAS_AI_BASE_URL and "
            "MYSTERY_ATLAS_AI_READING_MODEL"
        )
        return job.status

    _reset_runtime_telemetry(job)
    job.status = "queued"
    if not resume:
        job.stage = "source_validation"
        job.progress = 0
    job.error = None
    if current.analysis_execution == "celery":
        background_tasks.add_task(_send_to_celery, job.id)
    else:
        background_tasks.add_task(_spawn_inline, job.id)
    return job.status


def resume_waiting_analyses(settings: Settings | None = None) -> int:
    current = settings or get_settings()
    if not ai_analysis_configured(current):
        return 0

    from .database import SessionLocal

    resumable_statuses = ["waiting_configuration", "queued"]
    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(AnalysisJob).where(
                    AnalysisJob.status.in_(resumable_statuses)
                )
            )
        )
        job_ids = [job.id for job in jobs]
        for job in jobs:
            _reset_runtime_telemetry(job)
            job.status = "queued"
            job.error = None
        session.commit()

    target = _send_to_celery if current.analysis_execution == "celery" else _spawn_inline
    for job_id in job_ids:
        Thread(
            target=target,
            args=(job_id,),
            name=f"analysis-resume-{job_id[:8]}",
            daemon=True,
        ).start()
    return len(job_ids)
