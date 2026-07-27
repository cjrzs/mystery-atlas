from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    email_verified: Mapped[bool] = mapped_column(default=True)
    can_publish: Mapped[bool] = mapped_column(default=True)
    upload_quota_mb: Mapped[int] = mapped_column(Integer, default=500)
    reader_preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class Work(TimestampMixin, Base):
    __tablename__ = "works"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    author: Mapped[str] = mapped_column(String(200), index=True)
    synopsis: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    region: Mapped[str | None] = mapped_column(String(80))
    publication_year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    cover_key: Mapped[str | None] = mapped_column(String(500))
    visibility: Mapped[str] = mapped_column(String(20), default="public", index=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    maintainer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    analysis_progress: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_feedback_count: Mapped[int] = mapped_column(Integer, default=0)


class Edition(TimestampMixin, Base):
    __tablename__ = "editions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    publisher: Mapped[str | None] = mapped_column(String(200))
    translator: Mapped[str | None] = mapped_column(String(200))
    isbn: Mapped[str | None] = mapped_column(String(32), index=True)
    source_format: Mapped[str] = mapped_column(String(20))
    content_fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    is_public_reference: Mapped[bool] = mapped_column(default=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private", index=True)
    maintainer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    is_available: Mapped[bool] = mapped_column(default=True)
    rights_confirmed: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("edition_id", "number", name="uq_chapter_edition_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    text_fingerprint: Mapped[str | None] = mapped_column(String(128))


class Person(TimestampMixin, Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(200), index=True)
    role: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    first_chapter: Mapped[int] = mapped_column(Integer, default=1)
    identity_status: Mapped[str] = mapped_column(String(32), default="confirmed")


class PersonAlias(TimestampMixin, Base):
    __tablename__ = "person_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    first_chapter: Mapped[int] = mapped_column(Integer)
    merge_reveal_chapter: Mapped[int | None] = mapped_column(Integer)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))


class CaseRecord(TimestampMixin, Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    parent_case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open")


class MysteryQuestion(TimestampMixin, Base):
    __tablename__ = "mystery_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer_claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"))
    reveal_chapter: Mapped[int | None] = mapped_column(Integer)


class Evidence(TimestampMixin, Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    first_chapter: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    citation: Mapped[dict] = mapped_column(JSON, default=dict)
    lifecycle: Mapped[dict] = mapped_column(JSON, default=dict)


class PersonRelation(TimestampMixin, Base):
    __tablename__ = "person_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    source_person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    target_person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(32), default="inferred")
    first_chapter: Mapped[int] = mapped_column(Integer, index=True)
    resolved_chapter: Mapped[int | None] = mapped_column(Integer)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="inferred")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    introduced_chapter: Mapped[int] = mapped_column(Integer)
    resolved_chapter: Mapped[int | None] = mapped_column(Integer)
    reasoning_steps: Mapped[list] = mapped_column(JSON, default=list)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )
    effect: Mapped[str] = mapped_column(String(20), default="supports")
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class ChapterSnapshot(TimestampMixin, Base):
    __tablename__ = "chapter_snapshots"
    __table_args__ = (UniqueConstraint("work_id", "chapter", name="uq_snapshot_work_chapter"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    chapter: Mapped[int] = mapped_column(Integer)
    graph_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline_payload: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")


class Publication(TimestampMixin, Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("work_id", "version", name="uq_publication_work_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    change_summary: Mapped[str] = mapped_column(Text, default="")
    published_by: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class AnalysisJob(TimestampMixin, Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"), index=True)
    track: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_call_id: Mapped[str | None] = mapped_column(String(36))
    stage_detail: Mapped[str | None] = mapped_column(String(300))
    response_chars: Mapped[int] = mapped_column(Integer, default=0)
    content_idle_seconds: Mapped[int] = mapped_column(Integer, default=0)


class BookImport(TimestampMixin, Base):
    __tablename__ = "book_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000), unique=True)
    source_format: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    visibility: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    detected_author: Mapped[str | None] = mapped_column(String(300))
    publisher: Mapped[str | None] = mapped_column(String(200))
    translator: Mapped[str | None] = mapped_column(String(200))
    isbn: Mapped[str | None] = mapped_column(String(32), index=True)
    rights_confirmed: Mapped[bool] = mapped_column(default=False)
    work_id: Mapped[str | None] = mapped_column(ForeignKey("works.id", ondelete="SET NULL"), index=True)
    edition_id: Mapped[str | None] = mapped_column(ForeignKey("editions.id", ondelete="SET NULL"), index=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(60), default="waiting")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    detected_title: Mapped[str | None] = mapped_column(String(500))
    detected_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    chapters: Mapped[list] = mapped_column(JSON, default=list)
    preview: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)


class PrivateLibraryBook(TimestampMixin, Base):
    __tablename__ = "private_library_books"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    work_id: Mapped[str | None] = mapped_column(ForeignKey("works.id", ondelete="SET NULL"), index=True)
    edition_id: Mapped[str | None] = mapped_column(ForeignKey("editions.id", ondelete="SET NULL"))
    import_id: Mapped[str | None] = mapped_column(ForeignKey("book_imports.id", ondelete="CASCADE"), index=True)
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="private_upload", index=True)
    current_chapter: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[float] = mapped_column(Float, default=0)
    private_overrides: Mapped[dict] = mapped_column(JSON, default=dict)


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    work_id: Mapped[str | None] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    edition_id: Mapped[str | None] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="work", index=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(40), default="content", index=True)
    chapter: Mapped[int | None] = mapped_column(Integer, index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    same_issue_count: Mapped[int] = mapped_column(Integer, default=1)
    is_hidden: Mapped[bool] = mapped_column(default=False)
    resolved_revision_id: Mapped[str | None] = mapped_column(String(36))


class ContentRevision(TimestampMixin, Base):
    __tablename__ = "content_revisions"
    __table_args__ = (UniqueConstraint("work_id", "version", name="uq_revision_work_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    edition_id: Mapped[str | None] = mapped_column(ForeignKey("editions.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    source_feedback_id: Mapped[str | None] = mapped_column(ForeignKey("feedback.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(500), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
