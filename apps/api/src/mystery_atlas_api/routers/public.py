from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..demo import EDGES, NODES, WORKS
from ..models import BookImport, CaseRecord, Edition, Evidence, Person, User, Work
from ..schemas import GraphSnapshot, ReaderResponse, WorkSummary

router = APIRouter(prefix="/works", tags=["public works"])


def work_summary(work: Work, session: Session) -> WorkSummary:
    maintainer = session.get(User, work.maintainer_id) if work.maintainer_id else None
    return WorkSummary(
        id=work.id,
        slug=work.slug,
        title=work.title,
        author=work.author,
        region=work.region or "",
        year=work.publication_year or 0,
        tags=[],
        cases=session.scalar(
            select(func.count()).select_from(CaseRecord).where(CaseRecord.work_id == work.id)
        ) or 0,
        people=session.scalar(
            select(func.count()).select_from(Person).where(Person.work_id == work.id)
        ) or 0,
        clues=session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.work_id == work.id)
        ) or 0,
        analysis_progress=work.analysis_progress,
        status=work.status,
        visibility=work.visibility,
        edition_count=session.scalar(
            select(func.count())
            .select_from(Edition)
            .where(Edition.work_id == work.id, Edition.visibility == "public")
        ) or 0,
        unresolved_feedback_count=work.unresolved_feedback_count,
        maintainer_name=maintainer.display_name if maintainer else "待接管",
        updated_at=work.updated_at,
    )


@router.get("", response_model=list[WorkSummary])
def list_works(session: Session = Depends(get_session)) -> list[WorkSummary]:
    database_works = list(
        session.scalars(
            select(Work)
            .where(Work.visibility == "public")
            .order_by(Work.updated_at.desc())
        )
    )
    summaries = [work_summary(work, session) for work in database_works]
    known_slugs = {item.slug for item in summaries}
    return summaries + [item for item in WORKS if item.slug not in known_slugs]


@router.get("/{slug}", response_model=WorkSummary)
def get_work(slug: str, session: Session = Depends(get_session)) -> WorkSummary:
    work = session.scalar(
        select(Work).where(Work.slug == slug, Work.visibility == "public")
    )
    if work is not None:
        return work_summary(work, session)
    demo = next((item for item in WORKS if item.slug == slug), None)
    if demo is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return demo


@router.get("/{slug}/reader", response_model=ReaderResponse)
def get_reader(
    slug: str,
    edition_id: str | None = None,
    session: Session = Depends(get_session),
) -> ReaderResponse:
    work = session.scalar(
        select(Work).where(Work.slug == slug, Work.visibility == "public")
    )
    if work is None:
        raise HTTPException(status_code=404, detail="该作品暂时没有真实阅读版本")

    query = select(Edition).where(
        Edition.work_id == work.id,
        Edition.visibility == "public",
        Edition.is_available.is_(True),
    )
    if edition_id:
        query = query.where(Edition.id == edition_id)
    edition = session.scalar(query.order_by(Edition.created_at.asc()))
    if edition is None:
        raise HTTPException(status_code=404, detail="暂无可读版本")
    book_import = session.scalar(
        select(BookImport)
        .where(BookImport.edition_id == edition.id)
        .where(BookImport.finalized_at.is_not(None))
    )
    if book_import is None:
        raise HTTPException(status_code=404, detail="版本正文不可用")
    return ReaderResponse(
        work_id=work.id,
        work_slug=work.slug,
        work_title=work.title,
        author=work.author,
        edition_id=edition.id,
        edition_title=edition.title,
        visibility=edition.visibility,
        chapters=book_import.chapters,
    )


@router.get("/{slug}/graph", response_model=GraphSnapshot)
def get_graph(
    slug: str,
    through_chapter: int = Query(default=1, ge=1, le=999),
    session: Session = Depends(get_session),
) -> GraphSnapshot:
    exists = session.scalar(
        select(Work.id).where(Work.slug == slug, Work.visibility == "public")
    )
    if exists is not None:
        return GraphSnapshot(
            work_slug=slug,
            through_chapter=through_chapter,
            nodes=[],
            edges=[],
        )
    if not any(item.slug == slug for item in WORKS):
        raise HTTPException(status_code=404, detail="作品不存在")

    visible_nodes = [item for item in NODES if item.first_chapter <= through_chapter]
    node_ids = {item.id for item in visible_nodes}
    visible_edges = [
        item
        for item in EDGES
        if item.first_chapter <= through_chapter
        and item.source in node_ids
        and item.target in node_ids
    ]
    return GraphSnapshot(
        work_slug=slug,
        through_chapter=through_chapter,
        nodes=visible_nodes,
        edges=visible_edges,
    )
