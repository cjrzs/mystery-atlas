import re
import threading
import time

import pytest

from mystery_atlas_analyzer import contracts, pipeline
from mystery_atlas_analyzer.contracts import (
    AnalysisCheckpoint,
    BookInput,
    BookSynthesis,
    ChapterAnalysis,
    ClaimFinding,
    EvidenceFinding,
    PartSynthesis,
    SourceChapter,
    SourceCitation,
    StructureSection,
    TimelineEvent,
)
from mystery_atlas_analyzer.model_adapters import (
    ModelContentIdleError,
    ModelOutputTruncatedError,
    ModelResponseError,
    StaticModelAdapter,
)
from mystery_atlas_analyzer.pipeline import (
    PipelineConfig,
    _reconciliation_evidence,
    _resolved_chapter_title,
    analyze_book,
)


def citation(chapter: int, excerpt: str) -> SourceCitation:
    return SourceCitation(chapter=chapter, excerpt=excerpt)


def chapter_analysis(
    chapter: int,
    title: str,
    excerpt: str,
) -> ChapterAnalysis:
    return ChapterAnalysis(
        chapter_number=chapter,
        chapter_title=title,
        summary=f"{title} summary",
        key_points=[f"{title} key point"],
        evidence=[
            EvidenceFinding(
                title=f"{title} evidence",
                summary=f"Evidence from {title}",
                citation=citation(chapter, excerpt),
            )
        ],
        claims=[
            ClaimFinding(
                statement=f"{title} explicit claim",
                kind="author_explicit",
                status="confirmed",
                confidence=0.9,
                introduced_chapter=chapter,
                citations=[citation(chapter, excerpt)],
            )
        ],
    )


def test_internal_synthesis_contracts_do_not_change_the_external_book_schema() -> None:
    assert hasattr(contracts, "ClaimMergeResult")
    assert hasattr(contracts, "BookEditorial")
    assert hasattr(contracts, "ClaimAuditResult")

    merge = contracts.ClaimMergeResult(
        claims=[
            {
                "statement": "The letter identifies the station.",
                "kind": "author_explicit",
                "status": "confirmed",
                "confidence": 0.9,
                "introduced_chapter": 3,
                "source_claim_ids": ["claim-part-3-1"],
            }
        ]
    )
    editorial = contracts.BookEditorial(overview="A letter redirects the case.")
    audit = contracts.ClaimAuditResult(
        decisions=[
            {
                "claim_id": "claim-book-1",
                "verdict": "supported",
            }
        ]
    )

    assert merge.claims[0].source_claim_ids == ["claim-part-3-1"]
    assert editorial.overview == "A letter redirects the case."
    assert audit.decisions[0].verdict == "supported"
    assert set(BookSynthesis.model_fields) == {
        "overview",
        "structure",
        "core_ideas",
        "themes",
        "character_arcs",
        "timeline",
        "mysteries",
        "contradictions",
        "foreshadowing",
        "claims",
        "uncertainties",
        "action_insights",
    }


def test_pipeline_config_bounds_synthesis_input_batches_not_model_output() -> None:
    config = PipelineConfig(reading_model="reading")

    assert hasattr(config, "synthesis_batch_chars")
    assert config.synthesis_batch_chars == 40_000
    assert not hasattr(config, "max_output_tokens")


def test_analysis_checkpoint_accepts_old_payloads_and_saves_book_substeps() -> None:
    old = AnalysisCheckpoint.model_validate(
        {
            "chapters": [],
            "parts": [],
            "synthesis": None,
            "reconciliation": None,
        }
    )

    assert hasattr(old, "claim_merge_batches")
    assert hasattr(old, "book_claims")
    assert hasattr(old, "editorial")
    assert hasattr(old, "editorial_split")
    assert hasattr(old, "editorial_structure")
    assert hasattr(old, "claim_audit_batches")
    assert old.claim_merge_batches == {}
    assert old.book_claims is None
    assert old.editorial is None
    assert old.editorial_split is False
    assert old.editorial_structure is None
    assert old.claim_audit_batches == {}

    saved = old.model_copy(
        update={
            "book_claims": [
                ClaimFinding(
                    statement="A verified claim.",
                    kind="author_explicit",
                    introduced_chapter=1,
                    citations=[
                        SourceCitation(
                            chapter=1,
                            excerpt="A verified claim.",
                            verified=True,
                        )
                    ],
                )
            ],
            "editorial": contracts.BookEditorial(overview="A complete overview."),
        }
    )
    restored = AnalysisCheckpoint.model_validate(saved.model_dump(mode="json"))

    assert restored.book_claims is not None
    assert restored.book_claims[0].statement == "A verified claim."
    assert restored.editorial is not None
    assert restored.editorial.overview == "A complete overview."


def test_whole_book_timeline_is_a_deduplicated_merge_of_verified_part_events() -> None:
    verified = SourceCitation(
        chapter=1,
        excerpt="The clock stopped at midnight.",
        start_char=4,
        end_char=34,
        verified=True,
    )
    unverified = SourceCitation(
        chapter=2,
        excerpt="This sentence is not in the source.",
        verified=False,
    )
    parts = [
        PartSynthesis(
            chapter_numbers=[1],
            summary="The clock establishes the chronology.",
            timeline=[
                TimelineEvent(
                    chapter=1,
                    sequence=1,
                    summary="The clock stops at midnight.",
                    citations=[verified],
                )
            ],
        ),
        PartSynthesis(
            chapter_numbers=[1, 2],
            summary="The chronology is tested.",
            timeline=[
                TimelineEvent(
                    chapter=1,
                    sequence=2,
                    summary="  The clock stops at midnight. ",
                    citations=[verified],
                ),
                TimelineEvent(
                    chapter=2,
                    sequence=1,
                    summary="An unsupported event.",
                    citations=[unverified],
                ),
            ],
        ),
    ]

    assert hasattr(pipeline, "_merge_verified_timeline")
    timeline = pipeline._merge_verified_timeline(parts)

    assert len(timeline) == 1
    assert timeline[0].chapter == 1
    assert timeline[0].sequence == 1
    assert timeline[0].citations == [verified]


def test_verified_citation_catalog_uses_stable_ids_and_excludes_unverified_items() -> None:
    verified = SourceCitation(
        chapter=3,
        excerpt="The torn letter names the station.",
        start_char=12,
        end_char=48,
        verified=True,
    )
    duplicate = verified.model_copy(
        update={"locator": {"format": "epub", "resource": "chapter-3.xhtml"}}
    )
    unverified = SourceCitation(
        chapter=4,
        excerpt="An invented quotation.",
        verified=False,
    )
    parts = [
        PartSynthesis(
            chapter_numbers=[3, 4],
            summary="A letter changes the investigation.",
            claims=[
                ClaimFinding(
                    statement="The letter names the station.",
                    kind="author_explicit",
                    introduced_chapter=3,
                    citations=[verified, duplicate, unverified],
                )
            ],
        )
    ]

    assert hasattr(pipeline, "_verified_citation_catalog")
    catalog = pipeline._verified_citation_catalog(parts)

    assert list(catalog) == [next(iter(catalog))]
    evidence_id = next(iter(catalog))
    assert evidence_id.startswith("ev-")
    assert catalog[evidence_id].excerpt == verified.excerpt
    assert catalog[evidence_id].verified is True


def test_claim_candidates_reference_evidence_ids_without_copying_citations() -> None:
    verified = SourceCitation(
        chapter=3,
        excerpt="The torn letter names the station.",
        start_char=12,
        end_char=48,
        verified=True,
    )
    unverified = SourceCitation(
        chapter=4,
        excerpt="An invented quotation.",
        verified=False,
    )
    parts = [
        PartSynthesis(
            chapter_numbers=[3, 4],
            summary="A letter changes the investigation.",
            claims=[
                ClaimFinding(
                    statement="The letter names the station.",
                    kind="author_explicit",
                    introduced_chapter=3,
                    citations=[verified],
                ),
                ClaimFinding(
                    statement="An unsupported interpretation.",
                    kind="analysis_inference",
                    introduced_chapter=4,
                    citations=[unverified],
                ),
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)

    assert hasattr(pipeline, "_claim_candidates")
    candidates = pipeline._claim_candidates(parts, catalog)

    assert len(candidates) == 1
    assert candidates[0]["claim_id"].startswith("cl-")
    assert candidates[0]["statement"] == "The letter names the station."
    assert candidates[0]["evidence_ids"] == list(catalog)
    assert "citations" not in candidates[0]
    assert verified.excerpt not in str(candidates[0])


def test_claim_merge_hydrates_verified_citations_and_preserves_unmentioned_claims() -> None:
    first_citation = SourceCitation(
        chapter=1,
        excerpt="The key was under the clock.",
        start_char=4,
        end_char=32,
        verified=True,
    )
    second_citation = SourceCitation(
        chapter=7,
        excerpt="Mira admits moving the clock hand.",
        start_char=10,
        end_char=44,
        verified=True,
    )
    parts = [
        PartSynthesis(
            chapter_numbers=[1, 7],
            summary="The clock clue is resolved.",
            claims=[
                ClaimFinding(
                    statement="The key implicates the clock.",
                    kind="analysis_inference",
                    introduced_chapter=1,
                    citations=[first_citation],
                ),
                ClaimFinding(
                    statement="Mira moved the clock hand.",
                    kind="author_explicit",
                    introduced_chapter=7,
                    citations=[second_citation],
                ),
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)
    candidates = pipeline._claim_candidates(parts, catalog)
    merge = contracts.ClaimMergeResult(
        claims=[
            contracts.ClaimMergeDecision(
                statement="The clock evidence implicates Mira.",
                kind="analysis_inference",
                status="inferred",
                confidence=0.8,
                introduced_chapter=1,
                resolved_chapter=7,
                source_claim_ids=[candidates[0]["claim_id"]],
            )
        ]
    )

    assert hasattr(pipeline, "_apply_claim_merge")
    claims = pipeline._apply_claim_merge(merge, candidates, catalog)

    assert [item.statement for item in claims] == [
        "The clock evidence implicates Mira.",
        "Mira moved the clock hand.",
    ]
    assert claims[0].citations == [first_citation]
    assert claims[1].citations == [second_citation]


@pytest.mark.parametrize(
    "failure_type",
    [ModelOutputTruncatedError, ModelContentIdleError],
)
def test_claim_merge_splits_a_truncated_batch_without_repeating_it(
    failure_type,
    caplog,
) -> None:
    citations = [
        SourceCitation(
            chapter=chapter,
            excerpt=f"Verified excerpt {chapter}.",
            start_char=chapter * 10,
            end_char=chapter * 10 + 20,
            verified=True,
        )
        for chapter in (1, 2)
    ]
    parts = [
        PartSynthesis(
            chapter_numbers=[1, 2],
            summary="Two independent findings.",
            claims=[
                ClaimFinding(
                    statement=f"Finding {chapter}.",
                    kind="author_explicit",
                    introduced_chapter=chapter,
                    citations=[source],
                )
                for chapter, source in zip((1, 2), citations, strict=True)
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)
    candidates = pipeline._claim_candidates(parts, catalog)

    class SplitOnLength:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            assert task == "book_claim_merge"
            claim_ids = re.findall(r'"claim_id":\s*"([^"]+)"', prompt)
            self.batch_sizes.append(len(claim_ids))
            if len(claim_ids) > 1:
                if failure_type is ModelContentIdleError:
                    raise ModelContentIdleError(
                        "effective content idle",
                        response_chars=0,
                    )
                raise ModelOutputTruncatedError("provider length")
            candidate = next(
                item for item in candidates if item["claim_id"] == claim_ids[0]
            )
            return contracts.ClaimMergeResult(
                claims=[
                    contracts.ClaimMergeDecision(
                        statement=candidate["statement"],
                        kind=candidate["kind"],
                        status=candidate["status"],
                        confidence=candidate["confidence"],
                        introduced_chapter=candidate["introduced_chapter"],
                        source_claim_ids=claim_ids,
                    )
                ]
            )

    adapter = SplitOnLength()
    saved_batches: dict[str, contracts.ClaimMergeResult] = {}

    assert hasattr(pipeline, "_merge_claims_adaptively")
    with caplog.at_level(
        "INFO",
        logger="mystery_atlas_analyzer.pipeline",
    ):
        claims, _, _ = pipeline._merge_claims_adaptively(
            adapter,
            model="reading",
            candidates=candidates,
            catalog=catalog,
            cached_batches={},
            on_batch=lambda key, result: saved_batches.__setitem__(key, result),
        )

    assert adapter.batch_sizes == [2, 1, 1]
    assert [item.statement for item in claims] == ["Finding 1.", "Finding 2."]
    assert len(saved_batches) == 2
    expected_reason = (
        "content_idle"
        if failure_type is ModelContentIdleError
        else "provider_length"
    )
    assert f"reason={expected_reason}" in caplog.text
    assert "items=2" in caplog.text
    assert "layer=0" in caplog.text


def test_minimum_claim_batch_retries_content_idle_once() -> None:
    source = SourceCitation(
        chapter=1,
        excerpt="The key was under the clock.",
        start_char=4,
        end_char=32,
        verified=True,
    )
    parts = [
        PartSynthesis(
            chapter_numbers=[1],
            summary="One finding.",
            claims=[
                ClaimFinding(
                    statement="The key was under the clock.",
                    kind="author_explicit",
                    introduced_chapter=1,
                    citations=[source],
                )
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)
    candidates = pipeline._claim_candidates(parts, catalog)

    class IdleOnce:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, *, task, system, prompt, response_model, model, temperature=0.1):
            del system, prompt, response_model, model, temperature
            assert task == "book_claim_merge"
            self.calls += 1
            if self.calls == 1:
                raise ModelContentIdleError("idle", response_chars=0)
            return contracts.ClaimMergeResult()

    adapter = IdleOnce()
    claims, _, _ = pipeline._merge_claims_adaptively(
        adapter,
        model="reading",
        candidates=candidates,
        catalog=catalog,
        cached_batches={},
    )

    assert adapter.calls == 2
    assert len(claims) == 1


def test_claim_merge_preemptively_splits_by_request_character_budget() -> None:
    sources = [
        SourceCitation(
            chapter=chapter,
            excerpt=f"Evidence {chapter}.",
            start_char=chapter * 10,
            end_char=chapter * 10 + 11,
            verified=True,
        )
        for chapter in (1, 2)
    ]
    parts = [
        PartSynthesis(
            chapter_numbers=[1, 2],
            summary="Two findings.",
            claims=[
                ClaimFinding(
                    statement=("A" if chapter == 1 else "B") * 300,
                    kind="analysis_inference",
                    introduced_chapter=chapter,
                    citations=[source],
                )
                for chapter, source in zip((1, 2), sources, strict=True)
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)
    candidates = pipeline._claim_candidates(parts, catalog)

    class RecordsBatches:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def generate(self, *, task, system, prompt, response_model, model, temperature=0.1):
            del system, response_model, model, temperature
            assert task == "book_claim_merge"
            claim_ids = re.findall(r'"claim_id":\s*"([^"]+)"', prompt)
            self.batch_sizes.append(len(claim_ids))
            candidate = next(
                item for item in candidates if item["claim_id"] == claim_ids[0]
            )
            return contracts.ClaimMergeResult(
                claims=[
                    contracts.ClaimMergeDecision(
                        statement=candidate["statement"],
                        kind=candidate["kind"],
                        introduced_chapter=candidate["introduced_chapter"],
                        source_claim_ids=claim_ids,
                    )
                ]
            )

    adapter = RecordsBatches()
    pipeline._merge_claims_adaptively(
        adapter,
        model="reading",
        candidates=candidates,
        catalog=catalog,
        cached_batches={},
        max_batch_chars=500,
    )

    assert adapter.batch_sizes == [1, 1]


def test_pre_split_claim_batches_respect_single_book_concurrency() -> None:
    sources = [
        SourceCitation(
            chapter=chapter,
            excerpt=f"Concurrent evidence {chapter}.",
            start_char=chapter * 10,
            end_char=chapter * 10 + 21,
            verified=True,
        )
        for chapter in range(1, 5)
    ]
    parts = [
        PartSynthesis(
            chapter_numbers=list(range(1, 5)),
            summary="Four independent claims.",
            claims=[
                ClaimFinding(
                    statement=f"Claim {chapter}: " + ("x" * 300),
                    kind="analysis_inference",
                    introduced_chapter=chapter,
                    citations=[source],
                )
                for chapter, source in zip(range(1, 5), sources, strict=True)
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)
    candidates = pipeline._claim_candidates(parts, catalog)

    class ConcurrentMergeAdapter:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.active = 0
            self.max_active = 0

        def generate(self, *, task, system, prompt, response_model, model, temperature=0.1):
            del system, response_model, model, temperature
            assert task == "book_claim_merge"
            claim_id = re.search(r'"claim_id":\s*"([^"]+)"', prompt)
            assert claim_id is not None
            candidate = next(
                item for item in candidates if item["claim_id"] == claim_id.group(1)
            )
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return contracts.ClaimMergeResult(
                claims=[
                    contracts.ClaimMergeDecision(
                        statement=candidate["statement"],
                        kind=candidate["kind"],
                        introduced_chapter=candidate["introduced_chapter"],
                        source_claim_ids=[candidate["claim_id"]],
                    )
                ]
            )

    adapter = ConcurrentMergeAdapter()
    claims, _, _ = pipeline._merge_claims_adaptively(
        adapter,
        model="reading",
        candidates=candidates,
        catalog=catalog,
        cached_batches={},
        max_batch_chars=500,
        max_concurrency=2,
    )

    assert adapter.max_active == 2
    assert len(claims) == 4


def test_claim_batches_are_hierarchically_merged_when_each_level_shrinks() -> None:
    sources = [
        SourceCitation(
            chapter=chapter,
            excerpt=f"Hierarchy evidence {chapter}.",
            start_char=chapter * 10,
            end_char=chapter * 10 + 20,
            verified=True,
        )
        for chapter in range(1, 5)
    ]
    parts = [
        PartSynthesis(
            chapter_numbers=list(range(1, 5)),
            summary="Related findings develop across the book.",
            claims=[
                ClaimFinding(
                    statement=f"Related finding {chapter}: " + ("x" * 120),
                    kind="analysis_inference",
                    introduced_chapter=chapter,
                    citations=[source],
                )
                for chapter, source in zip(range(1, 5), sources, strict=True)
            ],
        )
    ]
    catalog = pipeline._verified_citation_catalog(parts)
    candidates = pipeline._claim_candidates(parts, catalog)

    class HierarchicalAdapter:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def generate(self, *, task, system, prompt, response_model, model, temperature=0.1):
            del system, response_model, model, temperature
            assert task == "book_claim_merge"
            claim_ids = re.findall(r'"claim_id":\s*"([^"]+)"', prompt)
            self.batch_sizes.append(len(claim_ids))
            return contracts.ClaimMergeResult(
                claims=[
                    contracts.ClaimMergeDecision(
                        statement=f"Merged level {len(self.batch_sizes)}.",
                        kind="analysis_inference",
                        introduced_chapter=1,
                        source_claim_ids=claim_ids,
                    )
                ]
            )

    adapter = HierarchicalAdapter()
    claims, _, _ = pipeline._merge_claims_adaptively(
        adapter,
        model="reading",
        candidates=candidates,
        catalog=catalog,
        cached_batches={},
        max_batch_chars=1_500,
        max_concurrency=2,
    )

    assert sorted(adapter.batch_sizes) == [2, 2, 2]
    assert len(claims) == 1
    assert len(claims[0].citations) == 4


def test_checkpointed_parts_use_compact_book_synthesis_and_claim_only_audit() -> None:
    excerpt = "Mira admitted that she moved the clock hand."
    source = SourceCitation(chapter=2, excerpt=excerpt)
    chapter = chapter_analysis(2, "The Confession", excerpt)
    part = PartSynthesis(
        chapter_numbers=[2],
        summary="Mira's confession resolves the clock discrepancy.",
        timeline=[
            TimelineEvent(
                chapter=2,
                sequence=1,
                summary="Mira admits moving the clock hand.",
                citations=[source],
            )
        ],
        claims=[
            ClaimFinding(
                statement="Mira moved the clock hand.",
                kind="author_explicit",
                status="confirmed",
                confidence=0.98,
                introduced_chapter=2,
                citations=[source],
            )
        ],
    )
    book = BookInput(
        work_id="work-compact",
        edition_id="edition-compact",
        title="Clock House",
        author="A. Writer",
        chapters=[
            SourceChapter(
                number=2,
                title="The Confession",
                text=f"At dawn, {excerpt} The case closed.",
            )
        ],
    )

    class CompactSynthesisAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.prompts: dict[str, str] = {}

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            self.calls.append(task)
            self.prompts[task] = prompt
            if task == "book_claim_merge":
                claim_id = re.search(r'"claim_id":\s*"([^"]+)"', prompt)
                assert claim_id is not None
                return contracts.ClaimMergeResult(
                    claims=[
                        contracts.ClaimMergeDecision(
                            statement="Mira moved the clock hand.",
                            kind="author_explicit",
                            status="confirmed",
                            confidence=0.98,
                            introduced_chapter=2,
                            source_claim_ids=[claim_id.group(1)],
                        )
                    ]
                )
            if task == "book_editorial":
                return contracts.BookEditorial(
                    overview="A confession resolves the clock mystery.",
                    themes=["Evidence and testimony"],
                    mysteries=["Who altered the clock?"],
                )
            if task == "book_claim_audit":
                claim_id = re.search(r'"claim_id":\s*"([^"]+)"', prompt)
                assert claim_id is not None
                return contracts.ClaimAuditResult(
                    decisions=[
                        contracts.ClaimAuditDecision(
                            claim_id=claim_id.group(1),
                            verdict="supported",
                        )
                    ],
                    review_notes=["The confession directly supports the claim."],
                )
            raise AssertionError(f"unexpected task: {task}")

    adapter = CompactSynthesisAdapter()
    checkpoints: list[AnalysisCheckpoint] = []
    progress_updates = []
    report = analyze_book(
        book,
        adapter,
        PipelineConfig(reading_model="reading", truth_model="truth"),
        checkpoint=AnalysisCheckpoint(chapters=[chapter], parts=[part]),
        on_checkpoint=checkpoints.append,
        on_progress=progress_updates.append,
    )

    assert adapter.calls == [
        "book_claim_merge",
        "book_editorial",
        "book_claim_audit",
    ]
    assert '"excerpt"' not in adapter.prompts["book_editorial"]
    assert '"overview"' not in adapter.prompts["book_claim_audit"]
    assert '"timeline"' not in adapter.prompts["book_claim_audit"]
    assert report.synthesis.overview == "A confession resolves the clock mystery."
    assert len(report.synthesis.timeline) == 1
    assert report.synthesis.timeline[0].citations[0].verified is True
    assert report.synthesis.claims[0].citations[0].verified is True
    assert report.reconciliation.final_claims == report.synthesis.claims
    assert any(item.book_claims is not None for item in checkpoints)
    assert any(item.editorial is not None for item in checkpoints)
    assert any(
        item.progress == 66 and item.detail == "1 claim batch merged"
        for item in progress_updates
    )
    assert any(
        item.progress == 83 and item.detail == "1 claim audit batch completed"
        for item in progress_updates
    )


def test_editorial_truncation_falls_back_to_checkpointed_field_groups() -> None:
    assert hasattr(contracts, "BookStructureEditorial")
    assert hasattr(contracts, "BookInterpretationEditorial")
    assert hasattr(contracts, "BookMysteryEditorial")
    assert hasattr(pipeline, "_generate_editorial_adaptively")

    class SplitEditorialAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, prompt, response_model, model, temperature
            self.calls.append(task)
            if task == "book_editorial":
                raise ModelOutputTruncatedError("provider length")
            if task == "book_editorial_structure":
                return contracts.BookStructureEditorial(
                    overview="A compact overview.",
                    structure=[],
                )
            if task == "book_editorial_interpretation":
                return contracts.BookInterpretationEditorial(
                    themes=["Memory"],
                    action_insights=["Verify recollections."],
                )
            if task == "book_editorial_mysteries":
                return contracts.BookMysteryEditorial(
                    mysteries=["Who changed the record?"],
                    uncertainties=["The exact time remains unclear."],
                )
            raise AssertionError(f"unexpected task: {task}")

    adapter = SplitEditorialAdapter()
    saved_sections: dict[str, object] = {}
    editorial = pipeline._generate_editorial_adaptively(
        adapter,
        model="reading",
        prompt="Compact authoritative facts.",
        split_mode=False,
        cached_sections={},
        on_split=lambda: saved_sections.__setitem__("split", True),
        on_section=lambda key, result: saved_sections.__setitem__(key, result),
    )

    assert adapter.calls == [
        "book_editorial",
        "book_editorial_structure",
        "book_editorial_interpretation",
        "book_editorial_mysteries",
    ]
    assert editorial.overview == "A compact overview."
    assert editorial.themes == ["Memory"]
    assert editorial.mysteries == ["Who changed the record?"]
    assert saved_sections["split"] is True
    assert set(saved_sections) == {
        "split",
        "structure",
        "interpretation",
        "mysteries",
    }


def test_claim_audit_splits_truncated_batches_and_combines_results() -> None:
    sources = [
        SourceCitation(
            chapter=chapter,
            excerpt=f"Audit evidence {chapter}.",
            start_char=chapter * 10,
            end_char=chapter * 10 + 17,
            verified=True,
        )
        for chapter in (1, 2)
    ]
    claims = [
        ClaimFinding(
            statement=f"Audited claim {chapter}.",
            kind="author_explicit",
            status="confirmed",
            introduced_chapter=chapter,
            citations=[source],
        )
        for chapter, source in zip((1, 2), sources, strict=True)
    ]
    catalog = pipeline._verified_citation_catalog(claims)

    class SplitAuditAdapter:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            assert task == "book_claim_audit"
            claim_ids = re.findall(r'"claim_id":\s*"([^"]+)"', prompt)
            self.batch_sizes.append(len(claim_ids))
            if len(claim_ids) > 1:
                raise ModelOutputTruncatedError("provider length")
            return contracts.ClaimAuditResult(
                decisions=[
                    contracts.ClaimAuditDecision(
                        claim_id=claim_ids[0],
                        verdict="supported",
                    )
                ]
            )

    adapter = SplitAuditAdapter()
    saved: dict[str, contracts.ClaimAuditResult] = {}

    assert hasattr(pipeline, "_audit_claims_adaptively")
    result = pipeline._audit_claims_adaptively(
        adapter,
        model="truth",
        claims=claims,
        catalog=catalog,
        cached_batches={},
        on_batch=lambda key, value: saved.__setitem__(key, value),
    )

    assert adapter.batch_sizes == [2, 1, 1]
    assert result.final_claims == claims
    assert len(saved) == 2


def test_minimum_claim_audit_retries_content_idle_once() -> None:
    source = SourceCitation(
        chapter=1,
        excerpt="The ledger names Mira.",
        start_char=10,
        end_char=32,
        verified=True,
    )
    claim = ClaimFinding(
        statement="The ledger names Mira.",
        kind="author_explicit",
        status="confirmed",
        introduced_chapter=1,
        citations=[source],
    )
    catalog = pipeline._verified_citation_catalog([claim])

    class IdleOnceAuditAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, prompt, response_model, model, temperature
            assert task == "book_claim_audit"
            self.calls += 1
            if self.calls == 1:
                raise ModelContentIdleError("idle", response_chars=0)
            return contracts.ClaimAuditResult(
                decisions=[
                    contracts.ClaimAuditDecision(
                        claim_id=pipeline._book_claim_id(claim),
                        verdict="supported",
                    )
                ]
            )

    adapter = IdleOnceAuditAdapter()
    result = pipeline._audit_claims_adaptively(
        adapter,
        model="truth",
        claims=[claim],
        catalog=catalog,
        cached_batches={},
    )

    assert adapter.calls == 2
    assert result.final_claims == [claim]


def test_pre_split_claim_audits_respect_single_book_concurrency() -> None:
    sources = [
        SourceCitation(
            chapter=chapter,
            excerpt=f"Audit concurrency evidence {chapter}.",
            start_char=chapter * 10,
            end_char=chapter * 10 + 28,
            verified=True,
        )
        for chapter in range(1, 5)
    ]
    claims = [
        ClaimFinding(
            statement=f"Audit claim {chapter}: " + ("x" * 300),
            kind="analysis_inference",
            introduced_chapter=chapter,
            citations=[source],
        )
        for chapter, source in zip(range(1, 5), sources, strict=True)
    ]
    catalog = pipeline._verified_citation_catalog(claims)

    class ConcurrentAuditAdapter:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.active = 0
            self.max_active = 0

        def generate(self, *, task, system, prompt, response_model, model, temperature=0.1):
            del system, response_model, model, temperature
            assert task == "book_claim_audit"
            claim_id = re.search(r'"claim_id":\s*"([^"]+)"', prompt)
            assert claim_id is not None
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return contracts.ClaimAuditResult(
                decisions=[
                    contracts.ClaimAuditDecision(
                        claim_id=claim_id.group(1),
                        verdict="supported",
                    )
                ]
            )

    adapter = ConcurrentAuditAdapter()
    result = pipeline._audit_claims_adaptively(
        adapter,
        model="truth",
        claims=claims,
        catalog=catalog,
        cached_batches={},
        max_batch_chars=500,
        max_concurrency=2,
    )

    assert adapter.max_active == 2
    assert result.final_claims == claims


def test_whole_book_pipeline_verifies_evidence_and_reconciles_claims() -> None:
    first_excerpt = "The brass key was hidden under the clock."
    second_excerpt = "Mira admitted that she moved the clock hand."
    first = chapter_analysis(1, "The Key", first_excerpt)
    second = chapter_analysis(2, "The Confession", second_excerpt)
    final_claim = ClaimFinding(
        statement="Mira moved the clock hand.",
        kind="author_explicit",
        status="confirmed",
        confidence=0.98,
        introduced_chapter=2,
        citations=[citation(2, second_excerpt)],
    )
    adapter = StaticModelAdapter(
        {
            "segment_analysis": [first, second],
            "part_synthesis": PartSynthesis(
                chapter_numbers=[1, 2],
                summary="A hidden key leads to a confession.",
                core_ideas=["Evidence changes the apparent timeline."],
                claims=[final_claim],
            ),
            "book_claim_merge": contracts.ClaimMergeResult(),
            "book_editorial": contracts.BookEditorial(
                overview="The investigation turns on a manipulated clock.",
                structure=[
                    StructureSection(
                        title="Investigation",
                        chapters=[1, 2],
                        purpose="Reveal and verify the decisive clue.",
                        summary="The key and confession resolve the timeline.",
                    )
                ],
                core_ideas=["Evidence must be checked against testimony."],
            ),
            "book_claim_audit": contracts.ClaimAuditResult(
                review_notes=["The final claim has direct textual support."],
            ),
        }
    )
    book = BookInput(
        work_id="work-1",
        edition_id="edition-1",
        title="Clock House",
        author="A. Writer",
        chapters=[
            SourceChapter(
                number=1,
                title="The Key",
                text=f"Before midnight. {first_excerpt} Nothing else moved.",
                source_locator={
                    "format": "pdf",
                    "page_start": 4,
                    "page_breaks": [{"page": 4, "offset": 0}],
                },
            ),
            SourceChapter(
                number=2,
                title="The Confession",
                text=f"At dawn, {second_excerpt} The case closed.",
                source_locator={
                    "format": "pdf",
                    "page_start": 9,
                    "page_breaks": [{"page": 9, "offset": 0}],
                },
            ),
        ],
    )

    report = analyze_book(
        book,
        adapter,
        PipelineConfig(reading_model="reading", truth_model="truth"),
    )

    assert adapter.calls == [
        "segment_analysis",
        "segment_analysis",
        "part_synthesis",
        "book_claim_merge",
        "book_editorial",
        "book_claim_audit",
    ]
    assert report.audit.unverified_citations == 0
    assert report.audit.coverage == 1
    assert report.evidence_index[0].evidence_id.startswith("ev-")
    assert report.evidence_index[0].citation.verified is True
    assert report.evidence_index[0].citation.page == 4
    assert report.reconciliation.final_claims[0].kind == "author_explicit"


def test_pipeline_resumes_from_last_checkpoint_after_book_synthesis_failure() -> None:
    excerpt = "The brass key was hidden under the clock."
    chapter = chapter_analysis(1, "The Key", excerpt)
    claim = chapter.claims[0]
    part = PartSynthesis(
        chapter_numbers=[1],
        summary="A hidden key changes the investigation.",
        claims=[claim],
    )
    book = BookInput(
        work_id="work-resume",
        edition_id="edition-resume",
        title="Checkpoint House",
        author="A. Writer",
        chapters=[
            SourceChapter(
                number=1,
                title="The Key",
                text=f"Before midnight. {excerpt} Nothing else moved.",
            )
        ],
    )
    checkpoints = []
    failing_adapter = StaticModelAdapter(
        {
            "segment_analysis": chapter,
            "part_synthesis": part,
        }
    )

    with pytest.raises(ModelResponseError):
        analyze_book(
            book,
            failing_adapter,
            PipelineConfig(reading_model="reading"),
            on_checkpoint=checkpoints.append,
        )

    assert failing_adapter.calls == [
        "segment_analysis",
        "part_synthesis",
        "book_claim_merge",
    ]
    assert checkpoints[-1].parts == [part]

    resumed_adapter = StaticModelAdapter(
        {
            "book_claim_merge": contracts.ClaimMergeResult(),
            "book_editorial": contracts.BookEditorial(
                overview="The key exposes the false account.",
            ),
            "book_claim_audit": contracts.ClaimAuditResult(),
        }
    )
    resumed_progress = []
    report = analyze_book(
        book,
        resumed_adapter,
        PipelineConfig(reading_model="reading"),
        checkpoint=checkpoints[-1],
        on_progress=resumed_progress.append,
    )

    assert resumed_adapter.calls == [
        "book_claim_merge",
        "book_editorial",
        "book_claim_audit",
    ]
    assert resumed_progress[0].stage == "book_synthesis"
    assert report.synthesis.overview == "The key exposes the false account."


def test_pipeline_checkpoints_successful_concurrent_chapters_before_failing() -> None:
    class PartiallyFailingAdapter:
        def __init__(self) -> None:
            self.started = threading.Barrier(2)

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            assert task == "segment_analysis"
            match = re.search(r"Chapter: (\d+) -", prompt)
            assert match is not None
            chapter_number = int(match.group(1))
            self.started.wait(timeout=2)
            if chapter_number == 1:
                raise ModelResponseError("chapter 1 response was truncated")
            time.sleep(0.01)
            return ChapterAnalysis(
                chapter_number=chapter_number,
                chapter_title=f"Chapter {chapter_number}",
                summary=f"Summary {chapter_number}",
            )

    checkpoints = []
    with pytest.raises(ModelResponseError):
        analyze_book(
            BookInput(
                work_id="work-partial-checkpoint",
                edition_id="edition-partial-checkpoint",
                title="Two Chapter Failure",
                author="A. Writer",
                chapters=[
                    SourceChapter(
                        number=number,
                        title=f"Chapter {number}",
                        text=f"Chapter {number} source text.",
                    )
                    for number in range(1, 3)
                ],
            ),
            PartiallyFailingAdapter(),
            PipelineConfig(reading_model="reading", max_concurrency=2),
            on_checkpoint=checkpoints.append,
        )

    assert [chapter.chapter_number for chapter in checkpoints[-1].chapters] == [2]


def test_pipeline_flags_a_model_excerpt_that_is_not_in_the_book() -> None:
    chapter = chapter_analysis(1, "Opening", "This sentence does not exist.")
    claim = chapter.claims[0]
    adapter = StaticModelAdapter(
        {
            "segment_analysis": chapter,
            "part_synthesis": PartSynthesis(
                chapter_numbers=[1],
                summary="Opening summary",
                claims=[claim],
            ),
            "book_editorial": contracts.BookEditorial(overview="Opening overview"),
        }
    )
    report = analyze_book(
        BookInput(
            work_id="work-2",
            edition_id="edition-2",
            title="Unreliable Notes",
            author="A. Writer",
            chapters=[
                SourceChapter(
                    number=1,
                    title="Opening",
                    text="Only a different sentence appears in the source.",
                )
            ],
        ),
        adapter,
        PipelineConfig(reading_model="reading"),
    )

    assert report.audit.unverified_citations > 0
    assert report.audit.coverage == 0
    assert report.audit.warnings
    assert report.evidence_index[0].citation.verified is False


def test_multisegment_chapter_uses_field_groups_and_hydrates_evidence_ids() -> None:
    class FieldGroupedChapterAdapter:
        def __init__(self) -> None:
            self.tasks: list[str] = []

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, model, temperature
            self.tasks.append(task)
            if task == "segment_analysis":
                source = prompt.split("<source>\n", 1)[1].split("\n</source>", 1)[0]
                excerpt = source[:24]
                source_citation = SourceCitation(chapter=1, excerpt=excerpt)
                return ChapterAnalysis(
                    chapter_number=1,
                    chapter_title="Chapter 1",
                    summary="Alice watches Bob leave.",
                    people=[
                        contracts.PersonFinding(
                            name="Alice",
                            role="witness",
                            first_chapter=1,
                            citations=[source_citation],
                        ),
                        contracts.PersonFinding(
                            name="Bob",
                            role="suspect",
                            first_chapter=1,
                            citations=[source_citation],
                        ),
                    ],
                    relations=[
                        contracts.RelationFinding(
                            source="Alice",
                            target="Bob",
                            label="observes",
                            kind="investigation",
                            first_chapter=1,
                            citations=[source_citation],
                        )
                    ],
                    events=[
                        TimelineEvent(
                            chapter=1,
                            summary="Bob leaves while Alice watches.",
                            citations=[source_citation],
                        )
                    ],
                    evidence=[
                        EvidenceFinding(
                            title="Alice sees Bob",
                            summary="Alice observes Bob leaving.",
                            citation=source_citation,
                        )
                    ],
                    claims=[
                        ClaimFinding(
                            statement="Alice saw Bob leave.",
                            kind="author_explicit",
                            introduced_chapter=1,
                            citations=[source_citation],
                        )
                    ],
                )

            evidence_ids = list(
                dict.fromkeys(re.findall(r'"evidence_id":\s*"([^"]+)"', prompt))
            )
            if task.startswith("chapter_"):
                assert evidence_ids
                evidence_id = evidence_ids[0]
            if task == "chapter_people_relations":
                return response_model.model_validate(
                    {
                        "people": [
                            {
                                "name": "Alice",
                                "aliases": [],
                                "role": "witness",
                                "description": "She sees Bob leave.",
                                "first_chapter": 1,
                                "evidence_ids": [evidence_id],
                            },
                            {
                                "name": "Bob",
                                "aliases": [],
                                "role": "suspect",
                                "description": "He leaves the scene.",
                                "first_chapter": 1,
                                "evidence_ids": [evidence_id],
                            },
                        ],
                        "relations": [
                            {
                                "source": "Alice",
                                "target": "Bob",
                                "label": "observes",
                                "kind": "investigation",
                                "status": "confirmed",
                                "first_chapter": 1,
                                "evidence_ids": [evidence_id],
                            }
                        ],
                    }
                )
            if task == "chapter_events_evidence":
                return response_model.model_validate(
                    {
                        "events": [
                            {
                                "chapter": 1,
                                "sequence": 1,
                                "summary": "Bob leaves while Alice watches.",
                                "story_time": "",
                                "narrative_time": "",
                                "evidence_ids": [evidence_id],
                            }
                        ]
                    }
                )
            if task == "chapter_interpretation":
                return response_model.model_validate(
                    {
                        "chapter_title": "Chapter 1",
                        "summary": "Alice watches Bob leave the scene.",
                        "key_points": ["Alice is a direct witness."],
                        "themes": ["observation"],
                        "claims": [
                            {
                                "statement": "Alice saw Bob leave.",
                                "kind": "author_explicit",
                                "status": "confirmed",
                                "confidence": 0.9,
                                "introduced_chapter": 1,
                                "resolved_chapter": None,
                                "reasoning": [],
                                "evidence_ids": [evidence_id],
                            }
                        ],
                        "uncertainties": [],
                    }
                )
            if task == "part_synthesis":
                return PartSynthesis(chapter_numbers=[], summary="Part summary")
            if task == "book_editorial":
                return contracts.BookEditorial(overview="Book overview")
            raise AssertionError(f"unexpected task: {task}")

    adapter = FieldGroupedChapterAdapter()
    report = analyze_book(
        BookInput(
            work_id="work-field-groups",
            edition_id="edition-field-groups",
            title="Long Witness Chapter",
            author="A. Writer",
            chapters=[
                SourceChapter(
                    number=1,
                    title="Chapter 1",
                    text="Alice saw Bob leave. " * 80,
                )
            ],
        ),
        adapter,
        PipelineConfig(
            reading_model="reading",
            max_chunk_chars=1000,
            chunk_overlap_chars=0,
        ),
    )

    assert "chapter_synthesis" not in adapter.tasks
    assert adapter.tasks.count("segment_analysis") == 2
    assert {
        "chapter_people_relations",
        "chapter_events_evidence",
        "chapter_interpretation",
    }.issubset(adapter.tasks)
    chapter = report.chapters[0]
    assert chapter.summary == "Alice watches Bob leave the scene."
    assert chapter.people[0].citations[0].verified is True
    assert chapter.relations[0].citations[0].verified is True
    assert chapter.events[0].citations[0].verified is True
    assert chapter.claims[0].citations[0].verified is True
    assert chapter.evidence
    assert all(item.evidence_id.startswith("ev-") for item in chapter.evidence)


def test_multisegment_chapter_resumes_segments_and_completed_field_groups() -> None:
    class ResumableChapterAdapter:
        def __init__(self) -> None:
            self.fail_events = True
            self.tasks: list[str] = []
            self.event_singleton_calls = 0

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, model, temperature
            self.tasks.append(task)
            if task == "segment_analysis":
                source = prompt.split("<source>\n", 1)[1].split("\n</source>", 1)[0]
                excerpt = source[:24]
                citation = SourceCitation(chapter=1, excerpt=excerpt)
                return ChapterAnalysis(
                    chapter_number=1,
                    chapter_title="Chapter 1",
                    summary="A witnessed departure.",
                    people=[
                        contracts.PersonFinding(
                            name="Alice",
                            first_chapter=1,
                            citations=[citation],
                        )
                    ],
                    events=[
                        TimelineEvent(
                            chapter=1,
                            summary="Alice witnesses a departure.",
                            citations=[citation],
                        )
                    ],
                )
            evidence_ids = list(
                dict.fromkeys(re.findall(r'"evidence_id":\s*"([^"]+)"', prompt))
            )
            if task == "chapter_people_relations":
                return response_model.model_validate(
                    {
                        "people": [
                            {
                                "name": "Alice",
                                "first_chapter": 1,
                                "evidence_ids": [evidence_ids[0]],
                            }
                        ]
                    }
                )
            if task == "chapter_events_evidence":
                if len(evidence_ids) > 1:
                    raise ModelOutputTruncatedError("provider length")
                self.event_singleton_calls += 1
                if self.fail_events and self.event_singleton_calls == 2:
                    raise ModelOutputTruncatedError("provider length")
                return response_model.model_validate(
                    {
                        "events": [
                            {
                                "chapter": 1,
                                "summary": "Alice witnesses a departure.",
                                "evidence_ids": [evidence_ids[0]],
                            }
                        ]
                    }
                )
            if task == "chapter_interpretation":
                return response_model.model_validate(
                    {
                        "chapter_title": "Chapter 1",
                        "summary": "Alice witnesses a departure.",
                    }
                )
            if task == "part_synthesis":
                return PartSynthesis(chapter_numbers=[], summary="Part summary")
            if task == "book_editorial":
                return contracts.BookEditorial(overview="Book overview")
            raise AssertionError(f"unexpected task: {task}")

    adapter = ResumableChapterAdapter()
    book = BookInput(
        work_id="work-chapter-resume",
        edition_id="edition-chapter-resume",
        title="Resumable Chapter",
        author="A. Writer",
        chapters=[
            SourceChapter(
                number=1,
                title="Chapter 1",
                text="Alice saw Bob leave. " * 80,
            )
        ],
    )
    config = PipelineConfig(
        reading_model="reading",
        max_chunk_chars=1000,
        chunk_overlap_chars=0,
    )
    checkpoints: list[AnalysisCheckpoint] = []

    with pytest.raises(ModelOutputTruncatedError):
        analyze_book(
            book,
            adapter,
            config,
            on_checkpoint=checkpoints.append,
        )

    assert checkpoints
    work = checkpoints[-1].chapter_work["1"]
    assert len(work.segments) == 2
    assert work.people_relations_batches
    segment_calls = adapter.tasks.count("segment_analysis")
    people_calls = adapter.tasks.count("chapter_people_relations")
    event_calls = adapter.tasks.count("chapter_events_evidence")

    adapter.fail_events = False
    report = analyze_book(
        book,
        adapter,
        config,
        checkpoint=checkpoints[-1],
        on_checkpoint=checkpoints.append,
    )

    assert report.chapters[0].summary == "Alice witnesses a departure."
    assert adapter.tasks.count("segment_analysis") == segment_calls
    assert adapter.tasks.count("chapter_people_relations") == people_calls
    assert adapter.tasks.count("chapter_events_evidence") == event_calls + 2
    assert checkpoints[-1].chapter_work == {}


def test_part_synthesis_caps_batches_inside_one_structural_parent() -> None:
    class BatchRecordingAdapter:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            assert task == "part_synthesis"
            chapter_numbers = [
                int(value)
                for value in re.findall(r'"chapter_number":\s*(\d+)', prompt)
            ]
            self.batch_sizes.append(len(chapter_numbers))
            return PartSynthesis(
                chapter_numbers=[],
                summary=f"Chapters {chapter_numbers[0]}-{chapter_numbers[-1]}",
            )

    adapter = BatchRecordingAdapter()
    chapters = [
        ChapterAnalysis(
            chapter_number=number,
            chapter_title=f"Chapter {number}",
            summary=f"Summary {number}",
        )
        for number in range(1, 15)
    ]
    source_chapters = {
        number: SourceChapter(
            number=number,
            title=f"Chapter {number}",
            text=f"Source {number}",
            structural_path=["Main text", f"Chapter {number}"],
        )
        for number in range(1, 15)
    }

    completed_batches: list[tuple[int, int]] = []
    parts = pipeline._synthesize_parts(
        adapter,
        PipelineConfig(
            reading_model="reading",
            chapters_per_batch=6,
            max_concurrency=1,
        ),
        chapters,
        source_chapters,
        on_batch_completed=lambda completed, total: completed_batches.append(
            (completed, total)
        ),
    )

    assert adapter.batch_sizes == [6, 6, 2]
    assert completed_batches == [(1, 3), (2, 3), (3, 3)]
    assert [number for part in parts for number in part.chapter_numbers] == list(
        range(1, 15)
    )


def test_part_synthesis_splits_a_provider_truncated_batch() -> None:
    class TruncatingPartAdapter:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            assert task == "part_synthesis"
            chapter_numbers = [
                int(value)
                for value in re.findall(r'"chapter_number":\s*(\d+)', prompt)
            ]
            self.batch_sizes.append(len(chapter_numbers))
            if len(chapter_numbers) > 2:
                raise ModelOutputTruncatedError("provider length")
            return PartSynthesis(
                chapter_numbers=[],
                summary=f"Chapters {chapter_numbers[0]}-{chapter_numbers[-1]}",
            )

    adapter = TruncatingPartAdapter()
    chapters = [
        ChapterAnalysis(
            chapter_number=number,
            chapter_title=f"Chapter {number}",
            summary=f"Summary {number}",
        )
        for number in range(1, 9)
    ]
    source_chapters = {
        number: SourceChapter(
            number=number,
            title=f"Chapter {number}",
            text=f"Source {number}",
        )
        for number in range(1, 9)
    }

    parts = pipeline._synthesize_parts(
        adapter,
        PipelineConfig(
            reading_model="reading",
            chapters_per_batch=8,
            max_concurrency=1,
        ),
        chapters,
        source_chapters,
    )

    assert adapter.batch_sizes == [8, 4, 2, 2, 4, 2, 2]
    assert [number for part in parts for number in part.chapter_numbers] == list(
        range(1, 9)
    )


def test_pipeline_analyzes_chapters_with_bounded_concurrency() -> None:
    class ConcurrentAdapter:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.release = threading.Event()
            self.active = 0
            self.max_active = 0
            self.started = 0

        def generate(
            self,
            *,
            task,
            system,
            prompt,
            response_model,
            model,
            temperature=0.1,
        ):
            del system, response_model, model, temperature
            if task == "segment_analysis":
                match = re.search(r"Chapter: (\d+) -", prompt)
                assert match is not None
                chapter_number = int(match.group(1))
                with self.lock:
                    self.active += 1
                    self.started += 1
                    self.max_active = max(self.max_active, self.active)
                    if self.started >= 10:
                        self.release.set()
                self.release.wait(timeout=2)
                time.sleep(0.01)
                with self.lock:
                    self.active -= 1
                return ChapterAnalysis(
                    chapter_number=chapter_number,
                    chapter_title=f"Chapter {chapter_number}",
                    summary=f"Summary {chapter_number}",
                )
            if task == "part_synthesis":
                return PartSynthesis(chapter_numbers=[], summary="Part summary")
            if task == "book_editorial":
                return contracts.BookEditorial(overview="Book overview")
            raise AssertionError(f"unexpected task: {task}")

    adapter = ConcurrentAdapter()
    book = BookInput(
        work_id="work-concurrent",
        edition_id="edition-concurrent",
        title="Concurrent Book",
        author="A. Writer",
        chapters=[
            SourceChapter(
                number=number,
                title=f"Chapter {number}",
                text=f"Chapter {number} source text.",
            )
            for number in range(1, 13)
        ],
    )

    report = analyze_book(
        book,
        adapter,
        PipelineConfig(reading_model="reading", max_concurrency=10),
    )

    assert adapter.max_active == 10
    assert [chapter.chapter_number for chapter in report.chapters] == list(range(1, 13))


def test_pipeline_adds_an_ai_subtitle_to_an_ordinal_only_source_heading() -> None:
    source_excerpt = "The missing necklace was found beneath the cabin bed."
    chapter = ChapterAnalysis(
        chapter_number=3,
        chapter_title="The missing necklace",
        summary="A hidden necklace changes the investigation.",
        evidence=[
            EvidenceFinding(
                title="Missing necklace",
                summary="The necklace is recovered.",
                citation=citation(3, source_excerpt),
            )
        ],
    )
    adapter = StaticModelAdapter(
        {
            "segment_analysis": chapter,
            "part_synthesis": PartSynthesis(
                chapter_numbers=[3],
                summary="The necklace is recovered.",
            ),
            "book_editorial": contracts.BookEditorial(
                overview="A recovered clue changes the case."
            ),
        }
    )

    report = analyze_book(
        BookInput(
            work_id="work-titles",
            edition_id="edition-titles",
            title="River Mystery",
            author="A. Writer",
            chapters=[
                SourceChapter(
                    number=3,
                    title="第三章",
                    text=source_excerpt,
                )
            ],
        ),
        adapter,
        PipelineConfig(reading_model="reading"),
    )

    assert report.chapters[0].chapter_title == "第三章｜The missing necklace"


def test_reconciliation_only_sends_evidence_supporting_synthesized_claims() -> None:
    supported = citation(1, "The bell rang twice.").model_copy(
        update={"verified": True, "start_char": 10, "end_char": 30}
    )
    unrelated = citation(2, "The boat left at dawn.").model_copy(
        update={"verified": True, "start_char": 5, "end_char": 27}
    )
    synthesis = BookSynthesis(
        overview="A bell matters.",
        claims=[
            ClaimFinding(
                statement="The bell rang twice.",
                kind="author_explicit",
                status="confirmed",
                confidence=1,
                introduced_chapter=1,
                citations=[supported],
            )
        ],
    )

    selected = _reconciliation_evidence(
        synthesis,
        [
            EvidenceFinding(
                evidence_id="supported",
                title="Bell",
                summary="The bell rang twice.",
                citation=supported,
            ),
            EvidenceFinding(
                evidence_id="unrelated",
                title="Boat",
                summary="The boat left.",
                citation=unrelated,
            ),
        ],
    )

    assert [item.evidence_id for item in selected] == ["supported"]


def test_ordinal_title_falls_back_to_a_concise_summary_title() -> None:
    assert (
        _resolved_chapter_title(
            "第十五章",
            "第十五章",
            "手枪从河中被捞出。调查仍在继续。",
        )
        == "第十五章｜手枪从河中被捞出"
    )
