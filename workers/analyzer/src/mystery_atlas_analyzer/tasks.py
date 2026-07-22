import os
from typing import Any

from celery import Celery


REDIS_URL = os.getenv("MYSTERY_ATLAS_REDIS_URL", "redis://localhost:6379/0")
app = Celery("mystery_atlas_analyzer", broker=REDIS_URL, backend=REDIS_URL)

READING_STAGES = [
    "chapter_segmentation",
    "character_extraction",
    "relationship_graph",
    "cases_and_clues",
    "dual_timeline",
    "chapter_snapshots",
]

TRUTH_STAGES = ["full_book_reconciliation", "foreshadowing_review", "final_claims"]


@app.task(bind=True, name="analyzer.analyze_edition")
def analyze_edition(
    task: Any,
    edition_id: str,
    track: str = "reading",
) -> dict[str, Any]:
    """Run the versioned pipeline; model calls will be added behind stage adapters."""
    stages = READING_STAGES if track == "reading" else TRUTH_STAGES
    for index, stage in enumerate(stages, start=1):
        task.update_state(
            state="PROGRESS",
            meta={
                "edition_id": edition_id,
                "track": track,
                "stage": stage,
                "progress": round(index / len(stages) * 100),
            },
        )
    return {
        "edition_id": edition_id,
        "track": track,
        "status": "draft_ready",
        "completed_stages": stages,
    }

