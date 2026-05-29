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
ResearchRoutingAction = Literal[
    "scope_refinement",
    "entity_resolution",
    "source_discovery",
    "evidence_extraction",
    "claim_verification",
    "stop",
]
ResearchRoutingSubtype = Literal[
    "query_refinement",
    "dimension_decomposition",
    "competitor_disambiguation",
    "source_type_search",
    "targeted_url_extract",
    "coverage_gap_search",
    "evidence_check",
    "budget_stop",
    "sufficient_stop",
    "no_viable_followup",
]
StageRole = Literal[
    "evidence_collection",
    "claim_verification",
]
StageOutputKind = Literal[
    "evidence_items",
    "claim_evidence_items",
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
    research_task_id: str
    dimension_id: str
    dimension_name: str
    title: str
    url: str
    source_type: EvidenceType
    published_at: str | None
    retrieved_at: str
    excerpt: str
    confidence: float


class EvidenceCollectionTask(TypedDict, total=False):
    id: str
    research_task_id: str
    research_brief_id: str
    branch_id: str
    parent_branch_id: str | None
    depth: int
    search_stage: str
    generated_from_gap: str
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    expected_source_types: list[str]
    topic: str
    expansion_reason: str
    competitor: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    parent_dimension_id: str
    target_urls: list[str]
    query: str


class EvidenceCollectionResult(TypedDict, total=False):
    task: EvidenceCollectionTask
    mode: str
    query: str
    context: Any
    evidence_items: list[EvidenceItem]
    costs: float


EvidenceReviewAction = Literal["accept", "retry", "expand"]
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
    coverage_assessment_id: str
    accepted: bool
    score: float
    findings: list[EvidenceReviewFinding]
    accepted_evidence_ids: list[str]
    rejected_evidence_ids: list[str]
    required_action: EvidenceReviewAction


BranchDriftRisk = Literal["low", "medium", "high"]
ClaimSupportStatus = Literal["supported", "weak", "contradicted", "unverifiable"]


class ResearchBranch(TypedDict, total=False):
    id: str
    research_brief_id: str
    parent_id: str | None
    parent_task_id: str | None
    parent_dimension_id: str
    depth: int
    path: list[str]
    competitor: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    topic: str
    query: str
    target_urls: list[str]
    search_stage: str
    generated_from_gap: str
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    expected_source_types: list[str]
    minimum_coverage: list[str]
    guiding_questions: list[str]
    evidence_ids: list[str]
    status: Literal["active", "expanded", "stopped"]
    expansion_reason: str


SearchStage = Literal["focused", "verification"]
CoverageNextAction = Literal[
    "ready_for_analysis",
    "collect_more",
    "refine_query",
    "split_dimension",
    "stop_with_limit",
]
class ResearchBrief(TypedDict, total=False):
    id: str
    branch_id: str
    competitor: str
    dimension_id: str
    dimension_name: str
    objective: str
    guiding_questions: list[str]
    expected_source_types: list[str]
    minimum_coverage: list[str]
    effort_level: Literal["low", "medium", "high"]
    source_policy: str
    stop_condition: str
    rationale: str


class ResearchTask(TypedDict, total=False):
    id: str
    brief_id: str
    parent_task_id: str | None
    branch_id: str
    competitor: str
    dimension_id: str
    dimension_name: str
    search_stage: SearchStage
    objective: str
    query: str
    target_urls: list[str]
    expected_source_types: list[str]
    generated_from_gap: str
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    reason: str
    drift_risk: BranchDriftRisk


class FollowUpTaskSpec(TypedDict, total=False):
    objective: str
    query: str
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    dimension_id: str
    dimension_name: str
    dimension_type: str
    parent_dimension_id: str
    target_urls: list[str]
    target_source_types: list[str]
    generated_from_gap: str
    reason: str
    search_stage: SearchStage


class ResearchRoutingDecision(TypedDict, total=False):
    action: ResearchRoutingAction
    subtype: ResearchRoutingSubtype
    rationale: str


class ResearchRoutingDecisionCandidate(TypedDict, total=False):
    action: ResearchRoutingAction
    subtype: ResearchRoutingSubtype
    score: float
    reasons: list[str]
    follow_up_task_specs: list[FollowUpTaskSpec]


class StageContract(TypedDict, total=False):
    search_stage: SearchStage
    stage_role: StageRole
    research_mode: str
    reviewer: str
    output_kind: StageOutputKind
    produces_evidence: bool
    state_sink: str
    evidence_sink: str


class CoverageAssessment(TypedDict, total=False):
    id: str
    stage_contract: StageContract
    branch_id: str
    brief_id: str
    research_task_ids: list[str]
    accepted_evidence_ids: list[str]
    rejected_evidence_ids: list[str]
    found_source_types: list[str]
    missing_source_types: list[str]
    covered_questions: list[str]
    missing_questions: list[str]
    contradictions: list[str]
    next_action: CoverageNextAction
    follow_up_task_specs: list[FollowUpTaskSpec]
    selected_follow_up_specs: list[FollowUpTaskSpec]
    decision_candidates: list[ResearchRoutingDecisionCandidate]
    arbitration: dict[str, Any]
    decision: ResearchRoutingDecision
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
    branch_id: str
    evidence_review_id: str
    claim: str
    competitors: list[str]
    evidence_ids: list[str]
    reasoning: str
    confidence: float


class ClaimSupportReview(TypedDict, total=False):
    id: str
    claim_id: str
    branch_id: str
    dimension: str
    support_status: ClaimSupportStatus
    evidence_ids: list[str]
    unsupported_phrases: list[str]
    required_follow_up_tasks: list[dict[str, Any]]
    reviewer_notes: str
    confidence: float


class AnalysisDimension(TypedDict, total=False):
    id: str
    name: str
    description: str
    priority: str
    guiding_questions: list[str]
    search_intent: str
    expected_source_types: list[str]
    minimum_coverage: list[str]
    risk_level: str
    expected_claim_types: list[str]
    rank: int


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
    "claim_support",
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
    branch_id: str | None = None
    evidence_review_id: str | None = None
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


class SchemaMessagePayload(StrictPayloadModel):
    knowledge_count: int = Field(ge=0)
    competitor_knowledge: list[CompetitorKnowledgePayload] = Field(default_factory=list)


class AnalysisMessagePayload(StrictPayloadModel):
    claim_count: int = Field(ge=0)
    claims: list[AnalysisClaimPayload] = Field(default_factory=list)


class ClaimSupportReviewPayload(StrictPayloadModel):
    id: str
    claim_id: str
    branch_id: str = ""
    dimension: str = ""
    support_status: ClaimSupportStatus
    evidence_ids: list[str] = Field(default_factory=list)
    unsupported_phrases: list[str] = Field(default_factory=list)
    required_follow_up_tasks: list[dict[str, Any]] = Field(default_factory=list)
    reviewer_notes: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class ClaimSupportMessagePayload(StrictPayloadModel):
    review_count: int = Field(ge=0)
    supported_count: int = Field(ge=0)
    weak_count: int = Field(ge=0)
    reviews: list[ClaimSupportReviewPayload] = Field(default_factory=list)


class ReportMessagePayload(StrictPayloadModel):
    report_length: int = Field(ge=0)


class PublishMessagePayload(StrictPayloadModel):
    markdown: str


AgentMessagePayload = (
    SchemaSelectionMessagePayload
    | EvidenceMessagePayload
    | SchemaMessagePayload
    | AnalysisMessagePayload
    | ClaimSupportMessagePayload
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
    research_branches: list[ResearchBranch]
    research_briefs: list[ResearchBrief]
    research_tasks: list[ResearchTask]
    coverage_assessments: list[CoverageAssessment]
    evidence_reviews: list[EvidenceReviewResult]
    file_context: FileContext
    evidence_items: list[EvidenceItem]
    competitor_knowledge: list[CompetitorKnowledge]
    analysis_claims: list[AnalysisClaim]
    claim_support_reviews: list[ClaimSupportReview]
    verification_task_queue: list[dict[str, Any]]
    verification_rounds: int
    analysis_dimensions: list[AnalysisDimension]
    research_artifacts: list[ResearchArtifact]
    report: str
    published_artifacts: dict[str, str]
    agent_events: list[AgentEvent]
