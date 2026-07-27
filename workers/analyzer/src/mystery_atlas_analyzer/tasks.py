import os
from typing import Any

from celery import Celery

from .contracts import AnalysisProgress
from .pipeline import ANALYSIS_STAGES
from .runner import run_analysis_job


REDIS_URL = os.getenv("MYSTERY_ATLAS_REDIS_URL", "redis://localhost:6379/0")
app = Celery("mystery_atlas_analyzer", broker=REDIS_URL, backend=REDIS_URL)

READING_STAGES = ANALYSIS_STAGES
TRUTH_STAGES = ANALYSIS_STAGES


@app.task(bind=True, name="analyzer.analyze_edition")
def analyze_edition(
    task: Any,
    job_id: str,
) -> dict[str, Any]:
    """Run the complete versioned whole-book analysis for one persisted job."""

    def update_celery_state(progress: AnalysisProgress) -> None:
        task.update_state(
            state="PROGRESS",
            meta={
                "job_id": job_id,
                "stage": progress.stage,
                "progress": progress.progress,
                "detail": progress.detail,
            },
        )

    return run_analysis_job(job_id, on_progress=update_celery_state)
