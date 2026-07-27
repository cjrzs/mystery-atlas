from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .contracts import (
    AnalysisProgress,
    BookAnalysis,
    BookInput,
    BookSynthesis,
    ChapterAnalysis,
    EvidenceAudit,
    EvidenceFinding,
    ModelAdapter,
    PartSynthesis,
    ProgressCallback,
    ReconciliationResult,
    SourceChapter,
    SourceCitation,
)


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


def _evidence_id(item: EvidenceFinding) -> str:
    raw = (
        f"{item.citation.chapter}|{item.citation.start_char}|"
        f"{item.title}|{item.citation.excerpt}"
    )
    return f"ev-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


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
        "Analyze only the supplied book segment. Preserve the source language. "
        "Separate explicit author statements from your inferences. Every factual "
        "finding must carry a short verbatim excerpt copied from this segment. "
        "Do not infer facts from later chapters. Citation.chapter must equal the "
        "current chapter number. If the source chapter heading is only an ordinal "
        "(for example, '第三章' or 'Chapter 3'), chapter_title must be a concise, "
        "source-grounded descriptive subtitle. Otherwise preserve the source title."
        f"\n\nBook: {book.title}\nAuthor: {book.author}\n"
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


def _synthesize_chapter(
    adapter: ModelAdapter,
    config: PipelineConfig,
    chapter: SourceChapter,
    segments: list[ChapterAnalysis],
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
    prompt = (
        "Merge the segment analyses into one chapter analysis. Deduplicate people, "
        "events, claims, and evidence. Retain exact source excerpts and do not add "
        "facts absent from the segment analyses.\n\n"
        f"Chapter {chapter.number}: {chapter.title}\n"
        f"{json.dumps([item.model_dump(mode='json') for item in segments], ensure_ascii=False)}"
    )
    merged = adapter.generate(
        task="chapter_synthesis",
        system="You are a meticulous whole-book analysis editor.",
        prompt=prompt,
        response_model=ChapterAnalysis,
        model=config.reading_model,
    )
    return merged.model_copy(
        update={
            "chapter_number": chapter.number,
            "chapter_title": _resolved_chapter_title(
                chapter.title,
                merged.chapter_title,
                merged.summary,
            ),
        }
    )


def _synthesize_parts(
    adapter: ModelAdapter,
    config: PipelineConfig,
    chapters: list[ChapterAnalysis],
) -> list[PartSynthesis]:
    batches = [
        chapters[start : start + config.chapters_per_batch]
        for start in range(0, len(chapters), config.chapters_per_batch)
    ]

    def synthesize_batch(batch: list[ChapterAnalysis]) -> PartSynthesis:
        prompt = (
            "Synthesize this consecutive group of chapter analyses. Preserve "
            "citations inside timeline events and claims. Identify cross-chapter "
            "development, contradictions, foreshadowing, and unresolved questions. "
            "Do not resolve anything using chapters outside this group.\n\n"
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

    if config.max_concurrency == 1 or len(batches) == 1:
        return [synthesize_batch(batch) for batch in batches]
    with ThreadPoolExecutor(
        max_workers=min(config.max_concurrency, len(batches)),
        thread_name_prefix="analysis-part",
    ) as executor:
        return list(executor.map(synthesize_batch, batches))


def _analyze_source_chapter(
    book: BookInput,
    chapter: SourceChapter,
    adapter: ModelAdapter,
    config: PipelineConfig,
) -> ChapterAnalysis:
    segments: list[ChapterAnalysis] = []
    for segment_number, (segment_start, segment_text) in enumerate(
        _split_text(
            chapter.text,
            config.max_chunk_chars,
            config.chunk_overlap_chars,
        ),
        start=1,
    ):
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
        segments.append(
            result.model_copy(
                update={
                    "chapter_number": chapter.number,
                }
            )
        )
    return _synthesize_chapter(adapter, config, chapter, segments)


def _book_synthesis_prompt(book: BookInput, parts: list[PartSynthesis]) -> str:
    return (
        "Produce the whole-book synthesis from the ordered part syntheses. Explain "
        "the book's structure, central ideas, themes, character arcs, timeline, "
        "mysteries, contradictions, foreshadowing, and practical implications. "
        "Keep author-explicit claims separate from analysis inferences. Do not invent "
        "citations or facts.\n\n"
        f"Book: {book.title}\nAuthor: {book.author}\n"
        f"{json.dumps([item.model_dump(mode='json') for item in parts], ensure_ascii=False)}"
    )


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
        f"<synthesis>{json.dumps(synthesis.model_dump(mode='json'), ensure_ascii=False)}</synthesis>\n"
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
) -> BookAnalysis:
    """Analyze a complete book through the module's single public interface."""
    if not book.chapters:
        raise ValueError("book has no chapters")
    if config.chapters_per_batch < 1:
        raise ValueError("chapters_per_batch must be at least 1")
    if config.max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")
    if any(not chapter.text.strip() for chapter in book.chapters):
        raise ValueError("every chapter must contain text")
    numbers = [chapter.number for chapter in book.chapters]
    if len(numbers) != len(set(numbers)):
        raise ValueError("chapter numbers must be unique")
    _notify(on_progress, "source_validation", 3, "source and chapter structure validated")

    chapter_results: list[ChapterAnalysis | None] = [None] * len(book.chapters)
    total_chapters = len(book.chapters)
    if config.max_concurrency == 1:
        for chapter_index, chapter in enumerate(book.chapters):
            chapter_results[chapter_index] = _analyze_source_chapter(
                book,
                chapter,
                adapter,
                config,
            )
            progress = 5 + round((chapter_index + 1) / total_chapters * 45)
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
                ): index
                for index, chapter in enumerate(book.chapters)
            }
            completed = 0
            for future in as_completed(future_indexes):
                chapter_index = future_indexes[future]
                chapter_results[chapter_index] = future.result()
                completed += 1
                progress = 5 + round(completed / total_chapters * 45)
                _notify(
                    on_progress,
                    "chapter_synthesis",
                    progress,
                    f"chapter {book.chapters[chapter_index].number} analyzed",
                )

    ordered_chapters = [item for item in chapter_results if item is not None]
    if len(ordered_chapters) != total_chapters:
        raise RuntimeError("one or more chapters did not produce an analysis")

    parts = _synthesize_parts(adapter, config, ordered_chapters)
    _notify(on_progress, "book_synthesis", 65, f"{len(parts)} hierarchical parts synthesized")
    synthesis = adapter.generate(
        task="book_synthesis",
        system="You synthesize complete books without losing evidence provenance.",
        prompt=_book_synthesis_prompt(book, parts),
        response_model=BookSynthesis,
        model=config.reading_model,
    )

    source_chapters = {chapter.number: chapter for chapter in book.chapters}
    verified_chapters = _walk_and_verify(ordered_chapters, source_chapters)
    verified_synthesis = _walk_and_verify(synthesis, source_chapters)
    evidence_index = _deduplicate_evidence(verified_chapters)
    all_pre_reconciliation = _all_citations(verified_chapters) + _all_citations(
        verified_synthesis
    )
    verified_count = sum(item.verified for item in all_pre_reconciliation)
    _notify(
        on_progress,
        "evidence_verification",
        78,
        f"{verified_count}/{len(all_pre_reconciliation)} citations verified",
    )

    reconciliation = adapter.generate(
        task="book_reconciliation",
        system="You are the final evidence auditor for a whole-book analysis.",
        prompt=_reconciliation_prompt(
            verified_synthesis,
            _reconciliation_evidence(verified_synthesis, evidence_index),
        ),
        response_model=ReconciliationResult,
        model=config.reconciliation_model,
        temperature=0,
    )
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
