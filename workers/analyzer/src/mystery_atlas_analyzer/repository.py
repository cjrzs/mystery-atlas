from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import MetaData, Table, create_engine, delete, insert, or_, select, update
from sqlalchemy.engine import Engine

from .contracts import (
    AnalysisCheckpoint,
    BookAnalysis,
    BookInput,
    ClaimFinding,
    PersonFinding,
    RelationFinding,
    SourceChapter,
)


@dataclass(frozen=True)
class LoadedJob:
    job_id: str
    track: str
    work_id: str
    edition_id: str
    status: str
    stage: str
    progress: int
    book: BookInput
    checkpoint: AnalysisCheckpoint


def _stable_id(kind: str, *parts: object) -> str:
    value = ":".join(str(part).strip().casefold() for part in parts)
    return str(uuid5(NAMESPACE_URL, f"mystery-atlas:{kind}:{value}"))


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


class SQLAlchemyAnalysisRepository:
    """Persistence adapter for the analyzer's database seam."""

    REQUIRED_TABLES = {
        "analysis_jobs",
        "book_imports",
        "cases",
        "chapter_snapshots",
        "chapters",
        "claim_evidence",
        "claims",
        "editions",
        "evidence",
        "people",
        "person_aliases",
        "person_relations",
        "works",
    }

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_engine(str(database_url), pool_pre_ping=True)
        self.metadata = MetaData()
        self.metadata.reflect(bind=self.engine)
        missing = self.REQUIRED_TABLES.difference(self.metadata.tables)
        if missing:
            raise RuntimeError(f"analysis database is missing tables: {sorted(missing)}")

    def table(self, name: str) -> Table:
        return self.metadata.tables[name]

    def load_job(self, job_id: str) -> LoadedJob:
        jobs = self.table("analysis_jobs")
        editions = self.table("editions")
        works = self.table("works")
        imports = self.table("book_imports")
        with self.engine.connect() as connection:
            job = connection.execute(
                select(jobs).where(jobs.c.id == job_id)
            ).mappings().one_or_none()
            if job is None:
                raise LookupError(f"analysis job {job_id} does not exist")
            edition = connection.execute(
                select(editions).where(editions.c.id == job["edition_id"])
            ).mappings().one_or_none()
            work = connection.execute(
                select(works).where(works.c.id == job["work_id"])
            ).mappings().one_or_none()
            book_import = connection.execute(
                select(imports)
                .where(imports.c.edition_id == job["edition_id"])
                .order_by(imports.c.created_at.desc())
            ).mappings().first()

        if edition is None or work is None:
            raise LookupError(f"analysis job {job_id} has no work or edition")
        if book_import is None:
            raise LookupError(f"edition {job['edition_id']} has no imported source")

        chapter_values = _json_value(book_import["chapters"])
        if not isinstance(chapter_values, list) or not chapter_values:
            raise ValueError("imported book has no parsed chapters")
        job_structure_version = str(job.get("structure_version") or "")
        import_structure_version = str(book_import.get("structure_version") or "")
        if (
            job_structure_version
            and import_structure_version
            and job_structure_version != import_structure_version
        ):
            raise ValueError(
                "analysis job is bound to an outdated chapter structure"
            )
        chapters = [
            SourceChapter(
                number=int(item.get("number", index + 1)),
                title=str(item.get("title") or ""),
                text=str(item.get("text") or ""),
                source_locator=dict(item.get("source_locator") or {}),
                structural_path=list(item.get("structural_path") or []),
                content_type=str(item.get("content_type") or "chapter"),
                structure_version=str(item.get("structure_version") or ""),
            )
            for index, item in enumerate(chapter_values)
            if isinstance(item, dict)
        ]
        book = BookInput(
            work_id=str(work["id"]),
            edition_id=str(edition["id"]),
            title=str(work["title"]),
            author=str(work["author"]),
            language=str(edition["language"] or "zh-CN"),
            structure_version=import_structure_version,
            chapters=chapters,
        )
        result_summary = _json_value(job["result_summary"])
        checkpoint_payload = (
            result_summary.get("checkpoint")
            if isinstance(result_summary, dict)
            else None
        )
        checkpoint = (
            AnalysisCheckpoint.model_validate(checkpoint_payload)
            if isinstance(checkpoint_payload, dict)
            else AnalysisCheckpoint()
        )
        return LoadedJob(
            job_id=job_id,
            track=str(job["track"]),
            work_id=str(work["id"]),
            edition_id=str(edition["id"]),
            status=str(job["status"]),
            stage=str(job["stage"]),
            progress=int(job["progress"]),
            book=book,
            checkpoint=checkpoint,
        )

    def save_checkpoint(
        self,
        job_id: str,
        checkpoint: AnalysisCheckpoint,
    ) -> None:
        jobs = self.table("analysis_jobs")
        with self.engine.begin() as connection:
            current = connection.execute(
                select(jobs.c.result_summary).where(jobs.c.id == job_id)
            ).scalar_one_or_none()
            if current is None:
                raise LookupError(f"analysis job {job_id} does not exist")
            decoded = _json_value(current)
            result_summary = dict(decoded) if isinstance(decoded, dict) else {}
            result_summary["checkpoint"] = checkpoint.model_dump(mode="json")
            connection.execute(
                update(jobs)
                .where(jobs.c.id == job_id)
                .values(result_summary=result_summary)
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        progress: int,
        error: str | None = None,
        stage_detail: str | None = None,
    ) -> None:
        jobs = self.table("analysis_jobs")
        works = self.table("works")
        with self.engine.begin() as connection:
            job = connection.execute(
                select(jobs.c.work_id).where(jobs.c.id == job_id)
            ).mappings().one_or_none()
            if job is None:
                raise LookupError(f"analysis job {job_id} does not exist")
            values: dict[str, Any] = {
                "status": status,
                "stage": stage,
                "progress": progress,
                "error": error,
            }
            if stage_detail is not None and "stage_detail" in jobs.c:
                values["stage_detail"] = stage_detail[:300]
            connection.execute(
                update(jobs)
                .where(jobs.c.id == job_id)
                .values(**values)
            )
            connection.execute(
                update(works)
                .where(works.c.id == job["work_id"])
                .values(
                    analysis_progress=progress,
                    status="analyzing" if status == "running" else status,
                )
            )

    def heartbeat_job(
        self,
        job_id: str,
        *,
        call_id: str,
        task: str,
        response_chars: int,
        content_idle_seconds: int,
    ) -> None:
        jobs = self.table("analysis_jobs")
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "heartbeat_at": now,
            "current_call_id": call_id,
            "stage_detail": task[:300],
            "response_chars": response_chars,
            "content_idle_seconds": content_idle_seconds,
        }
        if "updated_at" in jobs.c:
            values["updated_at"] = now
        values = {name: value for name, value in values.items() if name in jobs.c}
        with self.engine.begin() as connection:
            if values:
                result = connection.execute(
                    update(jobs)
                    .where(jobs.c.id == job_id)
                    .values(**values)
                )
                exists = result.rowcount == 1
            else:
                exists = (
                    connection.execute(
                        select(jobs.c.id).where(jobs.c.id == job_id)
                    ).scalar_one_or_none()
                    is not None
                )
            if not exists:
                raise LookupError(f"analysis job {job_id} does not exist")

    def _row_exists(self, connection: Any, table: Table, row_id: str) -> bool:
        return (
            connection.execute(
                select(table.c.id).where(table.c.id == row_id)
            ).scalar_one_or_none()
            is not None
        )

    def _insert_once(
        self,
        connection: Any,
        table: Table,
        values: dict[str, Any],
    ) -> bool:
        insert_values = dict(values)
        now = datetime.now(UTC)
        if "created_at" in table.c and "created_at" not in insert_values:
            insert_values["created_at"] = now
        if "updated_at" in table.c and "updated_at" not in insert_values:
            insert_values["updated_at"] = now
        row_id = str(insert_values["id"])
        if self._row_exists(connection, table, row_id):
            return False
        connection.execute(insert(table).values(**insert_values))
        return True

    def _clear_existing_analysis(
        self,
        connection: Any,
        *,
        work_id: str,
    ) -> int:
        snapshots = self.table("chapter_snapshots")
        cases = self.table("cases")
        people = self.table("people")
        aliases = self.table("person_aliases")
        relations = self.table("person_relations")
        evidence = self.table("evidence")
        claims = self.table("claims")
        claim_evidence = self.table("claim_evidence")

        person_ids = select(people.c.id).where(people.c.work_id == work_id)
        evidence_ids = select(evidence.c.id).where(evidence.c.work_id == work_id)
        claim_ids = select(claims.c.id).where(claims.c.work_id == work_id)
        removed = 0
        statements = [
            delete(claim_evidence).where(
                or_(
                    claim_evidence.c.claim_id.in_(claim_ids),
                    claim_evidence.c.evidence_id.in_(evidence_ids),
                )
            ),
            delete(relations).where(relations.c.work_id == work_id),
            delete(aliases).where(aliases.c.person_id.in_(person_ids)),
            delete(claims).where(claims.c.work_id == work_id),
            delete(evidence).where(evidence.c.work_id == work_id),
            delete(snapshots).where(snapshots.c.work_id == work_id),
            delete(cases).where(cases.c.work_id == work_id),
            delete(people).where(people.c.work_id == work_id),
        ]
        for statement in statements:
            result = connection.execute(statement)
            removed += max(result.rowcount or 0, 0)
        return removed

    @staticmethod
    def _aggregate_people(report: BookAnalysis) -> dict[str, PersonFinding]:
        result: dict[str, PersonFinding] = {}
        for chapter in report.chapters:
            for person in chapter.people:
                key = person.name.strip().casefold()
                current = result.get(key)
                if current is None or person.first_chapter < current.first_chapter:
                    result[key] = person
        return result

    @staticmethod
    def _aggregate_relations(report: BookAnalysis) -> dict[str, RelationFinding]:
        result: dict[str, RelationFinding] = {}
        for chapter in report.chapters:
            for relation in chapter.relations:
                key = "|".join(
                    [
                        relation.source.strip().casefold(),
                        relation.target.strip().casefold(),
                        relation.kind.strip().casefold(),
                        relation.label.strip().casefold(),
                    ]
                )
                current = result.get(key)
                if current is None or relation.first_chapter < current.first_chapter:
                    result[key] = relation
        return result

    @staticmethod
    def _aggregate_claims(report: BookAnalysis) -> dict[str, ClaimFinding]:
        claims: list[ClaimFinding] = []
        for chapter in report.chapters:
            claims.extend(chapter.claims)
        claims.extend(
            report.reconciliation.final_claims
            or report.synthesis.claims
        )
        result: dict[str, ClaimFinding] = {}
        for claim in claims:
            key = claim.statement.strip().casefold()
            current = result.get(key)
            if current is None or claim.confidence > current.confidence:
                result[key] = claim
        return result

    def persist_report(self, job_id: str, report: BookAnalysis) -> dict[str, int]:
        jobs = self.table("analysis_jobs")
        works = self.table("works")
        chapters_table = self.table("chapters")
        snapshots = self.table("chapter_snapshots")
        cases = self.table("cases")
        people = self.table("people")
        aliases = self.table("person_aliases")
        relations = self.table("person_relations")
        evidence_table = self.table("evidence")
        claims_table = self.table("claims")
        claim_evidence = self.table("claim_evidence")

        counts = {
            "chapter_snapshots": 0,
            "cases": 0,
            "people": 0,
            "aliases": 0,
            "relations": 0,
            "evidence": 0,
            "claims": 0,
            "claim_links": 0,
            "preserved_existing": 0,
            "removed_existing": 0,
        }
        with self.engine.begin() as connection:
            job = connection.execute(
                select(jobs).where(jobs.c.id == job_id)
            ).mappings().one_or_none()
            if job is None:
                raise LookupError(f"analysis job {job_id} does not exist")
            if str(job["track"]) == "full":
                counts["removed_existing"] = self._clear_existing_analysis(
                    connection,
                    work_id=report.work_id,
                )

            chapter_rows = connection.execute(
                select(chapters_table).where(
                    chapters_table.c.edition_id == report.edition_id
                )
            ).mappings().all()
            chapter_ids = {int(row["number"]): str(row["id"]) for row in chapter_rows}
            for chapter in report.chapters:
                connection.execute(
                    update(chapters_table)
                    .where(
                        chapters_table.c.edition_id == report.edition_id,
                        chapters_table.c.number == chapter.chapter_number,
                    )
                    .values(title=chapter.chapter_title[:300])
                )

            person_ids: dict[str, str] = {}
            for person in self._aggregate_people(report).values():
                person_id = _stable_id(
                    "person",
                    report.work_id,
                    person.name,
                )
                person_ids[person.name.strip().casefold()] = person_id
                inserted = self._insert_once(
                    connection,
                    people,
                    {
                        "id": person_id,
                        "work_id": report.work_id,
                        "canonical_name": person.name[:200],
                        "role": person.role[:200],
                        "description": person.description,
                        "first_chapter": person.first_chapter,
                        "identity_status": "confirmed"
                        if any(item.verified for item in person.citations)
                        else "inferred",
                    },
                )
                counts["people" if inserted else "preserved_existing"] += 1
                for alias in person.aliases:
                    alias_id = _stable_id("person-alias", person_id, alias)
                    alias_inserted = self._insert_once(
                        connection,
                        aliases,
                        {
                            "id": alias_id,
                            "person_id": person_id,
                            "name": alias[:200],
                            "first_chapter": person.first_chapter,
                            "merge_reveal_chapter": None,
                            "evidence_id": None,
                        },
                    )
                    counts[
                        "aliases" if alias_inserted else "preserved_existing"
                    ] += 1

            evidence_by_excerpt: dict[tuple[int, str], str] = {}
            for item in report.evidence_index:
                evidence_id = _stable_id(
                    "evidence",
                    report.work_id,
                    item.evidence_id,
                )
                evidence_by_excerpt[
                    (item.citation.chapter, _normal_text(item.citation.excerpt))
                ] = evidence_id
                inserted = self._insert_once(
                    connection,
                    evidence_table,
                    {
                        "id": evidence_id,
                        "work_id": report.work_id,
                        "case_id": None,
                        "chapter_id": chapter_ids.get(item.citation.chapter),
                        "first_chapter": item.citation.chapter,
                        "title": item.title[:300],
                        "summary": item.summary,
                        "source_type": item.source_type[:40],
                        "status": item.status,
                        "citation": item.citation.model_dump(mode="json"),
                        "lifecycle": {
                            "origin": "ai_analysis",
                            "verified": item.citation.verified,
                            "schema_version": report.schema_version,
                        },
                    },
                )
                counts["evidence" if inserted else "preserved_existing"] += 1

            for relation in self._aggregate_relations(report).values():
                source_id = person_ids.get(relation.source.strip().casefold())
                target_id = person_ids.get(relation.target.strip().casefold())
                if not source_id or not target_id:
                    continue
                relation_id = _stable_id(
                    "relation",
                    report.work_id,
                    relation.source,
                    relation.target,
                    relation.kind,
                    relation.label,
                )
                relation_evidence_id = next(
                    (
                        evidence_id
                        for citation in relation.citations
                        if citation.verified
                        for evidence_id in [
                            evidence_by_excerpt.get(
                                (citation.chapter, _normal_text(citation.excerpt))
                            )
                        ]
                        if evidence_id
                    ),
                    None,
                )
                inserted = self._insert_once(
                    connection,
                    relations,
                    {
                        "id": relation_id,
                        "work_id": report.work_id,
                        "source_person_id": source_id,
                        "target_person_id": target_id,
                        "label": relation.label[:120],
                        "kind": relation.kind[:40],
                        "status": relation.status,
                        "first_chapter": relation.first_chapter,
                        "resolved_chapter": None,
                        "evidence_id": relation_evidence_id,
                    },
                )
                counts["relations" if inserted else "preserved_existing"] += 1

            for claim in self._aggregate_claims(report).values():
                claim_id = _stable_id(
                    "claim",
                    report.work_id,
                    claim.statement,
                )
                inserted = self._insert_once(
                    connection,
                    claims_table,
                    {
                        "id": claim_id,
                        "work_id": report.work_id,
                        "case_id": None,
                        "statement": claim.statement,
                        "status": claim.status,
                        "confidence": claim.confidence,
                        "introduced_chapter": claim.introduced_chapter,
                        "resolved_chapter": claim.resolved_chapter,
                        "reasoning_steps": [
                            f"kind:{claim.kind}",
                            *claim.reasoning,
                        ],
                    },
                )
                counts["claims" if inserted else "preserved_existing"] += 1
                for citation in claim.citations:
                    evidence_id = evidence_by_excerpt.get(
                        (citation.chapter, _normal_text(citation.excerpt))
                    )
                    if not evidence_id:
                        continue
                    link_exists = connection.execute(
                        select(claim_evidence.c.claim_id).where(
                            claim_evidence.c.claim_id == claim_id,
                            claim_evidence.c.evidence_id == evidence_id,
                        )
                    ).scalar_one_or_none()
                    if link_exists is None:
                        connection.execute(
                            insert(claim_evidence).values(
                                claim_id=claim_id,
                                evidence_id=evidence_id,
                                effect="supports",
                                weight=1.0 if citation.verified else 0.25,
                            )
                        )
                        counts["claim_links"] += 1

            for index, mystery in enumerate(report.synthesis.mysteries, start=1):
                case_id = _stable_id(
                    "case",
                    report.work_id,
                    mystery,
                )
                inserted = self._insert_once(
                    connection,
                    cases,
                    {
                        "id": case_id,
                        "work_id": report.work_id,
                        "parent_case_id": None,
                        "title": mystery[:300] or f"Mystery {index}",
                        "summary": mystery,
                        "status": "open",
                    },
                )
                counts["cases" if inserted else "preserved_existing"] += 1

            cumulative_people: list[dict[str, Any]] = []
            cumulative_relations: list[dict[str, Any]] = []
            cumulative_timeline: list[dict[str, Any]] = []
            for chapter in report.chapters:
                cumulative_people.extend(
                    person.model_dump(mode="json") for person in chapter.people
                )
                cumulative_relations.extend(
                    relation.model_dump(mode="json") for relation in chapter.relations
                )
                cumulative_timeline.extend(
                    event.model_dump(mode="json") for event in chapter.events
                )
                snapshot_id = _stable_id(
                    "chapter-snapshot",
                    report.work_id,
                    chapter.chapter_number,
                )
                inserted = self._insert_once(
                    connection,
                    snapshots,
                    {
                        "id": snapshot_id,
                        "work_id": report.work_id,
                        "chapter": chapter.chapter_number,
                        "graph_payload": {
                            "people": cumulative_people,
                            "relations": cumulative_relations,
                        },
                        "timeline_payload": cumulative_timeline,
                        "summary": chapter.summary,
                    },
                )
                counts[
                    "chapter_snapshots" if inserted else "preserved_existing"
                ] += 1

            current_work = connection.execute(
                select(works).where(works.c.id == report.work_id)
            ).mappings().one()
            work_values: dict[str, Any] = {
                "analysis_progress": 100,
                "status": "ready",
            }
            if not current_work["synopsis"]:
                work_values["synopsis"] = report.synthesis.overview
            connection.execute(
                update(works)
                .where(works.c.id == report.work_id)
                .values(**work_values)
            )
            result_payload = report.model_dump(mode="json")
            result_payload["persistence"] = counts
            connection.execute(
                update(jobs)
                .where(jobs.c.id == job_id)
                .values(
                    status="completed",
                    stage="completed",
                    progress=100,
                    error=None,
                    result_summary=result_payload,
                )
            )
        return counts
