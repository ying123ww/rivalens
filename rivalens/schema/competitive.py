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
    "regulator_database",
    "financial_filing",
    "standards_body",
    "complaint_database",
    "incident_database",
    "case_study",
    "trust_center",
    "status_page",
    "benchmark",
    "analyst_report",
    "public_registry",
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


SOURCE_TYPE_PRIORITY: dict[str, int] = {
    "regulator_database": 1,
    "public_registry": 1,
    "standards_body": 1,
    "financial_filing": 1,
    "complaint_database": 1,
    "incident_database": 1,
    "pricing_page": 2,
    "docs": 2,
    "trust_center": 2,
    "status_page": 2,
    "benchmark": 2,
    "official_site": 3,
    "case_study": 3,
    "analyst_report": 3,
    "marketplace": 4,
    "review": 5,
    "news": 5,
    "blog": 6,
    "job_posting": 6,
    "social": 7,
    "other": 8,
}


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
    source_priority: int
    is_primary_source: bool
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
    source_hints: list[str]
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
    source_hints: list[str]
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
    source_hints: list[str]
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
    source_hints: list[str]
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


class IndustryProfileDirection(TypedDict, total=False):
    direction_id: str
    name: str
    reason: str
    source_hints: list[str]
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
    origin: Literal["industry_template", "planner_suggested", "user_requested"]


class IndustryDirectionPlan(TypedDict, total=False):
    id: str
    detected_industry: str
    industry: IndustryCandidate
    candidate_industries: list[IndustryCandidate]
    detected_competitors: list[str]
    suggested_competitors: list[str]
    suggested_directions: list[AnalysisDirection]
    default_directions: list[AnalysisDirection]
    planner_added_directions: list[AnalysisDirection]
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
    source_hints: list[str]
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


class IndustryProfileDirectionPayload(StrictPayloadModel):
    direction_id: str
    name: str
    reason: str = ""
    source_hints: list[str] = Field(default_factory=list)
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
    origin: Literal["industry_template", "planner_suggested", "user_requested"]


class IndustryDirectionPlanPayload(StrictPayloadModel):
    id: str
    detected_industry: str = ""
    industry: IndustryCandidatePayload
    candidate_industries: list[IndustryCandidatePayload] = Field(default_factory=list)
    detected_competitors: list[str] = Field(default_factory=list)
    suggested_competitors: list[str] = Field(default_factory=list)
    suggested_directions: list[AnalysisDirectionPayload] = Field(default_factory=list)
    default_directions: list[AnalysisDirectionPayload] = Field(default_factory=list)
    planner_added_directions: list[AnalysisDirectionPayload] = Field(
        default_factory=list,
    )
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
    source_hints: list[str] = Field(default_factory=list)
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
    industry_direction_plan: IndustryDirectionPlanPayload | None = None


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
    pdf: str = ""
    docx: str = ""
    html: str = ""


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


# ── Direction-level research result (universal) ──

DirectionResultStatus = Literal["pending", "partial", "complete", "failed"]


class DirectionFinding(TypedDict, total=False):
    """A single factual finding within a direction."""

    id: str
    summary: str
    detail: str
    data_point: str | None
    source_url: str | None
    source_type: EvidenceType
    evidence_ids: list[str]
    confidence: float


class DirectionResult(TypedDict, total=False):
    """Universal structure for storing the research result of one direction
    for one competitor.  Every direction (pricing, safety, UX, ...) produces
    the same shape so downstream agents can consume results uniformly."""

    id: str
    direction_id: str
    direction_name: str
    competitor: str
    status: DirectionResultStatus
    findings: list[DirectionFinding]
    summary: str
    gaps: list[str]
    evidence_ids: list[str]
    evidence_count: int
    confidence: float
    collected_at: str
    collector_task_ids: list[str]


class DirectionFindingPayload(StrictPayloadModel):
    """Pydantic-validated version of DirectionFinding."""

    id: str
    summary: str
    detail: str = ""
    data_point: str | None = None
    source_url: str | None = None
    source_type: EvidenceType = "other"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class DirectionResultPayload(StrictPayloadModel):
    """Pydantic-validated version of DirectionResult.

    Used for agent-to-agent handoff: the CollectorAgent produces this
    after researching a direction, the PlanningAgent/QualityAgent
    validates it before merging into CompetitorKnowledge."""

    id: str
    direction_id: str
    direction_name: str = ""
    competitor: str
    status: DirectionResultStatus = "pending"
    findings: list[DirectionFindingPayload] = Field(default_factory=list)
    summary: str = ""
    gaps: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    collected_at: str = ""
    collector_task_ids: list[str] = Field(default_factory=list)



def build_direction_result(
    *,
    direction_id: str,
    competitor: str,
    findings: list[dict[str, Any]] | None = None,
    summary: str = "",
    gaps: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    status: DirectionResultStatus = "complete",
    confidence: float = 0.0,
    direction_name: str = "",
    collected_at: str = "",
    collector_task_ids: list[str] | None = None,
) -> DirectionResult:
    """Create and validate a DirectionResult in one call.

    Raises ``pydantic.ValidationError`` if the data is malformed.
    Returns a plain dict (TypedDict) safe for JSON serialization.
    """
    from datetime import datetime, timezone

    _findings = findings or []
    _evidence_ids = evidence_ids or []
    _gaps = gaps or []
    _collector_task_ids = collector_task_ids or []
    _collected_at = collected_at or datetime.now(timezone.utc).isoformat()
    _result_id = f"dr_{direction_id}_{competitor}_{_collected_at}"

    payload = DirectionResultPayload(
        id=_result_id,
        direction_id=direction_id,
        direction_name=direction_name,
        competitor=competitor,
        status=status,
        findings=[DirectionFindingPayload(**f) for f in _findings],
        summary=summary,
        gaps=_gaps,
        evidence_ids=_evidence_ids,
        evidence_count=len(_evidence_ids),
        confidence=confidence,
        collected_at=_collected_at,
        collector_task_ids=_collector_task_ids,
    )
    return payload.model_dump()


class CompetitorAnalysisState(TypedDict, total=False):
    task: dict[str, Any]
    messages: list[AgentMessage]
    competitors: list[Competitor]
    active_knowledge_schema: ActiveKnowledgeSchema
    industry_direction_plan: IndustryDirectionPlan
    research_branches: list[ResearchBranch]
    research_briefs: list[ResearchBrief]
    research_tasks: list[ResearchTask]
    coverage_assessments: list[CoverageAssessment]
    evidence_reviews: list[EvidenceReviewResult]
    file_context: FileContext
    evidence_items: list[EvidenceItem]
    direction_results: list[DirectionResult]
    competitor_knowledge: list[CompetitorKnowledge]
    analysis_claims: list[AnalysisClaim]
    claim_support_reviews: list[ClaimSupportReview]
    verification_task_queue: list[dict[str, Any]]
    verification_rounds: int
    research_artifacts: list[ResearchArtifact]
    report: str
    published_artifacts: dict[str, str]
    agent_events: list[AgentEvent]
