from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import (
    ContentRevision,
    Edition,
    Feedback,
    Notification,
    User,
    Work,
)
from ..schemas import FeedbackCreate, FeedbackResolve, FeedbackResponse, NotificationResponse
from ..security import get_current_user

router = APIRouter(prefix="/feedback", tags=["feedback"])
maintenance_router = APIRouter(prefix="/maintenance", tags=["archive maintenance"])


def feedback_response(item: Feedback, session: Session) -> FeedbackResponse:
    reporter = session.get(User, item.reporter_id)
    assignee = session.get(User, item.assignee_id) if item.assignee_id else None
    return FeedbackResponse(
        id=item.id,
        work_id=item.work_id,
        edition_id=item.edition_id,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        category=item.category,
        chapter=item.chapter,
        content=item.content,
        status=item.status,
        resolution=item.resolution,
        same_issue_count=item.same_issue_count,
        reporter_name=reporter.display_name if reporter else "已注销用户",
        assignee_name=assignee.display_name if assignee else "待接管",
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def resolve_assignee(request: FeedbackCreate, session: Session) -> str | None:
    if request.edition_id:
        edition = session.get(Edition, request.edition_id)
        if edition is not None:
            return edition.maintainer_id
    if request.work_id:
        work = session.get(Work, request.work_id)
        if work is not None:
            return work.maintainer_id
    return session.scalar(select(User.id).where(User.role == "admin").order_by(User.created_at.asc()))


@router.get("", response_model=list[FeedbackResponse])
def list_public_feedback(
    work_id: str | None = None,
    through_chapter: int | None = None,
    session: Session = Depends(get_session),
) -> list[FeedbackResponse]:
    query = (
        select(Feedback)
        .outerjoin(Work, Feedback.work_id == Work.id)
        .outerjoin(Edition, Feedback.edition_id == Edition.id)
        .where(Feedback.is_hidden.is_(False))
        .where(
            or_(
                and_(Feedback.work_id.is_(None), Feedback.edition_id.is_(None)),
                and_(
                    Work.visibility == "public",
                    or_(Feedback.edition_id.is_(None), Edition.visibility == "public"),
                ),
            )
        )
    )
    if work_id:
        query = query.where(Feedback.work_id == work_id)
    if through_chapter is not None:
        query = query.where(
            (Feedback.chapter.is_(None)) | (Feedback.chapter <= through_chapter)
        )
    items = list(session.scalars(query.order_by(Feedback.created_at.desc())))
    return [feedback_response(item, session) for item in items]


@router.post("", response_model=FeedbackResponse, status_code=201)
def create_feedback(
    request: FeedbackCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FeedbackResponse:
    work = session.get(Work, request.work_id) if request.work_id else None
    edition = session.get(Edition, request.edition_id) if request.edition_id else None
    if request.work_id and work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    if request.edition_id and edition is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    if edition is not None:
        if work is not None and edition.work_id != work.id:
            raise HTTPException(status_code=422, detail="版本不属于指定作品")
        if work is None:
            work = session.get(Work, edition.work_id)
    if work is not None and work.visibility != "public" and work.owner_id != user.id:
        raise HTTPException(status_code=404, detail="作品不存在")

    effective_work_id = work.id if work else None
    assignee_id = resolve_assignee(request, session)
    item = Feedback(
        reporter_id=user.id,
        assignee_id=assignee_id,
        work_id=effective_work_id,
        edition_id=request.edition_id,
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        category=request.category,
        chapter=request.chapter,
        content=request.content.strip(),
    )
    session.add(item)
    if work is not None:
        work.unresolved_feedback_count += 1
    if assignee_id and assignee_id != user.id:
        session.add(
            Notification(
                user_id=assignee_id,
                kind="feedback_created",
                title="收到新的档案反馈",
                body=request.content.strip()[:240],
                link="/maintenance",
            )
        )
    session.commit()
    session.refresh(item)
    return feedback_response(item, session)


@router.post("/{feedback_id}/same", response_model=FeedbackResponse)
def mark_same_issue(
    feedback_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FeedbackResponse:
    del user
    item = session.get(Feedback, feedback_id)
    if item is None or item.is_hidden:
        raise HTTPException(status_code=404, detail="反馈不存在")
    item.same_issue_count += 1
    session.commit()
    session.refresh(item)
    return feedback_response(item, session)


@maintenance_router.get("/overview")
def maintenance_overview(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    work_query = select(Work).where(Work.maintainer_id == user.id)
    edition_query = select(Edition).where(Edition.maintainer_id == user.id)
    feedback_query = select(func.count()).select_from(Feedback).where(
        Feedback.assignee_id == user.id,
        Feedback.status == "open",
    )
    if user.role == "admin":
        feedback_query = select(func.count()).select_from(Feedback).where(Feedback.status == "open")
    return {
        "works": [
            {"id": item.id, "slug": item.slug, "title": item.title, "progress": item.analysis_progress}
            for item in session.scalars(work_query.order_by(Work.updated_at.desc()))
        ],
        "editions": [
            {"id": item.id, "work_id": item.work_id, "title": item.title, "visibility": item.visibility}
            for item in session.scalars(edition_query.order_by(Edition.updated_at.desc()))
        ],
        "open_feedback": session.scalar(feedback_query) or 0,
        "is_super_admin": user.role == "admin",
    }


@maintenance_router.get("/feedback", response_model=list[FeedbackResponse])
def list_assigned_feedback(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[FeedbackResponse]:
    query = select(Feedback)
    if user.role != "admin":
        query = query.where(Feedback.assignee_id == user.id)
    items = list(session.scalars(query.order_by(Feedback.created_at.desc())))
    return [feedback_response(item, session) for item in items]


@maintenance_router.patch("/feedback/{feedback_id}", response_model=FeedbackResponse)
def resolve_feedback(
    feedback_id: str,
    request: FeedbackResolve,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FeedbackResponse:
    item = session.get(Feedback, feedback_id)
    if item is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if user.role != "admin" and item.assignee_id != user.id:
        raise HTTPException(status_code=403, detail="你不能处理这条反馈")

    was_open = item.status == "open"
    item.status = request.status
    item.resolution = request.resolution.strip()
    if item.work_id and request.change_summary.strip():
        version = session.scalar(
            select(func.coalesce(func.max(ContentRevision.version), 0)).where(
                ContentRevision.work_id == item.work_id
            )
        ) or 0
        revision = ContentRevision(
            work_id=item.work_id,
            edition_id=item.edition_id,
            created_by=user.id,
            source_feedback_id=item.id,
            version=version + 1,
            summary=request.change_summary.strip(),
            snapshot={"feedback_status": request.status, "resolution": item.resolution},
        )
        session.add(revision)
        session.flush()
        item.resolved_revision_id = revision.id
    if was_open and request.status != "open" and item.work_id:
        work = session.get(Work, item.work_id)
        if work is not None:
            work.unresolved_feedback_count = max(0, work.unresolved_feedback_count - 1)
    session.add(
        Notification(
            user_id=item.reporter_id,
            kind="feedback_updated",
            title="你的反馈已有处理结果",
            body=item.resolution[:240],
            link="/maintenance",
        )
    )
    session.commit()
    session.refresh(item)
    return feedback_response(item, session)


@maintenance_router.get("/notifications", response_model=list[NotificationResponse])
def list_notifications(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[Notification]:
    return list(
        session.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
        )
    )
