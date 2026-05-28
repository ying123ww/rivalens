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
    branch_id: str
    parent_branch_id: str | None
    collection_task_id: str
    dimension_id: str
    dimension_name: str
    title: str
    url: str
    source_type: EvidenceType
    published_at: str | None
    retrieved_at: str
    excerpt: str
    summary: str
    confidence: float


class EvidenceCollectionTask(TypedDict, total=False):
    id: str
    branch_id: str
    parent_branch_id: str | None
    depth: int
    topic: str
    expansion_reason: str
    competitor: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    query: str


class EvidenceCollectionResult(TypedDict, total=False):
    task: EvidenceCollectionTask
    mode: str
    query: str
    context: Any
    evidence_items: list[EvidenceItem]
    costs: float


EvidenceReviewAction = Literal["accept", "retry", "expand", "fail"]
EvidenceReviewFindingCode = Literal[
    "no_evidence",
    "missing_source_url",
    "insufficient_source_count",
    "missing_official_source",
    "missing_pricing_page",
    "missing_docs_or_security_source",
    "missing_customer_or_review_source",
    "competitor_mismatch",
    "dimension_mismatch",
]


class EvidenceReviewFinding(TypedDict, total=False):
    id: str
    severity: Literal["low", "medium", "high"]
    code: EvidenceReviewFindingCode
    evidence_id: str | None
    branch_id: str
    message: str
    recommendation: str


class EvidenceReviewResult(TypedDict, total=False):
    id: str
    branch_id: str
    collection_task_id: str
    accepted: bool
    score: float
    findings: list[EvidenceReviewFinding]
    accepted_evidence_ids: list[str]
    rejected_evidence_ids: list[str]
    required_action: EvidenceReviewAction


BranchDecisionType = Literal["expand", "stop", "retry", "fail", "merge", "redirect"]
BranchDriftRisk = Literal["low", "medium", "high"]


class ResearchBranch(TypedDict, total=False):
    id: str
    parent_id: str | None
    depth: int
    path: list[str]
    competitor: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    topic: str
    query: str
    evidence_ids: list[str]
    status: Literal["active", "expanded", "stopped", "failed"]
    expansion_reason: str
    review_decision: BranchDecisionType | None


class BranchReviewDecision(TypedDict, total=False):
    branch_id: str
    evidence_review_id: str
    decision: BranchDecisionType
    score: float
    reasons: list[str]
    evidence_gaps: list[str]
    next_topics: list[str]
    next_queries: list[str]
    drift_risk: BranchDriftRisk


class IndustryCandidate(TypedDict, total=False):
    industry_id: str
    name: str
    confidence: float
    signals: list[str]


class IndustryProfileDirection(TypedDict, total=False):
    direction_id: str
    name: str
    reason: str
    required: bool


class IndustryProfile(TypedDict, total=False):
    industry: str
    display_name: str
    aliases: list[str]
    known_competitors: list[str]
    default_directions: list[IndustryProfileDirection]


class AnalysisDirection(TypedDict, total=False):
    direction_id: str
    name: str
    reason: str
    description: str
    search_focus: str
    source_hints: list[str]
    required: bool
    origin: Literal["industry_template", "user_requested"]


class IndustryDirectionPlan(TypedDict, total=False):
    id: str
    detected_industry: str
    industry: IndustryCandidate
    candidate_industries: list[IndustryCandidate]
    suggested_directions: list[AnalysisDirection]
    default_directions: list[AnalysisDirection]
    user_added_directions: list[AnalysisDirection]
    final_directions: list[AnalysisDirection]
    final_analysis_plan: dict[str, Any]
    user_confirmed: bool
    created_at: str


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


class AgentEvent(TypedDict, total=False):
    agent: str
    action: str
    input: dict[str, Any]
    output: dict[str, Any]
    started_at: str
    completed_at: str
    cost: float


AgentMessageType = Literal[
    "schema_selection",
    "evidence",
    "schema",
    "analysis",
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


class IndustryProfileDirectionPayload(StrictPayloadModel):
    direction_id: str
    name: str
    reason: str = ""
    required: bool = True


class IndustryProfilePayload(StrictPayloadModel):
    industry: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    known_competitors: list[str] = Field(default_factory=list)
    default_directions: list[IndustryProfileDirectionPayload] = Field(
        default_factory=list,
    )


class AnalysisDirectionPayload(StrictPayloadModel):
    direction_id: str
    name: str
    reason: str = ""
    description: str = ""
    search_focus: str = ""
    source_hints: list[str] = Field(default_factory=list)
    required: bool = True
    origin: Literal["industry_template", "user_requested"]


class IndustryDirectionPlanPayload(StrictPayloadModel):
    id: str
    detected_industry: str = ""
    industry: IndustryCandidatePayload
    candidate_industries: list[IndustryCandidatePayload] = Field(default_factory=list)
    suggested_directions: list[AnalysisDirectionPayload] = Field(default_factory=list)
    default_directions: list[AnalysisDirectionPayload] = Field(default_factory=list)
    user_added_directions: list[AnalysisDirectionPayload] = Field(default_factory=list)
    final_directions: list[AnalysisDirectionPayload] = Field(default_factory=list)
    final_analysis_plan: dict[str, Any] = Field(default_factory=dict)
    user_confirmed: bool = False
    created_at: str


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


class EvidenceMessagePayload(StrictPayloadModel):
    evidence_count: int = Field(ge=0)
    accepted_evidence_count: int = Field(default=0, ge=0)
    rejected_evidence_count: int = Field(default=0, ge=0)
    evidence_review_count: int = Field(default=0, ge=0)
    research_runs: int = Field(ge=0)
    collection_task_count: int = Field(default=0, ge=0)
    failed_task_count: int = Field(default=0, ge=0)
    dimensions: list[str] = Field(default_factory=list)


class SchemaSelectionMessagePayload(StrictPayloadModel):
    active_schema: ActiveKnowledgeSchemaPayloadModel
    candidate_count: int = Field(ge=0)
    industry_direction_plan: IndustryDirectionPlanPayload | None = None


class SchemaMessagePayload(StrictPayloadModel):
    knowledge_count: int = Field(ge=0)
    competitor_knowledge: list[CompetitorKnowledgePayload] = Field(default_factory=list)


class AnalysisMessagePayload(StrictPayloadModel):
    claim_count: int = Field(ge=0)
    claims: list[AnalysisClaimPayload] = Field(default_factory=list)


class ReportMessagePayload(StrictPayloadModel):
    report_length: int = Field(ge=0)


class PublishMessagePayload(StrictPayloadModel):
    markdown: str


AgentMessagePayload = (
    SchemaSelectionMessagePayload
    | EvidenceMessagePayload
    | SchemaMessagePayload
    | AnalysisMessagePayload
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
    branch_id: str
    report: str
    context: Any
    evidence_ids: list[str]
    costs: float


class FileContext(TypedDict, total=False):
    sources: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    summary: str
    search_hints: list[str]


class CompetitorAnalysisState(TypedDict, total=False):
    task: dict[str, Any]
    messages: list[AgentMessage]
    competitors: list[Competitor]
    active_knowledge_schema: ActiveKnowledgeSchema
    industry_direction_plan: IndustryDirectionPlan
    research_branches: list[ResearchBranch]
    branch_review_decisions: list[BranchReviewDecision]
    evidence_reviews: list[EvidenceReviewResult]
    file_context: FileContext
    evidence_items: list[EvidenceItem]
    competitor_knowledge: list[CompetitorKnowledge]
    analysis_claims: list[AnalysisClaim]
    research_artifacts: list[ResearchArtifact]
    report: str
    published_artifacts: dict[str, str]
    agent_events: list[AgentEvent]
