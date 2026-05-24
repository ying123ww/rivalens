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


class IndustryCandidate(TypedDict, total=False):
    industry_id: str
    name: str
    confidence: float
    signals: list[str]


class SchemaExtension(TypedDict, total=False):
    id: str
    name: str
    description: str
    origin: Literal["core", "schema_registry", "evidence_inferred", "user_requested"]
    evidence_ids: list[str]
    confidence: float
    approved: bool


class ActiveKnowledgeSchema(TypedDict, total=False):
    id: str
    version: str
    core_fields: list[str]
    selected_industry: IndustryCandidate
    candidate_industries: list[IndustryCandidate]
    industry_extensions: list[SchemaExtension]
    candidate_extensions: list[SchemaExtension]
    rationale: str


class FeatureNode(TypedDict, total=False):
    id: str
    category: str
    name: str
    description: str
    availability: str
    evidence_ids: list[str]
    confidence: float


class PricingPlan(TypedDict, total=False):
    id: str
    name: str
    billing_unit: str
    price: float | None
    currency: str | None
    pricing_visibility: str
    included_features: list[str]
    evidence_ids: list[str]
    confidence: float


class PricingModel(TypedDict, total=False):
    plans: list[PricingPlan]
    notes: str
    evidence_ids: list[str]
    confidence: float


class UserPersona(TypedDict, total=False):
    id: str
    segment: str
    needs: list[str]
    jobs_to_be_done: list[str]
    buying_triggers: list[str]
    evidence_ids: list[str]
    confidence: float


class CompetitorKnowledge(TypedDict, total=False):
    id: str
    competitor: str
    active_schema_id: str
    feature_tree: list[FeatureNode]
    pricing_model: PricingModel
    user_personas: list[UserPersona]
    industry_extensions: dict[str, Any]
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
    "schema_selection",
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


class IndustryCandidatePayload(StrictPayloadModel):
    industry_id: str
    name: str
    confidence: float = Field(ge=0, le=1)
    signals: list[str] = Field(default_factory=list)


class SchemaExtensionPayload(StrictPayloadModel):
    id: str
    name: str
    description: str = ""
    origin: Literal["core", "schema_registry", "evidence_inferred", "user_requested"]
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    approved: bool = False


class ActiveKnowledgeSchemaPayloadModel(StrictPayloadModel):
    id: str
    version: str
    core_fields: list[str] = Field(default_factory=list)
    selected_industry: IndustryCandidatePayload
    candidate_industries: list[IndustryCandidatePayload] = Field(default_factory=list)
    industry_extensions: list[SchemaExtensionPayload] = Field(default_factory=list)
    candidate_extensions: list[SchemaExtensionPayload] = Field(default_factory=list)
    rationale: str = ""


class FeatureNodePayload(StrictPayloadModel):
    id: str
    category: str
    name: str
    description: str = ""
    availability: str = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class PricingPlanPayload(StrictPayloadModel):
    id: str
    name: str
    billing_unit: str = "unknown"
    price: float | None = None
    currency: str | None = None
    pricing_visibility: str = "unknown"
    included_features: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class PricingModelPayload(StrictPayloadModel):
    plans: list[PricingPlanPayload] = Field(default_factory=list)
    notes: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class UserPersonaPayload(StrictPayloadModel):
    id: str
    segment: str
    needs: list[str] = Field(default_factory=list)
    jobs_to_be_done: list[str] = Field(default_factory=list)
    buying_triggers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class CompetitorKnowledgePayload(StrictPayloadModel):
    id: str
    competitor: str
    active_schema_id: str
    feature_tree: list[FeatureNodePayload] = Field(default_factory=list)
    pricing_model: PricingModelPayload = Field(default_factory=PricingModelPayload)
    user_personas: list[UserPersonaPayload] = Field(default_factory=list)
    industry_extensions: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


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


class SchemaSelectionMessagePayload(StrictPayloadModel):
    active_schema: ActiveKnowledgeSchemaPayloadModel
    candidate_count: int = Field(ge=0)


class SchemaMessagePayload(StrictPayloadModel):
    knowledge_count: int = Field(ge=0)
    competitor_knowledge: list[CompetitorKnowledgePayload] = Field(default_factory=list)


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
    | SchemaSelectionMessagePayload
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
    active_knowledge_schema: ActiveKnowledgeSchema
    evidence_items: list[EvidenceItem]
    competitor_knowledge: list[CompetitorKnowledge]
    analysis_claims: list[AnalysisClaim]
    quality_findings: list[QualityFinding]
    research_artifacts: list[ResearchArtifact]
    revision_notes: list[str]
    report: str
    published_artifacts: dict[str, str]
    agent_events: list[AgentEvent]
