from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnalysisJob,
    ChapterSnapshot,
    Evidence,
    Person,
    PersonRelation,
    Work,
)
from .schemas import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    WorkbenchAnalysisResponse,
    WorkbenchChapterSnapshot,
    WorkbenchEvidence,
    WorkbenchTimelineEvent,
)


def graph_for_work(
    work: Work,
    through_chapter: int,
    session: Session,
) -> GraphSnapshot:
    people = list(
        session.scalars(
            select(Person)
            .where(
                Person.work_id == work.id,
                Person.first_chapter <= through_chapter,
            )
            .order_by(Person.first_chapter, Person.canonical_name)
        )
    )
    person_ids = {person.id for person in people}
    relations = (
        list(
            session.scalars(
                select(PersonRelation)
                .where(
                    PersonRelation.work_id == work.id,
                    PersonRelation.first_chapter <= through_chapter,
                    PersonRelation.source_person_id.in_(person_ids),
                    PersonRelation.target_person_id.in_(person_ids),
                )
                .order_by(PersonRelation.first_chapter, PersonRelation.label)
            )
        )
        if person_ids
        else []
    )
    evidence_ids = {
        relation.evidence_id for relation in relations if relation.evidence_id
    }
    evidence_by_id = (
        {
            item.id: item
            for item in session.scalars(
                select(Evidence).where(Evidence.id.in_(evidence_ids))
            )
        }
        if evidence_ids
        else {}
    )
    return GraphSnapshot(
        work_slug=work.slug,
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
                status=(
                    relation.status
                    if relation.status in {"confirmed", "inferred", "disputed"}
                    else "inferred"
                ),
                first_chapter=relation.first_chapter,
                evidence=(
                    str(
                        evidence_by_id[relation.evidence_id].citation.get(
                            "excerpt", ""
                        )
                    )
                    if relation.evidence_id in evidence_by_id
                    else ""
                ),
            )
            for relation in relations
        ],
    )


def workbench_analysis(
    work: Work,
    through_chapter: int,
    session: Session,
) -> WorkbenchAnalysisResponse:
    job = session.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.work_id == work.id)
        .order_by(AnalysisJob.created_at.desc())
    )
    snapshots = list(
        session.scalars(
            select(ChapterSnapshot)
            .where(
                ChapterSnapshot.work_id == work.id,
                ChapterSnapshot.chapter <= through_chapter,
            )
            .order_by(ChapterSnapshot.chapter)
        )
    )
    latest_snapshot = snapshots[-1] if snapshots else None
    timeline_payload = latest_snapshot.timeline_payload if latest_snapshot else []
    timeline = [
        WorkbenchTimelineEvent.model_validate(item)
        for item in timeline_payload
        if isinstance(item, dict)
        and isinstance(item.get("chapter"), int)
        and item["chapter"] <= through_chapter
    ]
    evidence = list(
        session.scalars(
            select(Evidence)
            .where(
                Evidence.work_id == work.id,
                Evidence.first_chapter <= through_chapter,
            )
            .order_by(Evidence.first_chapter, Evidence.created_at)
        )
    )
    return WorkbenchAnalysisResponse(
        work_id=work.id,
        work_slug=work.slug,
        through_chapter=through_chapter,
        status=job.status if job else work.status,
        stage=job.stage if job else ("completed" if work.analysis_progress == 100 else "not_started"),
        progress=job.progress if job else work.analysis_progress,
        error=job.error if job else None,
        graph=graph_for_work(work, through_chapter, session),
        timeline=timeline,
        chapters=[
            WorkbenchChapterSnapshot(chapter=item.chapter, summary=item.summary)
            for item in snapshots
        ],
        evidence=[
            WorkbenchEvidence(
                id=item.id,
                title=item.title,
                summary=item.summary,
                source_type=item.source_type,
                status=item.status,
                first_chapter=item.first_chapter,
                excerpt=str(item.citation.get("excerpt", "")),
            )
            for item in evidence
        ],
    )
