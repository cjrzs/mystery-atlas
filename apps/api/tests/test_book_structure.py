from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from mystery_atlas_api.book_structure import apply_reviewed_structure
from mystery_atlas_api.database import Base, SessionLocal, engine
from mystery_atlas_api.main import app
from mystery_atlas_api.models import (
    AnalysisJob,
    BookImport,
    Chapter,
    Edition,
    User,
    Work,
    utcnow,
)
from mystery_atlas_api.security import SESSION_COOKIE, create_session_token


def make_import() -> BookImport:
    return BookImport(
        user_id="user-1",
        original_name="nested.epub",
        stored_path="nested.epub",
        source_format="epub",
        size_bytes=1,
        content_hash="a" * 64,
        status="completed",
        stage="structure_review_required",
        progress=100,
        chapter_count=2,
        structure_version="epub-structure-v1-old",
        structure_source="spine",
        structure_confidence="low",
        structure_warnings=["structure needs review"],
        structure_requires_review=True,
        chapters=[
            {
                "number": 1,
                "title": "Part One",
                "text": "Opening\n\nChapter One\n\nBody one",
                "blocks": [
                    {"type": "paragraph", "text": "Opening"},
                    {"type": "heading", "level": 2, "text": "Chapter One"},
                    {"type": "paragraph", "text": "Body one"},
                ],
                "structural_path": ["Part One"],
            },
            {
                "number": 2,
                "title": "Part Two",
                "text": "Body two",
                "blocks": [
                    {"type": "paragraph", "text": "Body two"},
                ],
                "structural_path": ["Part Two"],
            },
        ],
    )


def test_reviewed_structure_can_split_merge_and_preserve_every_block() -> None:
    book_import = make_import()

    apply_reviewed_structure(
        book_import,
        [
            {
                "title": "Prologue",
                "parent_path": ["Part One"],
                "segments": [
                    {"source_number": 1, "start_block": 0, "end_block": 1}
                ],
            },
            {
                "title": "Chapter One",
                "parent_path": ["Part One"],
                "segments": [
                    {"source_number": 1, "start_block": 1, "end_block": 3},
                    {"source_number": 2, "start_block": 0, "end_block": 1},
                ],
            },
        ],
    )

    assert [chapter["title"] for chapter in book_import.chapters] == [
        "Prologue",
        "Chapter One",
    ]
    assert book_import.chapters[1]["structural_path"] == [
        "Part One",
        "Chapter One",
    ]
    assert book_import.chapters[1]["text"] == "Chapter One\n\nBody one\n\nBody two"
    assert sum(len(chapter["blocks"]) for chapter in book_import.chapters) == 4
    assert book_import.structure_source == "manual_review"
    assert book_import.structure_confidence == "high"
    assert book_import.structure_requires_review is False
    assert book_import.structure_version.startswith("epub-structure-v2-manual-")


def test_reviewed_structure_rejects_missing_or_duplicated_blocks() -> None:
    book_import = make_import()

    try:
        apply_reviewed_structure(
            book_import,
            [
                {
                    "title": "Incomplete",
                    "parent_path": [],
                    "segments": [
                        {"source_number": 1, "start_block": 0, "end_block": 2}
                    ],
                }
            ],
        )
    except ValueError as exc:
        assert "cover every source block exactly once" in str(exc)
    else:
        raise AssertionError("incomplete manual structure must be rejected")


def test_uploader_can_save_reviewed_structure_and_resume_analysis() -> None:
    Base.metadata.create_all(bind=engine)
    slug = f"structure-review-{uuid4().hex[:8]}"
    with SessionLocal() as session:
        owner = User(
            email=f"structure-review-{uuid4().hex[:8]}@example.test",
            password_hash="unused",
            display_name="Uploader",
        )
        session.add(owner)
        session.flush()
        work = Work(
            slug=slug,
            title="Nested EPUB",
            author="A. Writer",
            status="analyzing",
            visibility="private",
            owner_id=owner.id,
            maintainer_id=owner.id,
        )
        session.add(work)
        session.flush()
        edition = Edition(
            work_id=work.id,
            title=work.title,
            source_format="epub",
            visibility="private",
            maintainer_id=owner.id,
            structure_version="epub-structure-v1-old",
        )
        session.add(edition)
        session.flush()
        book_import = make_import()
        book_import.user_id = owner.id
        book_import.work_id = work.id
        book_import.edition_id = edition.id
        book_import.finalized_at = utcnow()
        session.add(book_import)
        job = AnalysisJob(
            work_id=work.id,
            edition_id=edition.id,
            track="full",
            stage="structure_review",
            status="waiting_structure_review",
            progress=0,
            structure_version=book_import.structure_version,
        )
        session.add(job)
        session.commit()
        token = create_session_token(owner)
        owner_id = owner.id
        work_id = work.id
        edition_id = edition.id
        import_id = book_import.id
        job_id = job.id

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, token)
        response = client.put(
            f"/api/v1/imports/{import_id}/structure",
            json={
                "chapters": [
                    {
                        "title": "Prologue",
                        "parent_path": ["Part One"],
                        "segments": [
                            {
                                "source_number": 1,
                                "start_block": 0,
                                "end_block": 1,
                            }
                        ],
                    },
                    {
                        "title": "Chapter One",
                        "parent_path": ["Part One"],
                        "segments": [
                            {
                                "source_number": 1,
                                "start_block": 1,
                                "end_block": 3,
                            },
                            {
                                "source_number": 2,
                                "start_block": 0,
                                "end_block": 1,
                            },
                        ],
                    },
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["structure_requires_review"] is False
    assert response.json()["stage"] == "ready_for_analysis"
    with SessionLocal() as session:
        saved_import = session.get(BookImport, import_id)
        saved_edition = session.get(Edition, edition_id)
        saved_job = session.get(AnalysisJob, job_id)
        assert saved_import is not None
        assert saved_edition is not None
        assert saved_job is not None
        assert saved_import.chapter_count == 2
        assert saved_edition.revision == 2
        assert saved_edition.structure_version == saved_import.structure_version
        assert saved_job.structure_version == saved_import.structure_version
        assert saved_job.status == "waiting_configuration"
        chapters = list(
            session.scalars(
                select(Chapter)
                .where(Chapter.edition_id == edition_id)
                .order_by(Chapter.number)
            )
        )
        assert [chapter.title for chapter in chapters] == [
            "Prologue",
            "Chapter One",
        ]
        for chapter in chapters:
            session.delete(chapter)
        session.delete(saved_job)
        session.delete(saved_import)
        session.delete(saved_edition)
        session.delete(session.get(Work, work_id))
        session.delete(session.get(User, owner_id))
        session.commit()
