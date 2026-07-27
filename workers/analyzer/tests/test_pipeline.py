import re
import threading
import time

from mystery_atlas_analyzer.contracts import (
    BookInput,
    BookSynthesis,
    ChapterAnalysis,
    ClaimFinding,
    EvidenceFinding,
    PartSynthesis,
    ReconciliationResult,
    SourceChapter,
    SourceCitation,
    StructureSection,
)
from mystery_atlas_analyzer.model_adapters import StaticModelAdapter
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
            "book_synthesis": BookSynthesis(
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
                claims=[final_claim],
            ),
            "book_reconciliation": ReconciliationResult(
                final_claims=[final_claim],
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
        "book_synthesis",
        "book_reconciliation",
    ]
    assert report.audit.unverified_citations == 0
    assert report.audit.coverage == 1
    assert report.evidence_index[0].evidence_id.startswith("ev-")
    assert report.evidence_index[0].citation.verified is True
    assert report.evidence_index[0].citation.page == 4
    assert report.reconciliation.final_claims[0].kind == "author_explicit"


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
            "book_synthesis": BookSynthesis(
                overview="Opening overview",
                claims=[claim],
            ),
            "book_reconciliation": ReconciliationResult(
                unsupported_claims=[claim.statement],
                uncertainties=["The source excerpt could not be verified."],
            ),
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
            if task == "book_synthesis":
                return BookSynthesis(overview="Book overview")
            if task == "book_reconciliation":
                return ReconciliationResult()
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
            "book_synthesis": BookSynthesis(overview="A recovered clue changes the case."),
            "book_reconciliation": ReconciliationResult(),
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
