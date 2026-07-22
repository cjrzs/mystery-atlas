from uuid import uuid4

from fastapi import APIRouter, Depends, status

from ..demo import REVIEW_ITEMS
from ..schemas import AnalysisJobRequest, AnalysisJobResponse, ReviewItem
from ..security import require_admin

router = APIRouter(
    prefix="/admin",
    tags=["administration"],
    dependencies=[Depends(require_admin)],
)

ANALYSIS_STAGES = [
    "chapter_segmentation",
    "character_extraction",
    "relationship_graph",
    "cases_and_clues",
    "dual_timeline",
    "chapter_snapshots",
    "truth_review",
]


@router.get("/review-queue", response_model=list[ReviewItem])
def get_review_queue() -> list[ReviewItem]:
    return REVIEW_ITEMS


@router.post(
    "/works/{work_id}/analysis-jobs",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_job(work_id: str, request: AnalysisJobRequest) -> AnalysisJobResponse:
    del work_id, request
    return AnalysisJobResponse(
        job_id=str(uuid4()),
        status="queued",
        stages=ANALYSIS_STAGES,
    )
