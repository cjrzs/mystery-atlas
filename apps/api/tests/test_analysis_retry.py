from uuid import uuid4

from fastapi.testclient import TestClient
from mystery_atlas_analyzer.contracts import (
    AnalysisCheckpoint,
    ChapterAnalysis,
    PartSynthesis,
)

from mystery_atlas_api import analysis_dispatch
from mystery_atlas_api.config import get_settings
from mystery_atlas_api.database import Base, SessionLocal, engine
from mystery_atlas_api.main import app
from mystery_atlas_api.models import (
    AnalysisJob,
    Edition,
    PrivateLibraryBook,
    User,
    Work,
)
from mystery_atlas_api.security import SESSION_COOKIE, create_session_token


def test_only_the_maintainer_can_retry_a_failed_stage(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MYSTERY_ATLAS_AI_BASE_URL", "https://unused.test/v1")
    monkeypatch.setenv("MYSTERY_ATLAS_AI_READING_MODEL", "test-model")
    monkeypatch.setenv("MYSTERY_ATLAS_ANALYSIS_EXECUTION", "inline")
    get_settings.cache_clear()
    dispatched: list[str] = []
    monkeypatch.setattr(
        analysis_dispatch,
        "_spawn_inline",
        dispatched.append,
    )
    Base.metadata.create_all(bind=engine)

    slug = f"retry-stage-{uuid4().hex[:8]}"
    with SessionLocal() as session:
        owner = User(
            email=f"owner-{uuid4().hex[:8]}@example.test",
            password_hash="unused",
            display_name="Owner",
        )
        outsider = User(
            email=f"outsider-{uuid4().hex[:8]}@example.test",
            password_hash="unused",
            display_name="Outsider",
        )
        session.add_all([owner, outsider])
        session.flush()
        work = Work(
            slug=slug,
            title="Retry Stage Book",
            author="A. Writer",
            status="failed",
            visibility="public",
            owner_id=owner.id,
            maintainer_id=owner.id,
            analysis_progress=65,
        )
        session.add(work)
        session.flush()
        edition = Edition(
            work_id=work.id,
            title=work.title,
            source_format="txt",
            visibility="public",
            maintainer_id=owner.id,
        )
        session.add(edition)
        session.flush()
        checkpoint = AnalysisCheckpoint(
            chapters=[
                ChapterAnalysis(
                    chapter_number=1,
                    chapter_title="Opening",
                    summary="Opening summary",
                )
            ],
            parts=[
                PartSynthesis(
                    chapter_numbers=[1],
                    summary="Part summary",
                )
            ],
        )
        job = AnalysisJob(
            work_id=work.id,
            edition_id=edition.id,
            track="full",
            stage="book_synthesis",
            status="failed",
            progress=65,
            error="book_synthesis failed after 3 attempts",
            result_summary={
                "checkpoint": checkpoint.model_dump(mode="json"),
            },
        )
        session.add(job)
        reader_item = PrivateLibraryBook(
            user_id=outsider.id,
            work_id=work.id,
            edition_id=edition.id,
            object_key=f"{outsider.id}:{edition.id}",
            kind="public_reading",
        )
        session.add(reader_item)
        session.commit()
        owner_token = create_session_token(owner)
        outsider_token = create_session_token(outsider)
        owner_id = owner.id
        outsider_id = outsider.id
        work_id = work.id
        edition_id = edition.id
        job_id = job.id
        reader_item_id = reader_item.id

    with TestClient(app) as anonymous:
        public_state = anonymous.get(f"/api/v1/works/{slug}/analysis")
        assert public_state.status_code == 200
        assert public_state.json()["can_retry"] is False
        assert public_state.json()["retry_hint"] == "请登录后由作品维护者重试。"

    with TestClient(app) as outsider_client:
        outsider_client.cookies.set(SESSION_COOKIE, outsider_token)
        denied = outsider_client.post(
            f"/api/v1/analysis-jobs/{job_id}/retry-stage"
        )
        assert denied.status_code == 403
        legacy_denied = outsider_client.post(
            f"/api/v1/library/{reader_item_id}/analysis/retry"
        )
        assert legacy_denied.status_code == 403

    with TestClient(app) as owner_client:
        owner_client.cookies.set(SESSION_COOKIE, owner_token)
        owner_state = owner_client.get(f"/api/v1/works/{slug}/analysis")
        assert owner_state.status_code == 200
        assert owner_state.json()["job_id"] == job_id
        assert owner_state.json()["can_manage_retry"] is True
        assert owner_state.json()["can_retry"] is True
        assert owner_state.json()["can_restart"] is False

        restart_denied = owner_client.post(
            f"/api/v1/analysis-jobs/{job_id}/restart"
        )
        assert restart_denied.status_code == 409

        retried = owner_client.post(
            f"/api/v1/analysis-jobs/{job_id}/retry-stage"
        )
        assert retried.status_code == 202
        assert retried.json()["status"] == "queued"
        assert retried.json()["stage"] == "book_synthesis"
        assert retried.json()["progress"] == 65

    assert dispatched == [job_id]
    with SessionLocal() as session:
        saved_job = session.get(AnalysisJob, job_id)
        assert saved_job is not None
        assert saved_job.status == "queued"
        assert saved_job.stage == "book_synthesis"
        assert saved_job.progress == 65
        assert saved_job.error is None

        session.delete(session.get(PrivateLibraryBook, reader_item_id))
        session.delete(saved_job)
        session.delete(session.get(Edition, edition_id))
        session.delete(session.get(Work, work_id))
        session.delete(session.get(User, owner_id))
        session.delete(session.get(User, outsider_id))
        session.commit()

    get_settings.cache_clear()


def test_uploader_can_restart_a_legacy_job_without_a_checkpoint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MYSTERY_ATLAS_AI_BASE_URL", "https://unused.test/v1")
    monkeypatch.setenv("MYSTERY_ATLAS_AI_READING_MODEL", "test-model")
    monkeypatch.setenv("MYSTERY_ATLAS_ANALYSIS_EXECUTION", "inline")
    get_settings.cache_clear()
    dispatched: list[str] = []
    monkeypatch.setattr(
        analysis_dispatch,
        "_spawn_inline",
        dispatched.append,
    )
    Base.metadata.create_all(bind=engine)
    slug = f"legacy-retry-{uuid4().hex[:8]}"
    with SessionLocal() as session:
        uploader = User(
            email=f"uploader-{uuid4().hex[:8]}@example.test",
            password_hash="unused",
            display_name="Uploader",
        )
        session.add(uploader)
        session.flush()
        work = Work(
            slug=slug,
            title="Legacy Failed Upload",
            author="A. Writer",
            status="failed",
            visibility="public",
            owner_id=uploader.id,
            maintainer_id=uploader.id,
        )
        session.add(work)
        session.flush()
        edition = Edition(
            work_id=work.id,
            title=work.title,
            source_format="epub",
            visibility="public",
            maintainer_id=uploader.id,
        )
        session.add(edition)
        session.flush()
        job = AnalysisJob(
            work_id=work.id,
            edition_id=edition.id,
            track="full",
            stage="failed",
            status="failed",
            progress=0,
            error="model response was truncated by max_tokens",
            result_summary={},
        )
        session.add(job)
        session.commit()
        uploader_token = create_session_token(uploader)
        uploader_id = uploader.id
        work_id = work.id
        edition_id = edition.id
        job_id = job.id

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, uploader_token)
        response = client.get(f"/api/v1/works/{slug}/analysis")
        restarted = client.post(f"/api/v1/analysis-jobs/{job_id}/restart")

    assert response.status_code == 200
    assert response.json()["can_manage_retry"] is True
    assert response.json()["can_retry"] is False
    assert response.json()["can_restart"] is True
    assert response.json()["retry_hint"] == (
        "该旧任务没有阶段检查点，只能从头重新分析；确认后会重新消耗 Token。"
    )
    assert restarted.status_code == 202
    assert restarted.json()["status"] == "queued"
    assert restarted.json()["stage"] == "source_validation"
    assert restarted.json()["progress"] == 0
    assert dispatched == [job_id]

    with SessionLocal() as session:
        saved_job = session.get(AnalysisJob, job_id)
        assert saved_job is not None
        assert saved_job.result_summary == {}
        session.delete(saved_job)
        session.delete(session.get(Edition, edition_id))
        session.delete(session.get(Work, work_id))
        session.delete(session.get(User, uploader_id))
        session.commit()

    get_settings.cache_clear()
