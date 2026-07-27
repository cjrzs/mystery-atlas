from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .analysis_errors import public_analysis_error


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


class ReaderPreferences(BaseModel):
    font_size: int = Field(default=17, ge=14, le=22)
    line_height: float = Field(default=1.9, ge=1.5, le=2.4)
    content_width: int = Field(default=720, ge=520, le=900)
    theme: Literal["light", "sepia", "dark"] = "sepia"


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
    detected_tags: list[str] = Field(default_factory=list)
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
    visibility: Literal["private", "public"]
    rights_confirmed: bool = False


class ReaderBlock(BaseModel):
    type: Literal["paragraph", "heading", "quote", "divider", "pre"]
    text: str = ""


class ReaderChapter(BaseModel):
    number: int
    title: str
    text: str
    characters: int
    blocks: list[ReaderBlock] = Field(default_factory=list)


class ReaderResponse(BaseModel):
    work_id: str
    work_slug: str
    work_title: str
    author: str
    edition_id: str
    edition_title: str
    language: str
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
    tags: list[str] = Field(default_factory=list)
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


class WorkbenchTimelineEvent(BaseModel):
    chapter: int = Field(ge=1)
    sequence: int = Field(default=1, ge=1)
    summary: str
    story_time: str = ""
    narrative_time: str = ""


class WorkbenchChapterSnapshot(BaseModel):
    chapter: int = Field(ge=1)
    summary: str


class WorkbenchEvidence(BaseModel):
    id: str
    title: str
    summary: str
    source_type: str
    status: str
    first_chapter: int = Field(ge=1)
    excerpt: str = ""


class WorkbenchAnalysisResponse(BaseModel):
    work_id: str
    work_slug: str
    through_chapter: int
    status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    error: str | None = None
    graph: GraphSnapshot
    timeline: list[WorkbenchTimelineEvent]
    chapters: list[WorkbenchChapterSnapshot]
    evidence: list[WorkbenchEvidence]

    @field_validator("error", mode="before")
    @classmethod
    def hide_internal_analysis_error(cls, value: object) -> str | None:
        return public_analysis_error(value)


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
    tracks: list[Literal["full", "reading", "truth"]] = Field(
        default_factory=lambda: ["full"],
        min_length=1,
    )


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: str
    stages: list[str]


class AnalysisJobDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_id: str
    edition_id: str
    track: str
    stage: str
    status: str
    progress: int = Field(ge=0, le=100)
    error: str | None
    result_summary: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("error", mode="before")
    @classmethod
    def hide_internal_analysis_error(cls, value: object) -> str | None:
        return public_analysis_error(value)
