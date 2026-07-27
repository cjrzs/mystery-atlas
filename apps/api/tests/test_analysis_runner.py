import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from mystery_atlas_analyzer.contracts import (
    AnalysisCheckpoint,
    BookEditorial,
    BookSynthesis,
    ChapterAnalysis,
    ClaimAuditResult,
    ClaimFinding,
    ClaimMergeResult,
    EvidenceFinding,
    PartSynthesis,
    PersonFinding,
    ReconciliationResult,
    RelationFinding,
    SourceCitation,
)
from mystery_atlas_analyzer.model_adapters import ModelResponseError, StaticModelAdapter
from mystery_atlas_analyzer.repository import SQLAlchemyAnalysisRepository
from mystery_atlas_analyzer.runner import run_analysis_job
from mystery_atlas_analyzer.settings import AnalyzerSettings
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from mystery_atlas_api import analysis_dispatch
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


@pytest.fixture
def resumable_job(local_tmp_path: Path) -> tuple[object, str, str, str]:
    database_path = local_tmp_path / "resumable-analysis.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    excerpt = "Nora found the blue thread beside the locked window."

    with Session(engine) as session:
        user = User(
            email="resume-runner@example.test",
            password_hash="unused",
            display_name="Resume Runner",
        )
        session.add(user)
        session.flush()
        work = Work(
            slug="resume-runner-book",
            title="Resume Runner Book",
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
        session.add(
            BookImport(
                user_id=user.id,
                original_name="resume-runner.txt",
                stored_path=str(local_tmp_path / "resume-runner.txt"),
                source_format="txt",
                size_bytes=100,
                content_hash="b" * 64,
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
                        "source_locator": {"format": "txt", "start_char": 0},
                    }
                ],
            )
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

    yield engine, database_url, job_id, excerpt
    engine.dispose()


def resumable_outputs(
    excerpt: str,
) -> tuple[ChapterAnalysis, PartSynthesis, BookSynthesis, ReconciliationResult]:
    citation = SourceCitation(chapter=1, excerpt=excerpt)
    claim = ClaimFinding(
        statement="The blue thread was found beside the window.",
        kind="author_explicit",
        status="confirmed",
        confidence=0.95,
        introduced_chapter=1,
        citations=[citation],
    )
    chapter = ChapterAnalysis(
        chapter_number=1,
        chapter_title="The Window",
        summary="Nora finds a physical clue.",
        claims=[claim],
    )
    part = PartSynthesis(
        chapter_numbers=[1],
        summary="A physical clue challenges the account.",
        claims=[claim],
    )
    synthesis = BookSynthesis(
        overview="The investigation depends on physical evidence.",
        claims=[claim],
    )
    reconciliation = ReconciliationResult(final_claims=[claim])
    return chapter, part, synthesis, reconciliation


def test_runner_resumes_a_persisted_book_synthesis_checkpoint(
    resumable_job: tuple[object, str, str, str],
) -> None:
    engine, database_url, job_id, excerpt = resumable_job
    chapter, part, synthesis, _reconciliation = resumable_outputs(excerpt)
    with Session(engine) as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        job.status = "failed"
        job.stage = "book_synthesis"
        job.progress = 65
        job.result_summary = {
            "checkpoint": AnalysisCheckpoint(
                chapters=[chapter],
                parts=[part],
            ).model_dump(mode="json")
        }
        session.commit()

    adapter = StaticModelAdapter(
        {
            "book_claim_merge": ClaimMergeResult(),
            "book_editorial": BookEditorial(
                overview=synthesis.overview,
            ),
            "book_claim_audit": ClaimAuditResult(),
        }
    )
    repository = SQLAlchemyAnalysisRepository(engine=engine)

    result = run_analysis_job(
        job_id,
        settings=settings(database_url),
        adapter=adapter,
        repository=repository,
    )

    assert result["status"] == "completed"
    assert adapter.calls == [
        "book_claim_merge",
        "book_editorial",
        "book_claim_audit",
    ]


def test_runner_persists_the_real_failure_stage_and_latest_checkpoint(
    resumable_job: tuple[object, str, str, str],
) -> None:
    engine, database_url, job_id, excerpt = resumable_job
    chapter, part, _, _ = resumable_outputs(excerpt)
    adapter = StaticModelAdapter(
        {
            "segment_analysis": chapter,
            "part_synthesis": part,
        }
    )
    repository = SQLAlchemyAnalysisRepository(engine=engine)

    with pytest.raises(ModelResponseError):
        run_analysis_job(
            job_id,
            settings=settings(database_url),
            adapter=adapter,
            repository=repository,
        )

    with Session(engine) as session:
        saved_job = session.get(AnalysisJob, job_id)
        assert saved_job is not None
        assert saved_job.status == "failed"
        assert saved_job.stage == "book_synthesis"
        assert saved_job.progress == 65
        checkpoint = AnalysisCheckpoint.model_validate(
            saved_job.result_summary["checkpoint"]
        )
        assert checkpoint.parts == [part]


def test_runner_does_not_repeat_a_failed_stage_outside_the_adapter(
    resumable_job: tuple[object, str, str, str],
) -> None:
    engine, database_url, job_id, excerpt = resumable_job
    chapter, part, synthesis, _reconciliation = resumable_outputs(excerpt)

    class FailBookSynthesisOnce:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.book_attempts = 0

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
            if task == "segment_analysis":
                return chapter
            if task == "part_synthesis":
                return part
            if task == "book_claim_merge":
                self.book_attempts += 1
                if self.book_attempts == 1:
                    raise ModelResponseError("temporary book synthesis failure")
                return ClaimMergeResult()
            if task == "book_editorial":
                return BookEditorial(overview=synthesis.overview)
            if task == "book_claim_audit":
                return ClaimAuditResult()
            raise AssertionError(f"unexpected task: {task}")

    adapter = FailBookSynthesisOnce()
    repository = SQLAlchemyAnalysisRepository(engine=engine)

    with pytest.raises(ModelResponseError):
        run_analysis_job(
            job_id,
            settings=settings(database_url),
            adapter=adapter,
            repository=repository,
        )

    assert adapter.calls == [
        "segment_analysis",
        "part_synthesis",
        "book_claim_merge",
    ]


def test_repository_records_ai_request_heartbeat_metadata(
    resumable_job: tuple[object, str, str, str],
) -> None:
    engine, _, job_id, _ = resumable_job
    repository = SQLAlchemyAnalysisRepository(engine=engine)

    assert hasattr(repository, "heartbeat_job")
    repository.heartbeat_job(
        job_id,
        call_id="call-123",
        task="book_editorial",
        response_chars=12_345,
        content_idle_seconds=7,
    )

    with Session(engine) as session:
        job = session.get(AnalysisJob, job_id)
        assert job is not None
        assert job.heartbeat_at is not None
        assert job.current_call_id == "call-123"
        assert job.stage_detail == "book_editorial"
        assert job.response_chars == 12_345
        assert job.content_idle_seconds == 7


def test_stale_running_jobs_become_failed_without_losing_their_stage(
    resumable_job: tuple[object, str, str, str],
) -> None:
    engine, _, job_id, _ = resumable_job
    now = datetime.now(UTC)
    with Session(engine) as session:
        stale = session.get(AnalysisJob, job_id)
        assert stale is not None
        stale.status = "running"
        stale.stage = "book_synthesis"
        stale.progress = 70
        stale.heartbeat_at = now - timedelta(minutes=6)
        fresh = AnalysisJob(
            work_id=stale.work_id,
            edition_id=stale.edition_id,
            track="full",
            status="running",
            stage="segment_analysis",
            progress=20,
            heartbeat_at=now - timedelta(minutes=1),
        )
        session.add(fresh)
        session.commit()
        fresh_id = fresh.id

    assert hasattr(analysis_dispatch, "mark_stale_running_analyses")
    with Session(engine) as session:
        recovered = analysis_dispatch.mark_stale_running_analyses(
            session,
            now=now,
            stale_after_seconds=300,
        )
        session.commit()

    assert recovered == 1
    with Session(engine) as session:
        stale = session.get(AnalysisJob, job_id)
        fresh = session.get(AnalysisJob, fresh_id)
        assert stale is not None
        assert fresh is not None
        assert stale.status == "failed"
        assert stale.stage == "book_synthesis"
        assert stale.progress == 70
        assert "heartbeat" in (stale.error or "")
        assert fresh.status == "running"


def test_stale_analysis_watchdog_runs_and_can_be_stopped(monkeypatch) -> None:
    called = Event()
    monkeypatch.setattr(
        analysis_dispatch,
        "recover_stale_running_analyses",
        lambda: called.set() or 0,
        raising=False,
    )

    assert hasattr(analysis_dispatch, "start_stale_analysis_watchdog")
    stop = analysis_dispatch.start_stale_analysis_watchdog(
        interval_seconds=0.01
    )
    try:
        assert called.wait(timeout=0.5)
    finally:
        stop()


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
            "book_claim_merge": ClaimMergeResult(),
            "book_editorial": BookEditorial(
                overview="The investigation relies on checking physical evidence.",
                core_ideas=["Physical evidence can contradict testimony."],
                mysteries=["Who placed the blue thread beside the window?"],
            ),
            "book_claim_audit": ClaimAuditResult(),
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
