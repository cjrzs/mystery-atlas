from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkSummary(BaseModel):
    slug: str
    title: str
    author: str
    region: str
    year: int
    tags: list[str]
    cases: int
    people: int
    clues: int
    analysis_progress: int = Field(ge=0, le=100)
    status: str


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
    tracks: list[Literal["reading", "truth"]] = ["reading", "truth"]


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: str
    stages: list[str]

