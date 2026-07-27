from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class SourceChapter(BaseModel):
    number: int = Field(ge=1)
    title: str
    text: str
    source_locator: dict[str, Any] = Field(default_factory=dict)


class BookInput(BaseModel):
    work_id: str
    edition_id: str
    title: str
    author: str
    language: str = "zh-CN"
    chapters: list[SourceChapter] = Field(min_length=1)


class SourceCitation(BaseModel):
    chapter: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=500)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)
    locator: dict[str, Any] = Field(default_factory=dict)
    verified: bool = False


class EvidenceFinding(BaseModel):
    evidence_id: str = ""
    title: str
    summary: str
    source_type: str = "text"
    status: Literal["confirmed", "inferred", "disputed", "uncertain"] = "confirmed"
    citation: SourceCitation


class PersonFinding(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: str = ""
    description: str = ""
    first_chapter: int = Field(ge=1)
    citations: list[SourceCitation] = Field(default_factory=list)


class RelationFinding(BaseModel):
    source: str
    target: str
    label: str
    kind: str = "unknown"
    status: Literal["confirmed", "inferred", "disputed", "uncertain"] = "inferred"
    first_chapter: int = Field(ge=1)
    citations: list[SourceCitation] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    chapter: int = Field(ge=1)
    sequence: int = Field(default=1, ge=1)
    summary: str
    story_time: str = ""
    narrative_time: str = ""
    citations: list[SourceCitation] = Field(default_factory=list)


class ClaimFinding(BaseModel):
    statement: str
    kind: Literal["author_explicit", "analysis_inference", "open_question"]
    status: Literal["confirmed", "inferred", "disputed", "uncertain"] = "inferred"
    confidence: float = Field(default=0.5, ge=0, le=1)
    introduced_chapter: int = Field(ge=1)
    resolved_chapter: int | None = Field(default=None, ge=1)
    reasoning: list[str] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)


class ChapterAnalysis(BaseModel):
    chapter_number: int = Field(ge=1)
    chapter_title: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    people: list[PersonFinding] = Field(default_factory=list)
    relations: list[RelationFinding] = Field(default_factory=list)
    events: list[TimelineEvent] = Field(default_factory=list)
    evidence: list[EvidenceFinding] = Field(default_factory=list)
    claims: list[ClaimFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class PartSynthesis(BaseModel):
    chapter_numbers: list[int]
    summary: str
    core_ideas: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    character_arcs: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    mysteries: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    claims: list[ClaimFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class StructureSection(BaseModel):
    title: str
    chapters: list[int]
    purpose: str
    summary: str


class BookSynthesis(BaseModel):
    overview: str
    structure: list[StructureSection] = Field(default_factory=list)
    core_ideas: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    character_arcs: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    mysteries: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    claims: list[ClaimFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    action_insights: list[str] = Field(default_factory=list)


class ReconciliationResult(BaseModel):
    final_claims: list[ClaimFinding] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)


class ClaimMergeDecision(BaseModel):
    statement: str
    kind: Literal["author_explicit", "analysis_inference", "open_question"]
    status: Literal["confirmed", "inferred", "disputed", "uncertain"] = "inferred"
    confidence: float = Field(default=0.5, ge=0, le=1)
    introduced_chapter: int = Field(ge=1)
    resolved_chapter: int | None = Field(default=None, ge=1)
    reasoning: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)


class ClaimMergeResult(BaseModel):
    claims: list[ClaimMergeDecision] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class BookEditorial(BaseModel):
    overview: str
    structure: list[StructureSection] = Field(default_factory=list)
    core_ideas: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    character_arcs: list[str] = Field(default_factory=list)
    mysteries: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    action_insights: list[str] = Field(default_factory=list)


class BookStructureEditorial(BaseModel):
    overview: str
    structure: list[StructureSection] = Field(default_factory=list)


class BookInterpretationEditorial(BaseModel):
    core_ideas: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    character_arcs: list[str] = Field(default_factory=list)
    action_insights: list[str] = Field(default_factory=list)


class BookMysteryEditorial(BaseModel):
    mysteries: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class ClaimAuditDecision(BaseModel):
    claim_id: str
    verdict: Literal["supported", "unsupported", "uncertain"]


class ClaimAuditResult(BaseModel):
    decisions: list[ClaimAuditDecision] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)


class AnalysisCheckpoint(BaseModel):
    chapters: list[ChapterAnalysis] = Field(default_factory=list)
    parts: list[PartSynthesis] = Field(default_factory=list)
    claim_merge_batches: dict[str, ClaimMergeResult] = Field(default_factory=dict)
    book_claims: list[ClaimFinding] | None = None
    claim_contradictions: list[str] = Field(default_factory=list)
    claim_uncertainties: list[str] = Field(default_factory=list)
    editorial: BookEditorial | None = None
    editorial_split: bool = False
    editorial_structure: BookStructureEditorial | None = None
    editorial_interpretation: BookInterpretationEditorial | None = None
    editorial_mysteries: BookMysteryEditorial | None = None
    claim_audit_batches: dict[str, ClaimAuditResult] = Field(default_factory=dict)
    synthesis: BookSynthesis | None = None
    reconciliation: ReconciliationResult | None = None


class EvidenceAudit(BaseModel):
    total_citations: int = 0
    verified_citations: int = 0
    unverified_citations: int = 0
    coverage: float = Field(default=0, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class BookAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    work_id: str
    edition_id: str
    title: str
    author: str
    chapters: list[ChapterAnalysis]
    synthesis: BookSynthesis
    reconciliation: ReconciliationResult
    evidence_index: list[EvidenceFinding] = Field(default_factory=list)
    audit: EvidenceAudit


class AnalysisProgress(BaseModel):
    stage: str
    progress: int = Field(ge=0, le=100)
    detail: str = ""


ProgressCallback = Callable[[AnalysisProgress], None]
CheckpointCallback = Callable[[AnalysisCheckpoint], None]

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class ModelAdapter(Protocol):
    def generate(
        self,
        *,
        task: str,
        system: str,
        prompt: str,
        response_model: type[ResponseT],
        model: str,
        temperature: float = 0.1,
    ) -> ResponseT: ...
