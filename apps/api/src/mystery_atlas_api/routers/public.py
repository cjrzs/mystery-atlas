from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analysis_views import workbench_analysis
from ..database import get_session
from ..demo import EDGES, NODES, WORKS
from ..models import (
    BookImport,
    CaseRecord,
    Edition,
    Evidence,
    Person,
    PersonRelation,
    User,
    Work,
)
from ..reader_views import reader_chapter, reader_response
from ..schemas import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    ReaderChapter,
    ReaderResponse,
    WorkbenchAnalysisResponse,
    WorkSummary,
)
from ..security import get_optional_user

router = APIRouter(prefix="/works", tags=["public works"])


def work_tags(work: Work) -> list[str]:
    if work.tags:
        return list(work.tags)
    demo = next((item for item in WORKS if item.slug == work.slug), None)
    return list(demo.tags) if demo else []


def work_summary(work: Work, session: Session) -> WorkSummary:
    maintainer = session.get(User, work.maintainer_id) if work.maintainer_id else None
    return WorkSummary(
        id=work.id,
        slug=work.slug,
        title=work.title,
        author=work.author,
        region=work.region or "",
        year=work.publication_year or 0,
        tags=work_tags(work),
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


@router.get(
    "/{slug}/reader",
    response_model=ReaderResponse,
    response_model_exclude_unset=True,
)
def get_reader(
    slug: str,
    edition_id: str | None = None,
    session: Session = Depends(get_session),
) -> ReaderResponse:
    work, edition, book_import = public_reader_source(slug, edition_id, session)
    return reader_response(work, edition, book_import)


def public_reader_source(
    slug: str,
    edition_id: str | None,
    session: Session,
) -> tuple[Work, Edition, BookImport]:
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
    return work, edition, book_import


@router.get(
    "/{slug}/reader/chapters/{chapter_number}",
    response_model=ReaderChapter,
    response_model_exclude_unset=True,
)
def get_reader_chapter(
    slug: str,
    chapter_number: int,
    edition_id: str | None = None,
    session: Session = Depends(get_session),
) -> ReaderChapter:
    _, _, book_import = public_reader_source(slug, edition_id, session)
    chapter = reader_chapter(book_import, chapter_number)
    if chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.get("/{slug}/analysis", response_model=WorkbenchAnalysisResponse)
def get_workbench_analysis(
    slug: str,
    through_chapter: int = Query(default=1, ge=1, le=999),
    user: User | None = Depends(get_optional_user),
    session: Session = Depends(get_session),
) -> WorkbenchAnalysisResponse:
    work = session.scalar(
        select(Work).where(Work.slug == slug, Work.visibility == "public")
    )
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return workbench_analysis(work, through_chapter, session, user=user)


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
        people = list(
            session.scalars(
                select(Person).where(
                    Person.work_id == exists,
                    Person.first_chapter <= through_chapter,
                )
            )
        )
        person_ids = {person.id for person in people}
        relations = list(
            session.scalars(
                select(PersonRelation).where(
                    PersonRelation.work_id == exists,
                    PersonRelation.first_chapter <= through_chapter,
                    PersonRelation.source_person_id.in_(person_ids),
                    PersonRelation.target_person_id.in_(person_ids),
                )
            )
        ) if person_ids else []
        evidence_ids = {
            relation.evidence_id for relation in relations if relation.evidence_id
        }
        evidence_by_id = {
            item.id: item
            for item in session.scalars(
                select(Evidence).where(Evidence.id.in_(evidence_ids))
            )
        } if evidence_ids else {}
        return GraphSnapshot(
            work_slug=slug,
            through_chapter=through_chapter,
            nodes=[
                GraphNode(
                    id=person.id,
                    name=person.canonical_name,
                    role=person.role,
                    group=person.identity_status,
                    first_chapter=person.first_chapter,
                    description=person.description,
                )
                for person in people
            ],
            edges=[
                GraphEdge(
                    id=relation.id,
                    source=relation.source_person_id,
                    target=relation.target_person_id,
                    label=relation.label,
                    kind=relation.kind,
                    status=relation.status
                    if relation.status in {"confirmed", "inferred", "disputed"}
                    else "inferred",
                    first_chapter=relation.first_chapter,
                    evidence=(
                        evidence_by_id[relation.evidence_id].citation.get("excerpt", "")
                        if relation.evidence_id in evidence_by_id
                        else ""
                    ),
                )
                for relation in relations
            ],
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
