import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from mystery_atlas_analyzer.contracts import (
    BookSynthesis,
    ChapterAnalysis,
    ClaimFinding,
    EvidenceFinding,
    PartSynthesis,
    PersonFinding,
    ReconciliationResult,
    RelationFinding,
    SourceCitation,
)
from mystery_atlas_analyzer.model_adapters import StaticModelAdapter
from mystery_atlas_analyzer.repository import SQLAlchemyAnalysisRepository
from mystery_atlas_analyzer.runner import run_analysis_job
from mystery_atlas_analyzer.settings import AnalyzerSettings
from mystery_atlas_api.database import Base
from mystery_atlas_api.models import (
    AnalysisJob,
    BookImport,
    CaseRecord,
    Chapter,
    ChapterSnapshot,
    Claim,
    Edition,
    Evidence,
    Person,
    PersonAlias,
    PersonRelation,
    User,
    Work,
)


def settings(database_url: str) -> AnalyzerSettings:
    return AnalyzerSettings(
        database_url=database_url,
        ai_provider="openai-compatible",
        ai_base_url="https://unused.test/v1",
        ai_api_key="",
        reading_model="test-reading",
        truth_model="test-truth",
        timeout_seconds=1,
        max_output_tokens=2000,
        max_chunk_chars=12_000,
        chunk_overlap_chars=500,
        chapters_per_batch=6,
    )


@pytest.fixture
def local_tmp_path() -> Path:
    root = Path.cwd() / ".test-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, ignore_cleanup_errors=True) as path:
        yield Path(path)


def test_runner_persists_a_complete_analysis(local_tmp_path: Path) -> None:
    database_path = local_tmp_path / "analysis.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    excerpt = "Nora found the blue thread beside the locked window."
    citation = SourceCitation(chapter=1, excerpt=excerpt)
    claim = ClaimFinding(
        statement="The blue thread was found beside the window.",
        kind="author_explicit",
        status="confirmed",
        confidence=0.95,
        introduced_chapter=1,
        citations=[citation],
    )
    chapter_analysis = ChapterAnalysis(
        chapter_number=1,
        chapter_title="The Window",
        summary="Nora finds a physical clue.",
        evidence=[
            EvidenceFinding(
                title="Blue thread",
                summary="A thread lies beside the locked window.",
                citation=citation,
            )
        ],
        people=[
            PersonFinding(
                name="Nora",
                aliases=["N. Vale"],
                role="investigator",
                first_chapter=1,
                citations=[citation],
            ),
            PersonFinding(
                name="Eli",
                role="witness",
                first_chapter=1,
                citations=[citation],
            ),
        ],
        relations=[
            RelationFinding(
                source="Nora",
                target="Eli",
                label="questions",
                kind="investigation",
                status="confirmed",
                first_chapter=1,
                citations=[citation],
            )
        ],
        claims=[claim],
    )
    adapter = StaticModelAdapter(
        {
            "segment_analysis": chapter_analysis,
            "part_synthesis": PartSynthesis(
                chapter_numbers=[1],
                summary="A physical clue challenges the locked-room account.",
                claims=[claim],
            ),
            "book_synthesis": BookSynthesis(
                overview="The investigation relies on checking physical evidence.",
                core_ideas=["Physical evidence can contradict testimony."],
                mysteries=["Who placed the blue thread beside the window?"],
                claims=[claim],
            ),
            "book_reconciliation": ReconciliationResult(final_claims=[claim]),
        }
    )

    with Session(engine) as session:
        user = User(
            email="runner@example.test",
            password_hash="unused",
            display_name="Runner",
        )
        session.add(user)
        session.flush()
        work = Work(
            slug="runner-book",
            title="Runner Book",
            author="A. Writer",
            visibility="private",
            owner_id=user.id,
            maintainer_id=user.id,
            status="analyzing",
        )
        session.add(work)
        session.flush()
        edition = Edition(
            work_id=work.id,
            title=work.title,
            source_format="txt",
            visibility="private",
            maintainer_id=user.id,
        )
        session.add(edition)
        session.flush()
        session.add(
            Chapter(
                edition_id=edition.id,
                number=1,
                title="The Window",
                source_locator={"format": "txt", "start_char": 0},
            )
        )
        book_import = BookImport(
            user_id=user.id,
            original_name="runner.txt",
            stored_path=str(local_tmp_path / "runner.txt"),
            source_format="txt",
            size_bytes=100,
            content_hash="a" * 64,
            status="completed",
            stage="ready_for_analysis",
            work_id=work.id,
            edition_id=edition.id,
            chapters=[
                {
                    "number": 1,
                    "title": "The Window",
                    "text": f"At midnight, {excerpt} Nora wrote it down.",
                    "characters": 100,
                    "source_locator": {
                        "format": "txt",
                        "start_char": 0,
                    },
                }
            ],
        )
        session.add(book_import)
        session.add_all(
            [
                Person(
                    work_id=work.id,
                    canonical_name="Preface Author",
                    role="foreword contributor",
                    first_chapter=1,
                ),
                Evidence(
                    work_id=work.id,
                    first_chapter=1,
                    title="Foreword evidence",
                    summary="This evidence came from front matter.",
                    source_type="text",
                    status="confirmed",
                ),
                ChapterSnapshot(
                    work_id=work.id,
                    chapter=9,
                    graph_payload={},
                    timeline_payload=[],
                    summary="A stale front-matter snapshot.",
                ),
            ]
        )
        job = AnalysisJob(
            work_id=work.id,
            edition_id=edition.id,
            track="full",
            stage="source_validation",
            status="queued",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    repository = SQLAlchemyAnalysisRepository(engine=engine)
    result = run_analysis_job(
        job_id,
        settings=settings(database_url),
        adapter=adapter,
        repository=repository,
    )

    assert result["status"] == "completed"
    with Session(engine) as session:
        saved_job = session.get(AnalysisJob, job_id)
        assert saved_job is not None
        assert saved_job.status == "completed"
        assert saved_job.progress == 100
        assert saved_job.result_summary["audit"]["coverage"] == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(Claim)) == 1
        assert session.scalar(select(func.count()).select_from(ChapterSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(Person)) == 2
        assert session.scalar(select(func.count()).select_from(PersonAlias)) == 1
        assert session.scalar(select(func.count()).select_from(PersonRelation)) == 1
        assert session.scalar(select(func.count()).select_from(CaseRecord)) == 1
        assert session.scalar(
            select(func.count())
            .select_from(Person)
            .where(Person.canonical_name == "Preface Author")
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.title == "Foreword evidence")
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(ChapterSnapshot)
            .where(ChapterSnapshot.chapter == 9)
        ) == 0
    repository.engine.dispose()
    engine.dispose()
