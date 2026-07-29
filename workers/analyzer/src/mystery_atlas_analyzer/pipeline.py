from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from typing import Any

from pydantic import BaseModel

from .adaptive import run_adaptive_synthesis
from .contracts import (
    AnalysisCheckpoint,
    AnalysisProgress,
    BookAnalysis,
    BookEditorial,
    BookInput,
    BookInterpretationEditorial,
    BookMysteryEditorial,
    BookStructureEditorial,
    BookSynthesis,
    ChapterAnalysis,
    ChapterEventsResult,
    ChapterInterpretationResult,
    ChapterPeopleRelationsResult,
    ChapterWorkCheckpoint,
    CheckpointCallback,
    ClaimAuditResult,
    ClaimFinding,
    ClaimMergeResult,
    EvidenceAudit,
    EvidenceFinding,
    ModelAdapter,
    PartSynthesis,
    PersonFinding,
    ProgressCallback,
    ReconciliationResult,
    RelationFinding,
    SourceChapter,
    SourceCitation,
    TimelineEvent,
)
from .model_adapters import ModelContentIdleError

logger = logging.getLogger(__name__)

ANALYSIS_STAGES = [
    "source_validation",
    "segment_analysis",
    "chapter_synthesis",
    "book_synthesis",
    "evidence_verification",
    "full_book_reconciliation",
    "persistence",
]


@dataclass(frozen=True)
class PipelineConfig:
    reading_model: str
    truth_model: str = ""
    max_chunk_chars: int = 12_000
    chunk_overlap_chars: int = 500
    chapters_per_batch: int = 6
    max_concurrency: int = 1
    synthesis_batch_chars: int = 40_000

    @property
    def reconciliation_model(self) -> str:
        return self.truth_model or self.reading_model


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    progress: int,
    detail: str,
) -> None:
    if callback:
        callback(AnalysisProgress(stage=stage, progress=progress, detail=detail))


def _split_text(text: str, limit: int, overlap: int) -> list[tuple[int, str]]:
    if limit < 1000:
        raise ValueError("max_chunk_chars must be at least 1000")
    if overlap < 0 or overlap >= limit:
        raise ValueError("chunk_overlap_chars must be between 0 and max_chunk_chars")
    if len(text) <= limit:
        return [(0, text)]

    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        hard_end = min(start + limit, len(text))
        end = hard_end
        if hard_end < len(text):
            candidates = [
                text.rfind("\n", start + limit // 2, hard_end),
                text.rfind("。", start + limit // 2, hard_end),
                text.rfind(". ", start + limit // 2, hard_end),
            ]
            best = max(candidates)
            if best > start:
                end = best + 1
        chunks.append((start, text[start:end]))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _citation_page(chapter: SourceChapter, start_char: int) -> int | None:
    locator = chapter.source_locator
    page_breaks = locator.get("page_breaks", [])
    page: int | None = None
    if isinstance(page_breaks, list):
        for item in page_breaks:
            if not isinstance(item, dict):
                continue
            offset = item.get("offset")
            candidate = item.get("page")
            if isinstance(offset, int) and isinstance(candidate, int) and offset <= start_char:
                page = candidate
    if page is None and isinstance(locator.get("page_start"), int):
        page = int(locator["page_start"])
    return page


def _normalized_positions(text: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        normalized.append(char)
        positions.append(index)
    return "".join(normalized), positions


def _add_segment_context(
    value: Any,
    *,
    segment_start: int,
    segment_end: int,
) -> Any:
    if isinstance(value, SourceCitation):
        locator = dict(value.locator)
        locator.update(
            {
                "segment_start": segment_start,
                "segment_end": segment_end,
            }
        )
        return value.model_copy(update={"locator": locator})
    if isinstance(value, BaseModel):
        return value.model_copy(
            update={
                field: _add_segment_context(
                    getattr(value, field),
                    segment_start=segment_start,
                    segment_end=segment_end,
                )
                for field in type(value).model_fields
            }
        )
    if isinstance(value, list):
        return [
            _add_segment_context(
                item,
                segment_start=segment_start,
                segment_end=segment_end,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _add_segment_context(
                item,
                segment_start=segment_start,
                segment_end=segment_end,
            )
            for key, item in value.items()
        }
    return value


def _verify_citation(
    citation: SourceCitation,
    chapters: dict[int, SourceChapter],
) -> SourceCitation:
    chapter = chapters.get(citation.chapter)
    if chapter is None:
        return citation.model_copy(update={"verified": False})

    search_start = citation.locator.get("segment_start", 0)
    search_end = citation.locator.get("segment_end", len(chapter.text))
    if not isinstance(search_start, int) or not 0 <= search_start < len(chapter.text):
        search_start = 0
    if not isinstance(search_end, int) or not search_start < search_end <= len(chapter.text):
        search_end = len(chapter.text)

    exact_start = chapter.text.find(citation.excerpt, search_start, search_end)
    if exact_start >= 0:
        start = exact_start
        end = start + len(citation.excerpt)
    else:
        normalized_text, positions = _normalized_positions(
            chapter.text[search_start:search_end]
        )
        normalized_excerpt = "".join(citation.excerpt.split())
        normalized_start = normalized_text.find(normalized_excerpt)
        if normalized_start < 0 or not normalized_excerpt:
            return citation.model_copy(
                update={"verified": False}
            )
        start = search_start + positions[normalized_start]
        end_index = normalized_start + len(normalized_excerpt) - 1
        end = search_start + positions[end_index] + 1

    locator = {
        key: value
        for key, value in chapter.source_locator.items()
        if key != "page_breaks"
    }
    if "start_char" in locator:
        locator["source_start_char"] = locator.pop("start_char")
    if "end_char" in locator:
        locator["source_end_char"] = locator.pop("end_char")
    locator.update(
        {
            "chapter": chapter.number,
            "start_char": start,
            "end_char": end,
        }
    )

    return citation.model_copy(
        update={
            "start_char": start,
            "end_char": end,
            "page": _citation_page(chapter, start),
            "locator": locator,
            "verified": True,
        }
    )


def _walk_and_verify(value: Any, chapters: dict[int, SourceChapter]) -> Any:
    if isinstance(value, SourceCitation):
        return _verify_citation(value, chapters)
    if isinstance(value, BaseModel):
        updates: dict[str, Any] = {}
        for field in type(value).model_fields:
            updates[field] = _walk_and_verify(getattr(value, field), chapters)
        return value.model_copy(update=updates)
    if isinstance(value, list):
        return [_walk_and_verify(item, chapters) for item in value]
    if isinstance(value, dict):
        return {key: _walk_and_verify(item, chapters) for key, item in value.items()}
    return value


def _all_citations(value: Any) -> list[SourceCitation]:
    if isinstance(value, SourceCitation):
        return [value]
    if isinstance(value, BaseModel):
        citations: list[SourceCitation] = []
        for field in type(value).model_fields:
            citations.extend(_all_citations(getattr(value, field)))
        return citations
    if isinstance(value, list):
        citations = []
        for item in value:
            citations.extend(_all_citations(item))
        return citations
    if isinstance(value, dict):
        citations = []
        for item in value.values():
            citations.extend(_all_citations(item))
        return citations
    return []


def _citation_key(
    citation: SourceCitation,
) -> tuple[int, int | None, int | None, str]:
    return (
        citation.chapter,
        citation.start_char,
        citation.end_char,
        "".join(citation.excerpt.split()).casefold(),
    )


def _citation_id(citation: SourceCitation) -> str:
    raw = "|".join(
        [
            str(citation.chapter),
            str(citation.start_char),
            str(citation.end_char),
            "".join(citation.excerpt.split()).casefold(),
        ]
    )
    return f"ev-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _verified_citation_catalog(value: Any) -> dict[str, SourceCitation]:
    catalog: dict[str, SourceCitation] = {}
    for citation in _all_citations(value):
        if citation.verified:
            catalog.setdefault(_citation_id(citation), citation)
    return catalog


def _claim_candidates(
    parts: list[PartSynthesis],
    catalog: dict[str, SourceCitation],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for part_index, part in enumerate(parts, start=1):
        for claim_index, claim in enumerate(part.claims, start=1):
            evidence_ids = [
                evidence_id
                for citation in claim.citations
                if citation.verified
                for evidence_id in [_citation_id(citation)]
                if evidence_id in catalog
            ]
            evidence_ids = list(dict.fromkeys(evidence_ids))
            if not evidence_ids:
                continue
            raw_id = (
                f"{part_index}|{claim_index}|{claim.introduced_chapter}|"
                f"{claim.kind}|{claim.statement}"
            )
            claim_id = f"cl-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]}"
            candidates.append(
                {
                    "claim_id": claim_id,
                    "statement": claim.statement,
                    "kind": claim.kind,
                    "status": claim.status,
                    "confidence": claim.confidence,
                    "introduced_chapter": claim.introduced_chapter,
                    "resolved_chapter": claim.resolved_chapter,
                    "reasoning": claim.reasoning,
                    "source_claim_ids": [claim_id],
                    "evidence_ids": evidence_ids,
                }
            )
    return candidates


def _claims_to_candidates(
    claims: list[ClaimFinding],
    catalog: dict[str, SourceCitation],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for claim in claims:
        raw_id = (
            f"{claim.introduced_chapter}|{claim.resolved_chapter}|"
            f"{claim.kind}|{claim.statement}"
        )
        claim_id = f"cl-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]}"
        candidates.append(
            {
                "claim_id": claim_id,
                "statement": claim.statement,
                "kind": claim.kind,
                "status": claim.status,
                "confidence": claim.confidence,
                "introduced_chapter": claim.introduced_chapter,
                "resolved_chapter": claim.resolved_chapter,
                "reasoning": claim.reasoning,
                "source_claim_ids": [claim_id],
                "evidence_ids": list(
                    dict.fromkeys(
                        evidence_id
                        for citation in claim.citations
                        if citation.verified
                        for evidence_id in [_citation_id(citation)]
                        if evidence_id in catalog
                    )
                ),
            }
        )
    return candidates


def _claim_from_candidate(
    candidate: dict[str, Any],
    catalog: dict[str, SourceCitation],
) -> ClaimFinding:
    return ClaimFinding(
        statement=candidate["statement"],
        kind=candidate["kind"],
        status=candidate["status"],
        confidence=candidate["confidence"],
        introduced_chapter=candidate["introduced_chapter"],
        resolved_chapter=candidate["resolved_chapter"],
        reasoning=candidate["reasoning"],
        citations=[
            catalog[evidence_id]
            for evidence_id in candidate["evidence_ids"]
            if evidence_id in catalog
        ],
    )


def _apply_claim_merge(
    result: ClaimMergeResult,
    candidates: list[dict[str, Any]],
    catalog: dict[str, SourceCitation],
) -> list[ClaimFinding]:
    candidates_by_id = {item["claim_id"]: item for item in candidates}
    consumed: set[str] = set()
    claims: list[ClaimFinding] = []
    for decision in result.claims:
        source_ids = [
            claim_id
            for claim_id in dict.fromkeys(decision.source_claim_ids)
            if claim_id in candidates_by_id and claim_id not in consumed
        ]
        if not source_ids:
            continue
        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for claim_id in source_ids
                for evidence_id in candidates_by_id[claim_id]["evidence_ids"]
            )
        )
        claims.append(
            ClaimFinding(
                statement=decision.statement,
                kind=decision.kind,
                status=decision.status,
                confidence=decision.confidence,
                introduced_chapter=decision.introduced_chapter,
                resolved_chapter=decision.resolved_chapter,
                reasoning=decision.reasoning,
                citations=[
                    catalog[evidence_id]
                    for evidence_id in evidence_ids
                    if evidence_id in catalog
                ],
            )
        )
        consumed.update(source_ids)
    claims.extend(
        _claim_from_candidate(candidate, catalog)
        for candidate in candidates
        if candidate["claim_id"] not in consumed
    )
    return claims


def _claim_batch_key(candidates: list[dict[str, Any]]) -> str:
    raw = "|".join(item["claim_id"] for item in candidates)
    return f"claim-batch-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _claim_merge_prompt(
    candidates: list[dict[str, Any]],
    catalog: dict[str, SourceCitation],
) -> str:
    evidence_ids = {
        evidence_id
        for candidate in candidates
        for evidence_id in candidate["evidence_ids"]
    }
    evidence = [
        {
            "evidence_id": evidence_id,
            "chapter": citation.chapter,
            "excerpt": citation.excerpt,
        }
        for evidence_id, citation in catalog.items()
        if evidence_id in evidence_ids
    ]
    return (
        "Merge only semantically equivalent claims. Preserve conflicting claims "
        "separately. Every output claim must list the input claim IDs it represents. "
        "Do not invent claim IDs or evidence.\n\n"
        + json.dumps(
            {
                "claims": candidates,
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
    )


def _claim_leaf_batches(
    candidates: list[dict[str, Any]],
    catalog: dict[str, SourceCitation],
    max_batch_chars: int,
) -> list[list[dict[str, Any]]]:
    if (
        len(candidates) <= 1
        or len(_claim_merge_prompt(candidates, catalog)) <= max_batch_chars
    ):
        return [candidates]
    middle = len(candidates) // 2
    return [
        *_claim_leaf_batches(candidates[:middle], catalog, max_batch_chars),
        *_claim_leaf_batches(candidates[middle:], catalog, max_batch_chars),
    ]


def _combine_claim_merge_outputs(
    results: list[tuple[list[ClaimFinding], list[str], list[str]]],
) -> tuple[list[ClaimFinding], list[str], list[str]]:
    return (
        [claim for result in results for claim in result[0]],
        list(dict.fromkeys(item for result in results for item in result[1])),
        list(dict.fromkeys(item for result in results for item in result[2])),
    )


def _merge_claims_adaptively(
    adapter: ModelAdapter,
    *,
    model: str,
    candidates: list[dict[str, Any]],
    catalog: dict[str, SourceCitation],
    cached_batches: dict[str, ClaimMergeResult],
    on_batch: Callable[[str, ClaimMergeResult], None] | None = None,
    max_batch_chars: int = 40_000,
    max_concurrency: int = 1,
    layer: int = 0,
    parent_batch_id: str | None = None,
    split_keys: set[str] | None = None,
    on_split_decided: Callable[[str], None] | None = None,
) -> tuple[list[ClaimFinding], list[str], list[str]]:
    if not candidates:
        return [], [], []
    batch_key = _claim_batch_key(candidates)
    prompt = _claim_merge_prompt(candidates, catalog)
    if len(candidates) > 1 and len(prompt) > max_batch_chars:
        batches = _claim_leaf_batches(candidates, catalog, max_batch_chars)
        logger.info(
            "AI batch split task=book_claim_merge batch_id=%s "
            "parent_batch_id=%s layer=%d reason=request_chars items=%d "
            "request_chars=%d child_count=%d",
            batch_key,
            parent_batch_id or "none",
            layer,
            len(candidates),
            len(prompt),
            len(batches),
        )

        def merge_batch(
            batch: list[dict[str, Any]],
        ) -> tuple[list[ClaimFinding], list[str], list[str]]:
            return _merge_claims_adaptively(
                adapter,
                model=model,
                candidates=batch,
                catalog=catalog,
                cached_batches=cached_batches,
                on_batch=on_batch,
                max_batch_chars=max_batch_chars,
                max_concurrency=1,
                layer=layer + 1,
                parent_batch_id=batch_key,
                split_keys=split_keys,
                on_split_decided=on_split_decided,
            )

        if max_concurrency > 1 and len(batches) > 1:
            with ThreadPoolExecutor(
                max_workers=min(max_concurrency, len(batches)),
                thread_name_prefix="analysis-claim",
            ) as executor:
                combined = _combine_claim_merge_outputs(
                    list(executor.map(merge_batch, batches))
                )
        else:
            combined = _combine_claim_merge_outputs(
                [merge_batch(batch) for batch in batches]
            )
        if 1 < len(combined[0]) < len(candidates):
            next_level = _merge_claims_adaptively(
                adapter,
                model=model,
                candidates=_claims_to_candidates(combined[0], catalog),
                catalog=catalog,
                cached_batches=cached_batches,
                on_batch=on_batch,
                max_batch_chars=max_batch_chars,
                max_concurrency=max_concurrency,
                layer=layer + 1,
                parent_batch_id=batch_key,
                split_keys=split_keys,
                on_split_decided=on_split_decided,
            )
            return (
                next_level[0],
                list(dict.fromkeys([*combined[1], *next_level[1]])),
                list(dict.fromkeys([*combined[2], *next_level[2]])),
            )
        return combined
    def generate_result(batch: list[dict[str, Any]]) -> ClaimMergeResult:
        current_key = _claim_batch_key(batch)
        current_prompt = _claim_merge_prompt(batch, catalog)
        logger.info(
            "AI batch dispatch task=book_claim_merge batch_id=%s "
            "parent_batch_id=%s layer=%d items=%d request_chars=%d",
            current_key,
            parent_batch_id or "none",
            layer,
            len(batch),
            len(current_prompt),
        )
        return adapter.generate(
            task="book_claim_merge",
            system="You merge evidence-grounded whole-book claims.",
            prompt=current_prompt,
            response_model=ClaimMergeResult,
            model=model,
        )

    def split_candidates(
        batch: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        middle = len(batch) // 2
        return [batch[:middle], batch[middle:]]

    def combine_results(results: list[ClaimMergeResult]) -> ClaimMergeResult:
        return ClaimMergeResult(
            claims=[decision for result in results for decision in result.claims],
            contradictions=list(
                dict.fromkeys(
                    item for result in results for item in result.contradictions
                )
            ),
            uncertainties=list(
                dict.fromkeys(
                    item for result in results for item in result.uncertainties
                )
            ),
        )

    def log_split(
        batch: list[dict[str, Any]],
        exc: Exception,
        children: list[list[dict[str, Any]]],
    ) -> None:
        current_prompt = _claim_merge_prompt(batch, catalog)
        logger.info(
            "AI batch split task=book_claim_merge batch_id=%s "
            "parent_batch_id=%s layer=%d reason=%s items=%d "
            "request_chars=%d response_chars=%s child_count=%d",
            _claim_batch_key(batch),
            parent_batch_id or "none",
            layer,
            "content_idle"
            if isinstance(exc, ModelContentIdleError)
            else "provider_length",
            len(batch),
            len(current_prompt),
            getattr(exc, "response_chars", "unknown"),
            len(children),
        )

    result = run_adaptive_synthesis(
        candidates,
        task="book_claim_merge",
        generate=generate_result,
        can_split=lambda batch: len(batch) > 1,
        split=split_candidates,
        combine=combine_results,
        describe=lambda batch: {
            "items": len(batch),
            "layer": layer,
        },
        cache_key=_claim_batch_key,
        cached=cached_batches,
        on_completed=on_batch,
        on_split=log_split,
        cache_combined=False,
        split_keys=split_keys,
        on_split_decided=on_split_decided,
    )
    return (
        _apply_claim_merge(result, candidates, catalog),
        result.contradictions,
        result.uncertainties,
    )


def _merge_verified_timeline(parts: list[PartSynthesis]) -> list[Any]:
    merged: dict[tuple[int, str], Any] = {}
    for part in parts:
        for event in part.timeline:
            citations = [item for item in event.citations if item.verified]
            if not citations:
                continue
            key = (
                event.chapter,
                " ".join(event.summary.split()).casefold(),
            )
            current = merged.get(key)
            if current is None:
                merged[key] = event.model_copy(update={"citations": citations})
                continue
            citation_map = {
                _citation_key(item): item
                for item in [*current.citations, *citations]
            }
            merged[key] = current.model_copy(
                update={
                    "sequence": min(current.sequence, event.sequence),
                    "citations": list(citation_map.values()),
                }
            )
    return sorted(
        merged.values(),
        key=lambda item: (item.chapter, item.sequence, item.summary.casefold()),
    )


def _evidence_id(item: EvidenceFinding) -> str:
    return _citation_id(item.citation)


def _deduplicate_evidence(chapters: list[ChapterAnalysis]) -> list[EvidenceFinding]:
    items: dict[tuple[int, int | None, int | None, str], EvidenceFinding] = {}
    for chapter in chapters:
        for evidence in chapter.evidence:
            identified = evidence.model_copy(update={"evidence_id": _evidence_id(evidence)})
            key = (
                identified.citation.chapter,
                identified.citation.start_char,
                identified.citation.end_char,
                "".join(identified.citation.excerpt.split()).casefold(),
            )
            items.setdefault(key, identified)
    for citation in _all_citations(chapters):
        key = (
            citation.chapter,
            citation.start_char,
            citation.end_char,
            "".join(citation.excerpt.split()).casefold(),
        )
        if key in items:
            continue
        generated = EvidenceFinding(
            title=f"Source support in chapter {citation.chapter}",
            summary=citation.excerpt,
            source_type="citation",
            status="confirmed" if citation.verified else "uncertain",
            citation=citation,
        )
        items[key] = generated.model_copy(
            update={"evidence_id": _evidence_id(generated)}
        )
    return list(items.values())


def _compact_chapter(chapter: ChapterAnalysis) -> dict[str, Any]:
    return {
        "chapter_number": chapter.chapter_number,
        "chapter_title": chapter.chapter_title,
        "summary": chapter.summary,
        "key_points": chapter.key_points,
        "themes": chapter.themes,
        "people": [
            {
                "name": person.name,
                "role": person.role,
                "description": person.description,
                "first_chapter": person.first_chapter,
            }
            for person in chapter.people
        ],
        "events": [event.model_dump(mode="json") for event in chapter.events],
        "claims": [claim.model_dump(mode="json") for claim in chapter.claims],
        "uncertainties": chapter.uncertainties,
    }


def _segment_prompt(
    book: BookInput,
    chapter: SourceChapter,
    segment_number: int,
    segment_start: int,
    text: str,
) -> str:
    return (
        "Analyze only the supplied book segment. Use the source language only for "
        "person names and exact citation excerpts. "
        "Write all reader-facing analysis in Simplified Chinese, including person "
        "roles, descriptions, and relation labels. Preserve person names and exact "
        "citation excerpts in their original script. Relation kind must use one of "
        "the stable enum codes from the response schema. "
        "Separate explicit author statements from your inferences. Every factual "
        "finding must carry a short verbatim excerpt copied from this segment. "
        "Do not infer facts from later chapters. Citation.chapter must equal the "
        "current chapter number. If the source chapter heading is only an ordinal "
        "(for example, '第三章' or 'Chapter 3'), chapter_title must be a concise, "
        "source-grounded descriptive subtitle. Otherwise preserve the source title."
        f"\n\nBook: {book.title}\nAuthor: {book.author}\n"
        f"Structural path: {' > '.join(chapter.structural_path)}\n"
        f"Chapter: {chapter.number} - {chapter.title}\n"
        f"Segment: {segment_number}, chapter character offset: {segment_start}\n"
        "<source>\n"
        f"{text}\n"
        "</source>"
    )


def _is_ordinal_only_title(title: str) -> bool:
    return bool(
        re.fullmatch(
            r"\s*(?:第[0-9一二三四五六七八九十百千零〇两]+[章节回卷部篇]|"
            r"Chapter\s+[0-9IVXLC]+)\s*",
            title,
            flags=re.IGNORECASE,
        )
    )


def _resolved_chapter_title(
    source_title: str,
    suggested_title: str,
    summary: str,
) -> str:
    source = " ".join(source_title.split())[:160]
    if source and not _is_ordinal_only_title(source):
        return source

    suggestion = " ".join(suggested_title.split()).strip(" -—:：|｜")
    if source and suggestion.casefold().startswith(source.casefold()):
        suggestion = suggestion[len(source) :].strip(" -—:：|｜")
    if not suggestion or suggestion.casefold() == source.casefold():
        suggestion = " ".join(summary.split()).strip(" -—:：|｜")
    suggestion = re.split(r"[。！？!?；;]", suggestion, maxsplit=1)[0].strip()
    if not suggestion:
        return source
    return f"{source}｜{suggestion[:60]}" if source else suggestion[:80]


def _combine_chapter_people_relations(
    results: list[ChapterPeopleRelationsResult],
) -> ChapterPeopleRelationsResult:
    # Entity identity is not implied by a shared display name or citation. The
    # bounded model task may deduplicate within one response, but independently
    # synthesized subgroups stay separate without an explicit equivalence ID.
    people = [person for result in results for person in result.people]
    relations: dict[tuple[str, str, str, str, int], Any] = {}
    for result in results:
        for relation in result.relations:
            key = (
                relation.source.casefold(),
                relation.target.casefold(),
                relation.label.casefold(),
                relation.kind,
                relation.first_chapter,
            )
            current = relations.get(key)
            if current is None:
                relations[key] = relation
                continue
            relations[key] = current.model_copy(
                update={
                    "evidence_ids": list(
                        dict.fromkeys(
                            [*current.evidence_ids, *relation.evidence_ids]
                        )
                    )
                }
            )
    return ChapterPeopleRelationsResult(
        people=people,
        relations=list(relations.values()),
    )


def _synthesize_chapter(
    adapter: ModelAdapter,
    config: PipelineConfig,
    chapter: SourceChapter,
    segments: list[ChapterAnalysis],
    *,
    work_checkpoint: ChapterWorkCheckpoint | None = None,
    on_work_checkpoint: Callable[[ChapterWorkCheckpoint, str], None] | None = None,
) -> ChapterAnalysis:
    if len(segments) == 1:
        segment = segments[0]
        return segments[0].model_copy(
            update={
                "chapter_number": chapter.number,
                "chapter_title": _resolved_chapter_title(
                    chapter.title,
                    segment.chapter_title,
                    segment.summary,
                ),
            }
        )
    active_work = work_checkpoint or ChapterWorkCheckpoint()
    verified_segments = [
        _walk_and_verify(segment, {chapter.number: chapter}) for segment in segments
    ]
    evidence = _deduplicate_evidence(verified_segments)
    evidence_by_key = {
        _citation_key(item.citation): item.evidence_id
        for item in evidence
        if item.citation.verified
    }
    citation_catalog = {
        item.evidence_id: item.citation
        for item in evidence
        if item.evidence_id and item.citation.verified
    }

    def evidence_ids(citations: list[SourceCitation]) -> list[str]:
        return list(
            dict.fromkeys(
                evidence_id
                for citation in citations
                if citation.verified
                for evidence_id in [evidence_by_key.get(_citation_key(citation), "")]
                if evidence_id
            )
        )

    def payload_for(batch: list[ChapterAnalysis], group: str) -> dict[str, Any]:
        if group == "people_relations":
            candidates: dict[str, Any] = {
                "people": [
                    {
                        "name": person.name,
                        "aliases": person.aliases,
                        "role": person.role,
                        "description": person.description,
                        "first_chapter": person.first_chapter,
                        "evidence_ids": evidence_ids(person.citations),
                    }
                    for segment in batch
                    for person in segment.people
                ],
                "relations": [
                    {
                        "source": relation.source,
                        "target": relation.target,
                        "label": relation.label,
                        "kind": relation.kind,
                        "status": relation.status,
                        "first_chapter": relation.first_chapter,
                        "evidence_ids": evidence_ids(relation.citations),
                    }
                    for segment in batch
                    for relation in segment.relations
                ],
            }
        elif group == "events_evidence":
            candidates = {
                "events": [
                    {
                        "chapter": event.chapter,
                        "sequence": event.sequence,
                        "summary": event.summary,
                        "story_time": event.story_time,
                        "narrative_time": event.narrative_time,
                        "evidence_ids": evidence_ids(event.citations),
                    }
                    for segment in batch
                    for event in segment.events
                ]
            }
        else:
            candidates = {
                "segment_summaries": [segment.summary for segment in batch],
                "key_points": [
                    point for segment in batch for point in segment.key_points
                ],
                "themes": [theme for segment in batch for theme in segment.themes],
                "claims": [
                    {
                        "statement": claim.statement,
                        "kind": claim.kind,
                        "status": claim.status,
                        "confidence": claim.confidence,
                        "introduced_chapter": claim.introduced_chapter,
                        "resolved_chapter": claim.resolved_chapter,
                        "reasoning": claim.reasoning,
                        "evidence_ids": evidence_ids(claim.citations),
                    }
                    for segment in batch
                    for claim in segment.claims
                ],
                "uncertainties": [
                    uncertainty
                    for segment in batch
                    for uncertainty in segment.uncertainties
                ],
            }
        referenced_ids = {
            evidence_id
            for value in candidates.values()
            if isinstance(value, list)
            for item in value
            if isinstance(item, dict)
            for evidence_id in item.get("evidence_ids", [])
        }
        return {
            "chapter": {"number": chapter.number, "title": chapter.title},
            "candidates": candidates,
            "evidence_catalog": [
                {
                    "evidence_id": evidence_id,
                    "chapter": citation.chapter,
                    "excerpt": citation.excerpt,
                }
                for evidence_id, citation in citation_catalog.items()
                if evidence_id in referenced_ids
            ],
        }

    def split_batch(batch: list[ChapterAnalysis]) -> list[list[ChapterAnalysis]]:
        midpoint = len(batch) // 2
        return [batch[:midpoint], batch[midpoint:]]

    def batch_cache_key(batch: list[ChapterAnalysis]) -> str:
        raw = "|".join(
            hashlib.sha256(
                item.model_dump_json().encode("utf-8")
            ).hexdigest()
            for item in batch
        )
        return f"batch-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"

    def merge_people_relations(
        results: list[ChapterPeopleRelationsResult],
    ) -> ChapterPeopleRelationsResult:
        return _combine_chapter_people_relations(results)

    def merge_events(results: list[ChapterEventsResult]) -> ChapterEventsResult:
        events: dict[tuple[int, str], Any] = {}
        for result in results:
            for event in result.events:
                key = (event.chapter, event.summary.casefold())
                current = events.get(key)
                if current is None:
                    events[key] = event
                    continue
                events[key] = current.model_copy(
                    update={
                        "sequence": min(current.sequence, event.sequence),
                        "evidence_ids": list(
                            dict.fromkeys(
                                [*current.evidence_ids, *event.evidence_ids]
                            )
                        ),
                    }
                )
        return ChapterEventsResult(events=list(events.values()))

    def merge_interpretation(
        results: list[ChapterInterpretationResult],
    ) -> ChapterInterpretationResult:
        claims: dict[tuple[str, str, int], Any] = {}
        for result in results:
            for claim in result.claims:
                key = (
                    claim.statement.casefold(),
                    claim.kind,
                    claim.introduced_chapter,
                )
                current = claims.get(key)
                if current is None:
                    claims[key] = claim
                    continue
                claims[key] = current.model_copy(
                    update={
                        "evidence_ids": list(
                            dict.fromkeys(
                                [*current.evidence_ids, *claim.evidence_ids]
                            )
                        )
                    }
                )
        return ChapterInterpretationResult(
            chapter_title=next(
                (result.chapter_title for result in results if result.chapter_title),
                chapter.title,
            ),
            summary="\n".join(
                dict.fromkeys(result.summary for result in results if result.summary)
            ),
            key_points=list(
                dict.fromkeys(
                    point for result in results for point in result.key_points
                )
            ),
            themes=list(
                dict.fromkeys(theme for result in results for theme in result.themes)
            ),
            claims=list(claims.values()),
            uncertainties=list(
                dict.fromkeys(
                    item for result in results for item in result.uncertainties
                )
            ),
        )

    def run_group(
        *,
        task: str,
        group: str,
        response_model: type[BaseModel],
        combine: Callable[[list[Any]], Any],
        cache_field: str,
        split_field: str,
        progress_label: str,
    ) -> Any:
        nonlocal active_work
        cache = dict(getattr(active_work, cache_field))
        split_markers = set(getattr(active_work, split_field))

        if on_work_checkpoint:
            on_work_checkpoint(
                active_work,
                f"{progress_label.removesuffix(' checkpointed')} in progress",
            )

        def generate(batch: list[ChapterAnalysis]) -> Any:
            if on_work_checkpoint:
                on_work_checkpoint(
                    active_work,
                    (
                        f"{progress_label.removesuffix(' checkpointed')} "
                        f"subgroup in progress ({len(batch)} segments)"
                    ),
                )
            prompt = (
                "Consolidate only the supplied candidate fields. Merge duplicates "
                "only when they clearly describe the same item; preserve uncertain "
                "or conflicting items separately. Every factual output must retain "
                "one or more evidence_ids from the catalog. Never invent an ID, "
                "quote, or fact. Write reader-facing analysis in Simplified Chinese "
                "while preserving person names.\n\n"
                + json.dumps(payload_for(batch, group), ensure_ascii=False)
            )
            return adapter.generate(
                task=task,
                system="You are a meticulous chapter analysis editor.",
                prompt=prompt,
                response_model=response_model,
                model=config.reading_model,
            )

        def save_completed(key: str, result: Any) -> None:
            nonlocal active_work
            cache[key] = result
            active_work = active_work.model_copy(
                update={cache_field: dict(cache)}, deep=True
            )
            if on_work_checkpoint:
                on_work_checkpoint(active_work, progress_label)

        def save_split(key: str) -> None:
            nonlocal active_work
            split_markers.add(key)
            active_work = active_work.model_copy(
                update={split_field: set(split_markers)}, deep=True
            )
            if on_work_checkpoint:
                on_work_checkpoint(
                    active_work,
                    (
                        f"{progress_label.removesuffix(' checkpointed')} split; "
                        "subgroup in progress"
                    ),
                )

        return run_adaptive_synthesis(
            verified_segments,
            task=task,
            generate=generate,
            can_split=lambda batch: len(batch) > 1,
            split=split_batch,
            combine=combine,
            describe=lambda batch: {
                "chapter": chapter.number,
                "segments": len(batch),
            },
            cache_key=batch_cache_key,
            cached=cache,
            on_completed=save_completed,
            split_keys=split_markers,
            on_split_decided=save_split,
        )

    people_relations = run_group(
        task="chapter_people_relations",
        group="people_relations",
        response_model=ChapterPeopleRelationsResult,
        combine=merge_people_relations,
        cache_field="people_relations_batches",
        split_field="people_relations_splits",
        progress_label="people and relations checkpointed",
    )
    events_result = run_group(
        task="chapter_events_evidence",
        group="events_evidence",
        response_model=ChapterEventsResult,
        combine=merge_events,
        cache_field="events_batches",
        split_field="events_splits",
        progress_label="events and evidence checkpointed",
    )
    interpretation = run_group(
        task="chapter_interpretation",
        group="interpretation",
        response_model=ChapterInterpretationResult,
        combine=merge_interpretation,
        cache_field="interpretation_batches",
        split_field="interpretation_splits",
        progress_label="interpretation checkpointed",
    )

    def citations_for(ids: list[str]) -> list[SourceCitation]:
        return [
            citation_catalog[evidence_id]
            for evidence_id in dict.fromkeys(ids)
            if evidence_id in citation_catalog
        ]

    def has_valid_evidence(ids: list[str]) -> bool:
        return bool(ids) and all(evidence_id in citation_catalog for evidence_id in ids)

    return ChapterAnalysis(
        chapter_number=chapter.number,
        chapter_title=_resolved_chapter_title(
            chapter.title,
            interpretation.chapter_title,
            interpretation.summary,
        ),
        summary=interpretation.summary,
        key_points=interpretation.key_points,
        themes=interpretation.themes,
        people=[
            PersonFinding(
                name=person.name,
                aliases=person.aliases,
                role=person.role,
                description=person.description,
                first_chapter=person.first_chapter,
                citations=citations_for(person.evidence_ids),
            )
            for person in people_relations.people
            if has_valid_evidence(person.evidence_ids)
            and person.first_chapter <= chapter.number
        ],
        relations=[
            RelationFinding(
                source=relation.source,
                target=relation.target,
                label=relation.label,
                kind=relation.kind,
                status=relation.status,
                first_chapter=relation.first_chapter,
                citations=citations_for(relation.evidence_ids),
            )
            for relation in people_relations.relations
            if has_valid_evidence(relation.evidence_ids)
            and relation.first_chapter <= chapter.number
        ],
        events=[
            TimelineEvent(
                chapter=event.chapter,
                sequence=event.sequence,
                summary=event.summary,
                story_time=event.story_time,
                narrative_time=event.narrative_time,
                citations=citations_for(event.evidence_ids),
            )
            for event in events_result.events
            if has_valid_evidence(event.evidence_ids)
            and event.chapter == chapter.number
        ],
        evidence=evidence,
        claims=[
            ClaimFinding(
                statement=claim.statement,
                kind=claim.kind,
                status=claim.status,
                confidence=claim.confidence,
                introduced_chapter=claim.introduced_chapter,
                resolved_chapter=claim.resolved_chapter,
                reasoning=claim.reasoning,
                citations=citations_for(claim.evidence_ids),
            )
            for claim in interpretation.claims
            if has_valid_evidence(claim.evidence_ids)
            and claim.introduced_chapter <= chapter.number
            and (
                claim.resolved_chapter is None
                or claim.introduced_chapter
                <= claim.resolved_chapter
                <= chapter.number
            )
        ],
        uncertainties=interpretation.uncertainties,
    )


def _synthesize_parts(
    adapter: ModelAdapter,
    config: PipelineConfig,
    chapters: list[ChapterAnalysis],
    source_chapters: dict[int, SourceChapter],
    on_batch_completed: Callable[[int, int], None] | None = None,
) -> list[PartSynthesis]:
    batches: list[list[ChapterAnalysis]] = []
    current: list[ChapterAnalysis] = []
    current_parent: tuple[str, ...] | None = None
    for chapter in chapters:
        source = source_chapters.get(chapter.chapter_number)
        parent = (
            tuple(source.structural_path[:-1])
            if source and len(source.structural_path) > 1
            else None
        )
        if current and (
            parent != current_parent
            or len(current) >= config.chapters_per_batch
        ):
            batches.append(current)
            current = []
        current.append(chapter)
        current_parent = parent
    if current:
        batches.append(current)

    def synthesize_batch(batch: list[ChapterAnalysis]) -> PartSynthesis:
        first_source = source_chapters.get(batch[0].chapter_number)
        parent_path = (
            first_source.structural_path[:-1]
            if first_source and len(first_source.structural_path) > 1
            else []
        )
        prompt = (
            "Synthesize this consecutive group of chapter analyses. Preserve "
            "citations inside timeline events and claims. Identify cross-chapter "
            "development, contradictions, foreshadowing, and unresolved questions. "
            "Do not resolve anything using chapters outside this group.\n\n"
            f"Structural group: {' > '.join(parent_path) or 'automatic batch'}\n"
            f"{json.dumps([_compact_chapter(item) for item in batch], ensure_ascii=False)}"
        )
        part = adapter.generate(
            task="part_synthesis",
            system="You build evidence-grounded hierarchical book summaries.",
            prompt=prompt,
            response_model=PartSynthesis,
            model=config.reading_model,
        )
        return part.model_copy(
            update={"chapter_numbers": [item.chapter_number for item in batch]}
        )

    def synthesize_adaptively(
        batch: list[ChapterAnalysis],
    ) -> list[PartSynthesis]:
        def split(items: list[ChapterAnalysis]) -> list[list[ChapterAnalysis]]:
            midpoint = len(items) // 2
            return [items[:midpoint], items[midpoint:]]

        return run_adaptive_synthesis(
            batch,
            task="part_synthesis",
            generate=lambda items: [synthesize_batch(items)],
            can_split=lambda items: len(items) > 1,
            split=split,
            combine=lambda groups: [part for group in groups for part in group],
            describe=lambda items: {
                "first_chapter": items[0].chapter_number,
                "last_chapter": items[-1].chapter_number,
                "chapters": len(items),
            },
        )

    if config.max_concurrency == 1 or len(batches) == 1:
        grouped_parts: list[list[PartSynthesis]] = []
        for completed, batch in enumerate(batches, start=1):
            grouped_parts.append(synthesize_adaptively(batch))
            if on_batch_completed:
                on_batch_completed(completed, len(batches))
        return [part for group in grouped_parts for part in group]

    ordered_groups: dict[int, list[PartSynthesis]] = {}
    with ThreadPoolExecutor(
        max_workers=min(config.max_concurrency, len(batches)),
        thread_name_prefix="analysis-part",
    ) as executor:
        futures = {
            executor.submit(synthesize_adaptively, batch): index
            for index, batch in enumerate(batches)
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            ordered_groups[futures[future]] = future.result()
            if on_batch_completed:
                on_batch_completed(completed, len(batches))
    return [
        part
        for index in range(len(batches))
        for part in ordered_groups[index]
    ]


def _analyze_source_chapter(
    book: BookInput,
    chapter: SourceChapter,
    adapter: ModelAdapter,
    config: PipelineConfig,
    *,
    work_checkpoint: ChapterWorkCheckpoint | None = None,
    on_work_checkpoint: Callable[[ChapterWorkCheckpoint, str], None] | None = None,
) -> ChapterAnalysis:
    source_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "chapter": chapter.number,
                "text": chapter.text,
                "max_chunk_chars": config.max_chunk_chars,
                "chunk_overlap_chars": config.chunk_overlap_chars,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    active_work = (
        work_checkpoint.model_copy(deep=True)
        if work_checkpoint is not None
        and work_checkpoint.source_fingerprint == source_fingerprint
        else ChapterWorkCheckpoint(source_fingerprint=source_fingerprint)
    )

    def save_work(detail: str, **updates: Any) -> None:
        nonlocal active_work
        active_work = active_work.model_copy(update=updates, deep=True)
        if on_work_checkpoint:
            on_work_checkpoint(active_work.model_copy(deep=True), detail)

    segments: list[ChapterAnalysis] = []
    source_segments = _split_text(
        chapter.text,
        config.max_chunk_chars,
        config.chunk_overlap_chars,
    )
    segment_cache = dict(active_work.segments)
    for segment_number, (segment_start, segment_text) in enumerate(source_segments, start=1):
        raw_key = f"{segment_start}|{len(segment_text)}|{segment_text}"
        segment_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:20]
        if segment_key in segment_cache:
            segments.append(segment_cache[segment_key])
            continue
        if on_work_checkpoint:
            on_work_checkpoint(
                active_work.model_copy(deep=True),
                f"segment {segment_number}/{len(source_segments)} in progress",
            )
        result = adapter.generate(
            task="segment_analysis",
            system=(
                "You are a rigorous book analyst. Ground every factual finding "
                "in the supplied source and return structured JSON."
            ),
            prompt=_segment_prompt(
                book,
                chapter,
                segment_number,
                segment_start,
                segment_text,
            ),
            response_model=ChapterAnalysis,
            model=config.reading_model,
        )
        result = _add_segment_context(
            result,
            segment_start=segment_start,
            segment_end=segment_start + len(segment_text),
        )
        analyzed_segment = result.model_copy(
            update={
                "chapter_number": chapter.number,
            }
        )
        segments.append(analyzed_segment)
        segment_cache[segment_key] = analyzed_segment
        save_work(
            f"segment {segment_number}/{len(source_segments)} checkpointed",
            segments=dict(segment_cache),
        )
    return _synthesize_chapter(
        adapter,
        config,
        chapter,
        segments,
        work_checkpoint=active_work,
        on_work_checkpoint=lambda update, detail: save_work(
            detail,
            people_relations_batches=update.people_relations_batches,
            people_relations_splits=update.people_relations_splits,
            events_batches=update.events_batches,
            events_splits=update.events_splits,
            interpretation_batches=update.interpretation_batches,
            interpretation_splits=update.interpretation_splits,
        ),
    )


def _compact_editorial_part(part: PartSynthesis) -> dict[str, Any]:
    return {
        "chapter_numbers": part.chapter_numbers,
        "summary": part.summary,
        "core_ideas": part.core_ideas,
        "themes": part.themes,
        "character_arcs": part.character_arcs,
        "mysteries": part.mysteries,
        "contradictions": part.contradictions,
        "foreshadowing": part.foreshadowing,
        "uncertainties": part.uncertainties,
    }


def _editorial_prompt(
    book: BookInput,
    parts: list[PartSynthesis],
    timeline: list[Any],
    claims: list[ClaimFinding],
) -> str:
    return (
        "Produce the reader-facing whole-book editorial synthesis. Explain "
        "the book's structure, central ideas, themes, character arcs, timeline, "
        "mysteries, contradictions, foreshadowing, and practical implications. "
        "Keep author-explicit claims separate from analysis inferences. Do not invent "
        "new facts. Timeline and claims are authoritative inputs and must not be "
        "rewritten or returned.\n\n"
        f"Book: {book.title}\nAuthor: {book.author}\n"
        + json.dumps(
            {
                "parts": [_compact_editorial_part(item) for item in parts],
                "timeline_index": [
                    {
                        "chapter": item.chapter,
                        "sequence": item.sequence,
                        "summary": item.summary,
                    }
                    for item in timeline
                ],
                "claims": [
                    {
                        "statement": item.statement,
                        "kind": item.kind,
                        "status": item.status,
                        "introduced_chapter": item.introduced_chapter,
                        "resolved_chapter": item.resolved_chapter,
                    }
                    for item in claims
                ],
            },
            ensure_ascii=False,
        )
    )


def _generate_editorial_adaptively(
    adapter: ModelAdapter,
    *,
    model: str,
    prompt: str,
    split_mode: bool,
    cached_sections: dict[str, BaseModel],
    on_split: Callable[[], None] | None = None,
    on_section: Callable[[str, BaseModel], None] | None = None,
) -> BookEditorial:
    section_specs: dict[str, tuple[str, type[BaseModel], str]] = {
        "structure": (
            "book_editorial_structure",
            BookStructureEditorial,
            "Return only the overview and structural sections.",
        ),
        "interpretation": (
            "book_editorial_interpretation",
            BookInterpretationEditorial,
            "Return only core ideas, themes, character arcs, and action insights.",
        ),
        "mysteries": (
            "book_editorial_mysteries",
            BookMysteryEditorial,
            "Return only mysteries, contradictions, foreshadowing, and uncertainties.",
        ),
    }

    def generate(keys: tuple[str, ...]) -> BaseModel:
        key = keys[0]
        if key == "full":
            return adapter.generate(
                task="book_editorial",
                system=(
                    "You write a whole-book analysis from an authoritative fact index."
                ),
                prompt=prompt,
                response_model=BookEditorial,
                model=model,
            )
        task, response_model, instruction = section_specs[key]
        return adapter.generate(
            task=task,
            system="You write one bounded section of a whole-book analysis.",
            prompt=f"{instruction}\n\n{prompt}",
            response_model=response_model,
            model=model,
        )

    def combine(results: list[BaseModel]) -> BaseModel:
        resolved = {
            key: result
            for key, result in zip(section_specs, results, strict=True)
        }
        structure = BookStructureEditorial.model_validate(resolved["structure"])
        interpretation = BookInterpretationEditorial.model_validate(
            resolved["interpretation"]
        )
        mysteries = BookMysteryEditorial.model_validate(resolved["mysteries"])
        return BookEditorial(
            **structure.model_dump(mode="python"),
            **interpretation.model_dump(mode="python"),
            **mysteries.model_dump(mode="python"),
        )

    def complete(key: str, result: BaseModel) -> None:
        if on_section:
            on_section(key, result)

    def run(keys: tuple[str, ...]) -> BaseModel:
        return run_adaptive_synthesis(
            keys,
            task="book_editorial",
            generate=generate,
            can_split=lambda value: value == ("full",),
            split=lambda value: [(key,) for key in section_specs],
            combine=combine,
            describe=lambda value: {"scope": value[0]},
            cache_key=lambda value: "" if value == ("full",) else value[0],
            cached=cached_sections,
            on_completed=complete,
            on_split=(
                (lambda value, exc, children: on_split()) if on_split else None
            ),
        )

    if not split_mode:
        return BookEditorial.model_validate(run(("full",)))
    return BookEditorial.model_validate(
        combine([run((key,)) for key in section_specs])
    )


def _book_claim_id(claim: ClaimFinding) -> str:
    raw = (
        f"{claim.introduced_chapter}|{claim.resolved_chapter}|"
        f"{claim.kind}|{claim.statement}"
    )
    return f"book-cl-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _claim_audit_payload(
    claims: list[ClaimFinding],
    catalog: dict[str, SourceCitation],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claim_payload: list[dict[str, Any]] = []
    used_evidence_ids: set[str] = set()
    for claim in claims:
        evidence_ids = [
            evidence_id
            for citation in claim.citations
            if citation.verified
            for evidence_id in [_citation_id(citation)]
            if evidence_id in catalog
        ]
        evidence_ids = list(dict.fromkeys(evidence_ids))
        used_evidence_ids.update(evidence_ids)
        claim_payload.append(
            {
                "claim_id": _book_claim_id(claim),
                "statement": claim.statement,
                "kind": claim.kind,
                "status": claim.status,
                "confidence": claim.confidence,
                "introduced_chapter": claim.introduced_chapter,
                "resolved_chapter": claim.resolved_chapter,
                "reasoning": claim.reasoning,
                "evidence_ids": evidence_ids,
            }
        )
    evidence_payload = [
        {
            "evidence_id": evidence_id,
            "chapter": citation.chapter,
            "excerpt": citation.excerpt,
        }
        for evidence_id, citation in catalog.items()
        if evidence_id in used_evidence_ids
    ]
    return claim_payload, evidence_payload


def _claim_audit_prompt(
    claims: list[ClaimFinding],
    catalog: dict[str, SourceCitation],
) -> str:
    claim_payload, evidence_payload = _claim_audit_payload(claims, catalog)
    return (
        "Audit each claim only against its listed verified evidence IDs. Return one "
        "decision for every claim_id. Unsupported claims must not be treated as "
        "facts. Never invent claim IDs or evidence.\n\n"
        + json.dumps(
            {
                "claims": claim_payload,
                "evidence": evidence_payload,
            },
            ensure_ascii=False,
        )
    )


def _apply_claim_audit(
    claims: list[ClaimFinding],
    audit: ClaimAuditResult,
) -> ReconciliationResult:
    decisions = {item.claim_id: item for item in audit.decisions}
    final_claims: list[ClaimFinding] = []
    unsupported: list[str] = []
    uncertainties = list(audit.uncertainties)
    for claim in claims:
        decision = decisions.get(_book_claim_id(claim))
        if decision is not None and decision.verdict == "unsupported":
            unsupported.append(claim.statement)
            continue
        if decision is None or decision.verdict == "uncertain":
            final_claims.append(claim.model_copy(update={"status": "uncertain"}))
            if claim.statement not in uncertainties:
                uncertainties.append(claim.statement)
            continue
        final_claims.append(claim)
    return ReconciliationResult(
        final_claims=final_claims,
        contradictions=audit.contradictions,
        unsupported_claims=unsupported,
        uncertainties=uncertainties,
        review_notes=audit.review_notes,
    )


def _claim_audit_batch_key(claims: list[ClaimFinding]) -> str:
    raw = "|".join(_book_claim_id(claim) for claim in claims)
    return f"claim-audit-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _combine_reconciliations(
    left: ReconciliationResult,
    right: ReconciliationResult,
) -> ReconciliationResult:
    return ReconciliationResult(
        final_claims=[*left.final_claims, *right.final_claims],
        contradictions=list(
            dict.fromkeys([*left.contradictions, *right.contradictions])
        ),
        unsupported_claims=list(
            dict.fromkeys(
                [*left.unsupported_claims, *right.unsupported_claims]
            )
        ),
        uncertainties=list(
            dict.fromkeys([*left.uncertainties, *right.uncertainties])
        ),
        review_notes=[*left.review_notes, *right.review_notes],
    )


def _claim_audit_leaf_batches(
    claims: list[ClaimFinding],
    catalog: dict[str, SourceCitation],
    max_batch_chars: int,
) -> list[list[ClaimFinding]]:
    if (
        len(claims) <= 1
        or len(_claim_audit_prompt(claims, catalog)) <= max_batch_chars
    ):
        return [claims]
    middle = len(claims) // 2
    return [
        *_claim_audit_leaf_batches(
            claims[:middle],
            catalog,
            max_batch_chars,
        ),
        *_claim_audit_leaf_batches(
            claims[middle:],
            catalog,
            max_batch_chars,
        ),
    ]


def _audit_claims_adaptively(
    adapter: ModelAdapter,
    *,
    model: str,
    claims: list[ClaimFinding],
    catalog: dict[str, SourceCitation],
    cached_batches: dict[str, ClaimAuditResult],
    on_batch: Callable[[str, ClaimAuditResult], None] | None = None,
    max_batch_chars: int = 40_000,
    max_concurrency: int = 1,
    split_keys: set[str] | None = None,
    on_split_decided: Callable[[str], None] | None = None,
) -> ReconciliationResult:
    if not claims:
        return ReconciliationResult()
    prompt = _claim_audit_prompt(claims, catalog)
    if len(claims) > 1 and len(prompt) > max_batch_chars:
        batches = _claim_audit_leaf_batches(
            claims,
            catalog,
            max_batch_chars,
        )

        def audit_batch(batch: list[ClaimFinding]) -> ReconciliationResult:
            return _audit_claims_adaptively(
                adapter,
                model=model,
                claims=batch,
                catalog=catalog,
                cached_batches=cached_batches,
                on_batch=on_batch,
                max_batch_chars=max_batch_chars,
                max_concurrency=1,
                split_keys=split_keys,
                on_split_decided=on_split_decided,
            )

        if max_concurrency > 1 and len(batches) > 1:
            with ThreadPoolExecutor(
                max_workers=min(max_concurrency, len(batches)),
                thread_name_prefix="analysis-audit",
            ) as executor:
                results = list(executor.map(audit_batch, batches))
        else:
            results = [audit_batch(batch) for batch in batches]
        combined = ReconciliationResult()
        for result in results:
            combined = _combine_reconciliations(combined, result)
        return combined

    def generate_audit(batch: list[ClaimFinding]) -> ClaimAuditResult:
        return adapter.generate(
                task="book_claim_audit",
                system="You are the final evidence auditor for whole-book claims.",
                prompt=_claim_audit_prompt(batch, catalog),
                response_model=ClaimAuditResult,
                model=model,
                temperature=0,
            )

    def split_claims(batch: list[ClaimFinding]) -> list[list[ClaimFinding]]:
        middle = len(batch) // 2
        return [batch[:middle], batch[middle:]]

    def combine_audits(results: list[ClaimAuditResult]) -> ClaimAuditResult:
        return ClaimAuditResult(
            decisions=[decision for result in results for decision in result.decisions],
            contradictions=list(
                dict.fromkeys(
                    item for result in results for item in result.contradictions
                )
            ),
            uncertainties=list(
                dict.fromkeys(
                    item for result in results for item in result.uncertainties
                )
            ),
            review_notes=list(
                dict.fromkeys(
                    item for result in results for item in result.review_notes
                )
            ),
        )

    audit = run_adaptive_synthesis(
        claims,
        task="book_claim_audit",
        generate=generate_audit,
        can_split=lambda batch: len(batch) > 1,
        split=split_claims,
        combine=combine_audits,
        describe=lambda batch: {"claims": len(batch)},
        cache_key=_claim_audit_batch_key,
        cached=cached_batches,
        on_completed=on_batch,
        cache_combined=False,
        split_keys=split_keys,
        on_split_decided=on_split_decided,
    )
    return _apply_claim_audit(claims, audit)


def _reconciliation_prompt(
    synthesis: BookSynthesis,
    evidence: list[EvidenceFinding],
) -> str:
    evidence_payload = [
        {
            "evidence_id": item.evidence_id,
            "title": item.title,
            "summary": item.summary,
            "citation": item.citation.model_dump(mode="json"),
        }
        for item in evidence
        if item.citation.verified
    ]
    return (
        "Audit the proposed whole-book claims against the verified evidence index. "
        "Return corrected final claims, explicit contradictions, unsupported claims, "
        "remaining uncertainties, and review notes. A claim without verified support "
        "must be marked uncertain or listed as unsupported. Never treat an inference "
        "as an explicit author statement.\n\n"
        "<synthesis>"
        f"{json.dumps(synthesis.model_dump(mode='json'), ensure_ascii=False)}"
        "</synthesis>\n"
        f"<verified_evidence>{json.dumps(evidence_payload, ensure_ascii=False)}</verified_evidence>"
    )


def _reconciliation_evidence(
    synthesis: BookSynthesis,
    evidence: list[EvidenceFinding],
) -> list[EvidenceFinding]:
    """Keep only verified evidence that directly supports a synthesized claim."""
    claim_citations = [
        citation for citation in _all_citations(synthesis.claims) if citation.verified
    ]
    selected: dict[tuple[int, int | None, int | None, str], EvidenceFinding] = {}

    def citation_key(citation: SourceCitation) -> tuple[int, int | None, int | None, str]:
        return (
            citation.chapter,
            citation.start_char,
            citation.end_char,
            "".join(citation.excerpt.split()).casefold(),
        )

    for item in evidence:
        if not item.citation.verified:
            continue
        item_key = citation_key(item.citation)
        for citation in claim_citations:
            claim_key = citation_key(citation)
            same_excerpt = (
                item.citation.chapter == citation.chapter and item_key[3] == claim_key[3]
            )
            overlapping_range = (
                item.citation.chapter == citation.chapter
                and item.citation.start_char is not None
                and item.citation.end_char is not None
                and citation.start_char is not None
                and citation.end_char is not None
                and item.citation.start_char < citation.end_char
                and citation.start_char < item.citation.end_char
            )
            if same_excerpt or overlapping_range:
                selected[item_key] = item
                break

    for citation in claim_citations:
        key = citation_key(citation)
        if key in selected:
            continue
        generated = EvidenceFinding(
            title=f"Verified support for synthesized claim in chapter {citation.chapter}",
            summary=citation.excerpt,
            source_type="citation",
            status="confirmed",
            citation=citation,
        )
        selected[key] = generated.model_copy(
            update={"evidence_id": _evidence_id(generated)}
        )
    return list(selected.values())


def analyze_book(
    book: BookInput,
    adapter: ModelAdapter,
    config: PipelineConfig,
    on_progress: ProgressCallback | None = None,
    *,
    checkpoint: AnalysisCheckpoint | None = None,
    on_checkpoint: CheckpointCallback | None = None,
) -> BookAnalysis:
    """Analyze a complete book through the module's single public interface."""
    if not book.chapters:
        raise ValueError("book has no chapters")
    if config.chapters_per_batch < 1:
        raise ValueError("chapters_per_batch must be at least 1")
    if config.max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")
    if config.synthesis_batch_chars < 1_000:
        raise ValueError("synthesis_batch_chars must be at least 1000")
    if any(not chapter.text.strip() for chapter in book.chapters):
        raise ValueError("every chapter must contain text")
    numbers = [chapter.number for chapter in book.chapters]
    if len(numbers) != len(set(numbers)):
        raise ValueError("chapter numbers must be unique")

    active_checkpoint = (
        checkpoint.model_copy(deep=True) if checkpoint is not None else AnalysisCheckpoint()
    )
    has_checkpoint = bool(
        active_checkpoint.chapters
        or active_checkpoint.chapter_work
        or active_checkpoint.parts
        or active_checkpoint.synthesis
        or active_checkpoint.reconciliation
    )
    if not has_checkpoint:
        _notify(
            on_progress,
            "source_validation",
            3,
            "source and chapter structure validated",
        )

    checkpoint_lock = Lock()

    def persist_checkpoint_locked(**updates: Any) -> None:
        nonlocal active_checkpoint
        active_checkpoint = active_checkpoint.model_copy(update=updates, deep=True)
        if on_checkpoint:
            on_checkpoint(active_checkpoint.model_copy(deep=True))

    def save_checkpoint(**updates: Any) -> None:
        with checkpoint_lock:
            persist_checkpoint_locked(**updates)

    def save_chapter_work(
        chapter_number: int,
        work: ChapterWorkCheckpoint,
        detail: str,
    ) -> None:
        with checkpoint_lock:
            chapter_work = dict(active_checkpoint.chapter_work)
            chapter_work[str(chapter_number)] = work
            persist_checkpoint_locked(chapter_work=chapter_work)
            completed_chapters = len(active_checkpoint.chapters)
        progress = 5 + round(completed / total_chapters * 45)
        _notify(
            on_progress,
            "chapter_synthesis",
            progress,
            (
                f"{completed_chapters}/{total_chapters} chapters complete; "
                f"chapter {chapter_number}: {detail}"
            ),
        )

    def complete_chapter_checkpoint(
        chapter_number: int,
        chapters: list[ChapterAnalysis],
    ) -> None:
        with checkpoint_lock:
            chapter_work = dict(active_checkpoint.chapter_work)
            chapter_work.pop(str(chapter_number), None)
            persist_checkpoint_locked(
                chapters=chapters,
                chapter_work=chapter_work,
            )

    checkpoint_chapters = {
        chapter.chapter_number: chapter
        for chapter in active_checkpoint.chapters
        if chapter.chapter_number in numbers
    }
    chapter_results: list[ChapterAnalysis | None] = [
        checkpoint_chapters.get(chapter.number) for chapter in book.chapters
    ]
    total_chapters = len(book.chapters)
    completed = sum(item is not None for item in chapter_results)
    if completed < total_chapters:
        _notify(
            on_progress,
            "segment_analysis",
            5 + round(completed / total_chapters * 45),
            f"resuming with {completed}/{total_chapters} chapters checkpointed",
        )
    if config.max_concurrency == 1:
        for chapter_index, chapter in enumerate(book.chapters):
            if chapter_results[chapter_index] is not None:
                continue
            chapter_results[chapter_index] = _analyze_source_chapter(
                book,
                chapter,
                adapter,
                config,
                work_checkpoint=active_checkpoint.chapter_work.get(
                    str(chapter.number)
                ),
                on_work_checkpoint=lambda work, detail, chapter_number=chapter.number: (
                    save_chapter_work(chapter_number, work, detail)
                ),
            )
            completed += 1
            complete_chapter_checkpoint(
                chapter.number,
                [item for item in chapter_results if item is not None],
            )
            progress = 5 + round(completed / total_chapters * 45)
            _notify(
                on_progress,
                "chapter_synthesis",
                progress,
                f"chapter {chapter.number} analyzed",
            )
    else:
        with ThreadPoolExecutor(
            max_workers=min(config.max_concurrency, total_chapters),
            thread_name_prefix="analysis-chapter",
        ) as executor:
            future_indexes = {
                executor.submit(
                    _analyze_source_chapter,
                    book,
                    chapter,
                    adapter,
                    config,
                    work_checkpoint=active_checkpoint.chapter_work.get(
                        str(chapter.number)
                    ),
                    on_work_checkpoint=lambda work, detail, chapter_number=chapter.number: (
                        save_chapter_work(chapter_number, work, detail)
                    ),
                ): index
                for index, chapter in enumerate(book.chapters)
                if chapter_results[index] is None
            }
            chapter_failures: list[Exception] = []
            for future in as_completed(future_indexes):
                chapter_index = future_indexes[future]
                try:
                    chapter_results[chapter_index] = future.result()
                except Exception as exc:
                    chapter_failures.append(exc)
                    continue
                completed += 1
                complete_chapter_checkpoint(
                    book.chapters[chapter_index].number,
                    [item for item in chapter_results if item is not None],
                )
                progress = 5 + round(completed / total_chapters * 45)
                _notify(
                    on_progress,
                    "chapter_synthesis",
                    progress,
                    f"chapter {book.chapters[chapter_index].number} analyzed",
                )
            if chapter_failures:
                raise chapter_failures[0]

    ordered_chapters = [item for item in chapter_results if item is not None]
    if len(ordered_chapters) != total_chapters:
        raise RuntimeError("one or more chapters did not produce an analysis")

    parts = active_checkpoint.parts
    if not parts:
        _notify(on_progress, "book_synthesis", 55, "synthesizing chapter groups")
        source_chapters = {chapter.number: chapter for chapter in book.chapters}
        parts = _synthesize_parts(
            adapter,
            config,
            ordered_chapters,
            source_chapters,
            on_batch_completed=lambda completed, total: _notify(
                on_progress,
                "book_synthesis",
                55 + round(completed / total * 9),
                f"{completed}/{total} chapter groups synthesized",
            ),
        )
        save_checkpoint(parts=parts)

    source_chapters = {chapter.number: chapter for chapter in book.chapters}
    verified_chapters = _walk_and_verify(ordered_chapters, source_chapters)
    verified_parts = _walk_and_verify(parts, source_chapters)
    citation_catalog = _verified_citation_catalog(
        [verified_chapters, verified_parts]
    )

    synthesis = active_checkpoint.synthesis
    if synthesis is None:
        _notify(
            on_progress,
            "book_synthesis",
            65,
            f"{len(parts)} parts verified; merging whole-book claims",
        )
        claims = active_checkpoint.book_claims
        if claims is None:
            candidates = _claim_candidates(verified_parts, citation_catalog)
            claim_batches = dict(active_checkpoint.claim_merge_batches)
            claim_splits = set(active_checkpoint.claim_merge_splits)

            def save_claim_batch(key: str, result: ClaimMergeResult) -> None:
                claim_batches[key] = result
                save_checkpoint(claim_merge_batches=dict(claim_batches))
                completed = len(claim_batches)
                batch_label = "batch" if completed == 1 else "batches"
                _notify(
                    on_progress,
                    "book_synthesis",
                    min(69, 65 + completed),
                    f"{completed} claim {batch_label} merged",
                )

            def save_claim_split(key: str) -> None:
                claim_splits.add(key)
                save_checkpoint(claim_merge_splits=set(claim_splits))

            claims, claim_contradictions, claim_uncertainties = (
                _merge_claims_adaptively(
                    adapter,
                    model=config.reading_model,
                    candidates=candidates,
                    catalog=citation_catalog,
                    cached_batches=claim_batches,
                    on_batch=save_claim_batch,
                    max_batch_chars=config.synthesis_batch_chars,
                    max_concurrency=config.max_concurrency,
                    split_keys=claim_splits,
                    on_split_decided=save_claim_split,
                )
            )
            save_checkpoint(
                book_claims=claims,
                claim_contradictions=claim_contradictions,
                claim_uncertainties=claim_uncertainties,
            )
        else:
            claim_contradictions = active_checkpoint.claim_contradictions
            claim_uncertainties = active_checkpoint.claim_uncertainties

        timeline = _merge_verified_timeline(verified_parts)
        editorial = active_checkpoint.editorial
        if editorial is None:
            _notify(
                on_progress,
                "book_synthesis",
                70,
                "generating evidence-bounded reader report",
            )
            editorial_sections: dict[str, BaseModel] = {
                key: value
                for key, value in {
                    "structure": active_checkpoint.editorial_structure,
                    "interpretation": active_checkpoint.editorial_interpretation,
                    "mysteries": active_checkpoint.editorial_mysteries,
                }.items()
                if value is not None
            }

            def save_editorial_section(key: str, result: BaseModel) -> None:
                editorial_sections[key] = result
                save_checkpoint(**{f"editorial_{key}": result})
                _notify(
                    on_progress,
                    "book_synthesis",
                    min(77, 71 + len(editorial_sections) * 2),
                    f"{len(editorial_sections)}/3 reader report sections generated",
                )

            def mark_editorial_split() -> None:
                save_checkpoint(editorial_split=True)
                _notify(
                    on_progress,
                    "book_synthesis",
                    71,
                    "large reader report split into 3 sections",
                )

            editorial = _generate_editorial_adaptively(
                adapter,
                model=config.reading_model,
                prompt=_editorial_prompt(
                    book,
                    verified_parts,
                    timeline,
                    claims,
                ),
                split_mode=active_checkpoint.editorial_split,
                cached_sections=editorial_sections,
                on_split=mark_editorial_split,
                on_section=save_editorial_section,
            )
            save_checkpoint(editorial=editorial)

        editorial_payload = editorial.model_dump(
            mode="python",
            exclude={"contradictions", "uncertainties"},
        )
        synthesis = BookSynthesis(
            **editorial_payload,
            timeline=timeline,
            claims=claims,
            contradictions=list(
                dict.fromkeys(
                    [*editorial.contradictions, *claim_contradictions]
                )
            ),
            uncertainties=list(
                dict.fromkeys(
                    [*editorial.uncertainties, *claim_uncertainties]
                )
            ),
        )
        save_checkpoint(synthesis=synthesis)

    verified_synthesis = _walk_and_verify(synthesis, source_chapters)
    citation_catalog.update(_verified_citation_catalog(verified_synthesis))
    evidence_index = _deduplicate_evidence(verified_chapters)
    all_pre_reconciliation = _all_citations(verified_chapters) + _all_citations(
        verified_synthesis
    )
    verified_count = sum(item.verified for item in all_pre_reconciliation)
    if active_checkpoint.reconciliation is None:
        _notify(
            on_progress,
            "evidence_verification",
            78,
            f"{verified_count}/{len(all_pre_reconciliation)} citations verified",
        )

    reconciliation = active_checkpoint.reconciliation
    if reconciliation is None:
        _notify(
            on_progress,
            "full_book_reconciliation",
            82,
            "auditing whole-book claims against verified evidence",
        )
        if verified_synthesis.claims:
            audit_batches = dict(active_checkpoint.claim_audit_batches)
            audit_splits = set(active_checkpoint.claim_audit_splits)

            def save_audit_batch(key: str, result: ClaimAuditResult) -> None:
                audit_batches[key] = result
                save_checkpoint(claim_audit_batches=dict(audit_batches))
                completed = len(audit_batches)
                batch_label = "batch" if completed == 1 else "batches"
                _notify(
                    on_progress,
                    "full_book_reconciliation",
                    min(91, 82 + completed),
                    f"{completed} claim audit {batch_label} completed",
                )

            def save_audit_split(key: str) -> None:
                audit_splits.add(key)
                save_checkpoint(claim_audit_splits=set(audit_splits))

            reconciliation = _audit_claims_adaptively(
                adapter,
                model=config.reconciliation_model,
                claims=verified_synthesis.claims,
                catalog=citation_catalog,
                cached_batches=audit_batches,
                on_batch=save_audit_batch,
                max_batch_chars=config.synthesis_batch_chars,
                max_concurrency=config.max_concurrency,
                split_keys=audit_splits,
                on_split_decided=save_audit_split,
            )
        else:
            reconciliation = ReconciliationResult()
        save_checkpoint(reconciliation=reconciliation)
    verified_reconciliation = _walk_and_verify(reconciliation, source_chapters)
    all_citations = all_pre_reconciliation + _all_citations(verified_reconciliation)
    verified_count = sum(item.verified for item in all_citations)
    unverified = len(all_citations) - verified_count
    warnings = []
    if unverified:
        warnings.append(
            f"{unverified} citation(s) could not be located verbatim in the source"
        )
    if reconciliation.unsupported_claims:
        warnings.append(
            f"{len(reconciliation.unsupported_claims)} unsupported claim(s) require review"
        )
    audit = EvidenceAudit(
        total_citations=len(all_citations),
        verified_citations=verified_count,
        unverified_citations=unverified,
        coverage=verified_count / len(all_citations) if all_citations else 0,
        warnings=warnings,
    )
    _notify(on_progress, "full_book_reconciliation", 92, "whole-book claims reconciled")

    return BookAnalysis(
        work_id=book.work_id,
        edition_id=book.edition_id,
        title=book.title,
        author=book.author,
        chapters=verified_chapters,
        synthesis=verified_synthesis,
        reconciliation=verified_reconciliation,
        evidence_index=evidence_index,
        audit=audit,
    )
