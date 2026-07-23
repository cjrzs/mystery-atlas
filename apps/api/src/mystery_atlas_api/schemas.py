from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str
    role: Literal["user", "admin"]


class BookImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_name: str
    source_format: str
    size_bytes: int
    status: str
    stage: str
    progress: int
    detected_title: str | None
    detected_author: str | None
    publisher: str | None
    translator: str | None
    isbn: str | None
    visibility: str
    rights_confirmed: bool
    work_id: str | None
    edition_id: str | None
    chapter_count: int
    chapters: list[dict]
    preview: str
    error: str | None


class WorkSummary(BaseModel):
    id: str | None = None
    slug: str
    title: str
    author: str
    region: str = ""
    year: int = 0
    tags: list[str] = Field(default_factory=list)
    cases: int = 0
    people: int = 0
    clues: int = 0
    analysis_progress: int = Field(ge=0, le=100)
    status: str
    visibility: str = "public"
    edition_count: int = 1
    unresolved_feedback_count: int = 0
    maintainer_name: str = ""
    updated_at: datetime | None = None


class FinalizeImportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=200)
    publisher: str | None = Field(default=None, max_length=200)
    translator: str | None = Field(default=None, max_length=200)
    isbn: str | None = Field(default=None, max_length=32)
    visibility: Literal["private", "public"]
    rights_confirmed: bool = False


class ReaderChapter(BaseModel):
    number: int
    title: str
    text: str
    characters: int


class ReaderResponse(BaseModel):
    work_id: str
    work_slug: str
    work_title: str
    author: str
    edition_id: str
    edition_title: str
    visibility: str
    chapters: list[ReaderChapter]


class LibraryItemResponse(BaseModel):
    id: str
    kind: str
    work_id: str | None
    work_slug: str | None
    edition_id: str | None
    title: str
    author: str
    visibility: str
    current_chapter: int
    progress: float
    analysis_progress: int
    is_maintainer: bool
    updated_at: datetime


class ProgressUpdate(BaseModel):
    current_chapter: int = Field(ge=1)
    progress: float = Field(ge=0, le=1)


class FeedbackCreate(BaseModel):
    work_id: str | None = None
    edition_id: str | None = None
    entity_type: str = Field(default="work", max_length=40)
    entity_id: str | None = Field(default=None, max_length=100)
    category: str = Field(default="content", max_length=40)
    chapter: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=3, max_length=4000)


class FeedbackResolve(BaseModel):
    status: Literal["resolved", "closed", "duplicate", "open"]
    resolution: str = Field(default="", max_length=4000)
    change_summary: str = Field(default="", max_length=1000)


class FeedbackResponse(BaseModel):
    id: str
    work_id: str | None
    edition_id: str | None
    entity_type: str
    entity_id: str | None
    category: str
    chapter: int | None
    content: str
    status: str
    resolution: str
    same_issue_count: int
    reporter_name: str
    assignee_name: str
    created_at: datetime
    updated_at: datetime


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    body: str
    link: str
    read_at: datetime | None
    created_at: datetime


class GraphNode(BaseModel):
    id: str
    name: str
    role: str
    group: str
    first_chapter: int
    description: str


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    kind: str
    status: Literal["confirmed", "inferred", "disputed"]
    first_chapter: int
    evidence: str


class GraphSnapshot(BaseModel):
    work_slug: str
    through_chapter: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_type: str
    title: str
    chapter: int
    status: str
    confidence: float
    evidence_count: int


class AnalysisJobRequest(BaseModel):
    edition_id: str
    tracks: list[Literal["reading", "truth"]] = Field(
        default_factory=lambda: ["reading", "truth"]
    )


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: str
    stages: list[str]
