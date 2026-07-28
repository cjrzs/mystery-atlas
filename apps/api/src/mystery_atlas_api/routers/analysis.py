from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis_dispatch import schedule_analysis
from ..analysis_retry import (
    can_manage_analysis,
    can_restart_from_beginning,
    can_retry_from_checkpoint,
    should_reparse_source,
)
from ..book_structure import reparse_import_structure
from ..config import get_settings
from ..database import get_session
from ..models import AnalysisJob, BookImport, Edition, User, Work
from ..schemas import AnalysisJobDetailResponse
from ..security import get_current_user

router = APIRouter(prefix="/analysis-jobs", tags=["analysis jobs"])


@router.post(
    "/{job_id}/retry",
    response_model=AnalysisJobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_analysis(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    work = session.get(Work, job.work_id)
    edition = session.get(Edition, job.edition_id)
    if work is None or edition is None:
        raise HTTPException(status_code=404, detail="作品或版本不存在")
    if not can_manage_analysis(user, work, edition):
        raise HTTPException(
            status_code=403,
            detail="只有作品所有者、维护者或管理员可以重新分析",
        )
    if job.status not in {
        "failed",
        "waiting_configuration",
        "waiting_structure_review",
    }:
        raise HTTPException(status_code=409, detail="该分析任务当前不可重新分析")

    book_import = session.scalar(
        select(BookImport)
        .where(BookImport.edition_id == edition.id)
        .order_by(BookImport.created_at.desc())
    )
    reparse = should_reparse_source(job, book_import)
    structure_changed = False
    if reparse and book_import is not None:
        try:
            structure_changed = reparse_import_structure(
                session,
                book_import=book_import,
                edition=edition,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"无法重新提取原始文件：{exc}",
            ) from exc
        job.structure_version = book_import.structure_version
        book_import.stage = (
            "structure_review_required"
            if book_import.structure_requires_review
            else "ready_for_analysis"
        )
        if book_import.structure_requires_review:
            job.result_summary = {}
            job.status = "waiting_structure_review"
            job.stage = "structure_review"
            job.progress = 0
            job.error = None
            session.commit()
            session.refresh(job)
            return job

    resume = (
        not structure_changed
        and not reparse
        and can_retry_from_checkpoint(job)
    )
    if not resume:
        job.result_summary = {}
    schedule_analysis(
        job,
        background_tasks,
        get_settings(),
        resume=resume,
    )
    session.commit()
    session.refresh(job)
    return job


@router.post(
    "/{job_id}/retry-stage",
    response_model=AnalysisJobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_stage(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    work = session.get(Work, job.work_id)
    edition = session.get(Edition, job.edition_id)
    if work is None or edition is None:
        raise HTTPException(status_code=404, detail="作品或版本不存在")
    if not can_manage_analysis(user, work, edition):
        raise HTTPException(
            status_code=403,
            detail="只有作品所有者、维护者或管理员可以重试分析",
        )
    if job.status not in {"failed", "waiting_configuration"}:
        raise HTTPException(status_code=409, detail="该分析任务当前不可重试")
    if not can_retry_from_checkpoint(job):
        raise HTTPException(
            status_code=409,
            detail="该任务没有可用的阶段检查点，无法在不重跑前置阶段的情况下恢复",
        )

    schedule_analysis(
        job,
        background_tasks,
        get_settings(),
        resume=True,
    )
    session.commit()
    session.refresh(job)
    return job


@router.post(
    "/{job_id}/restart",
    response_model=AnalysisJobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def restart_failed_analysis(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AnalysisJob:
    job = session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    work = session.get(Work, job.work_id)
    edition = session.get(Edition, job.edition_id)
    if work is None or edition is None:
        raise HTTPException(status_code=404, detail="作品或版本不存在")
    if not can_manage_analysis(user, work, edition):
        raise HTTPException(
            status_code=403,
            detail="只有作品所有者、维护者或管理员可以重新分析",
        )
    if job.status not in {"failed", "waiting_configuration"}:
        raise HTTPException(status_code=409, detail="该分析任务当前不可重新分析")
    if not can_restart_from_beginning(job):
        raise HTTPException(
            status_code=409,
            detail="该任务存在可恢复的阶段检查点，请使用失败阶段重试",
        )

    job.result_summary = {}
    schedule_analysis(
        job,
        background_tasks,
        get_settings(),
        resume=False,
    )
    session.commit()
    session.refresh(job)
    return job
