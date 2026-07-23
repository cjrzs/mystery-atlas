from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import AnalysisJob, Edition, Feedback, User, Work
from ..schemas import AnalysisJobRequest, AnalysisJobResponse
from ..security import require_admin

router = APIRouter(
    prefix="/admin",
    tags=["super administration"],
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


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session)) -> dict:
    return {
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "public_works": session.scalar(
            select(func.count()).select_from(Work).where(Work.visibility == "public")
        ) or 0,
        "open_feedback": session.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.status == "open")
        ) or 0,
        "failed_jobs": session.scalar(
            select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "failed")
        ) or 0,
        "orphaned_works": session.scalar(
            select(func.count()).select_from(Work).where(Work.maintainer_id.is_(None))
        ) or 0,
    }


@router.post("/works/{work_id}/takeover")
def take_over_work(
    work_id: str,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    work = session.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    work.maintainer_id = admin.id
    session.commit()
    return {"work_id": work.id, "maintainer_id": admin.id}


@router.post("/editions/{edition_id}/availability")
def set_edition_availability(
    edition_id: str,
    available: bool,
    session: Session = Depends(get_session),
) -> dict:
    edition = session.get(Edition, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    edition.is_available = available
    session.commit()
    return {"edition_id": edition.id, "is_available": edition.is_available}


@router.post(
    "/works/{work_id}/analysis-jobs",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_job(
    work_id: str,
    request: AnalysisJobRequest,
    session: Session = Depends(get_session),
) -> AnalysisJobResponse:
    work = session.get(Work, work_id)
    edition = session.get(Edition, request.edition_id)
    if work is None or edition is None or edition.work_id != work.id:
        raise HTTPException(status_code=404, detail="作品或版本不存在")
    for track in request.tracks:
        session.add(
            AnalysisJob(
                id=str(uuid4()),
                work_id=work.id,
                edition_id=edition.id,
                track=track,
                stage=ANALYSIS_STAGES[0],
                status="queued",
                progress=0,
            )
        )
    session.commit()
    return AnalysisJobResponse(
        job_id=str(uuid4()),
        status="queued",
        stages=ANALYSIS_STAGES,
    )
