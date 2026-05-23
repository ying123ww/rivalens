"""Core schema for traceable competitor analysis workflows."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


EvidenceType = Literal[
    "official_site",
    "pricing_page",
    "docs",
    "blog",
    "news",
    "review",
    "marketplace",
    "social",
    "job_posting",
    "other",
]


class Competitor(TypedDict, total=False):
    name: str
    product: str
    website: str
    category: str
    notes: str


class EvidenceItem(TypedDict, total=False):
    id: str
    competitor: str
    title: str
    url: str
    source_type: EvidenceType
    published_at: str | None
    retrieved_at: str
    excerpt: str
    summary: str
    confidence: float


class ProductFact(TypedDict, total=False):
    id: str
    competitor: str
    dimension: str
    value: str
    evidence_ids: list[str]
    confidence: float


class AnalysisClaim(TypedDict, total=False):
    id: str
    dimension: str
    claim: str
    competitors: list[str]
    evidence_ids: list[str]
    reasoning: str
    confidence: float


class QualityFinding(TypedDict, total=False):
    id: str
    severity: Literal["low", "medium", "high"]
    target_id: str
    message: str
    recommendation: str


class AgentEvent(TypedDict, total=False):
    agent: str
    action: str
    input: dict[str, Any]
    output: dict[str, Any]
    started_at: str
    completed_at: str
    cost: float


AgentMessageType = Literal[
    "plan",
    "evidence",
    "schema",
    "analysis",
    "review",
    "revision",
    "report",
    "publish",
]


class StrictPayloadModel(BaseModel):
    """Base class for JSON payloads exchanged between agents."""

    model_config = ConfigDict(extra="forbid")


class CompetitorPayload(StrictPayloadModel):
    name: str
    product: str | None = None
    website: str | None = None
    category: str | None = None
    notes: str | None = None


class ProductFactPayload(StrictPayloadModel):
    id: str
    competitor: str = ""
    dimension: str
    value: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class AnalysisClaimPayload(StrictPayloadModel):
    id: str
    dimension: str
    claim: str
    competitors: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.5


class QualityFindingPayload(StrictPayloadModel):
    id: str
    severity: Literal["low", "medium", "high"]
    target_id: str
    message: str
    recommendation: str


class PlanMessagePayload(StrictPayloadModel):
    query: str
    competitors: list[CompetitorPayload] = Field(default_factory=list)
    suggested_outline: str = ""


class EvidenceMessagePayload(StrictPayloadModel):
    evidence_count: int = Field(ge=0)
    research_runs: int = Field(ge=0)


class SchemaMessagePayload(StrictPayloadModel):
    fact_count: int = Field(ge=0)
    facts: list[ProductFactPayload] = Field(default_factory=list)


class AnalysisMessagePayload(StrictPayloadModel):
    claim_count: int = Field(ge=0)
    claims: list[AnalysisClaimPayload] = Field(default_factory=list)


class ReviewMessagePayload(StrictPayloadModel):
    finding_count: int = Field(ge=0)
    findings: list[QualityFindingPayload] = Field(default_factory=list)
    accepted: bool


class RevisionMessagePayload(StrictPayloadModel):
    note: str
    claim_count: int = Field(ge=0)


class ReportMessagePayload(StrictPayloadModel):
    report_length: int = Field(ge=0)


class PublishMessagePayload(StrictPayloadModel):
    markdown: str


AgentMessagePayload = (
    PlanMessagePayload
    | EvidenceMessagePayload
    | SchemaMessagePayload
    | AnalysisMessagePayload
    | ReviewMessagePayload
    | RevisionMessagePayload
    | ReportMessagePayload
    | PublishMessagePayload
)


class AgentMessage(TypedDict, total=False):
    id: str
    sender: str
    receiver: str
    type: AgentMessageType
    payload: dict[str, Any]
    artifact_ids: list[str]
    evidence_ids: list[str]
    created_at: str


class ResearchArtifact(TypedDict, total=False):
    id: str
    agent: str
    mode: str
    query: str
    competitor: str
    report: str
    context: Any
    evidence_ids: list[str]
    costs: float


class CompetitorAnalysisState(TypedDict, total=False):
    task: dict[str, Any]
    messages: list[AgentMessage]
    competitors: list[Competitor]
    evidence_items: list[EvidenceItem]
    product_facts: list[ProductFact]
    analysis_claims: list[AnalysisClaim]
    quality_findings: list[QualityFinding]
    research_artifacts: list[ResearchArtifact]
    revision_notes: list[str]
    report: str
    published_artifacts: dict[str, str]
    agent_events: list[AgentEvent]
