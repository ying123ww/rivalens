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
ClaimRiskLevel = Literal["low", "medium", "high"]
ResearchRoutingAction = Literal[
    "scope_refinement",
    "entity_resolution",
    "source_discovery",
    "evidence_extraction",
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
]
StageOutputKind = Literal[
    "evidence_items",
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
    evidence_ids: list[str]
    confidence: float


class EvidenceItem(TypedDict, total=False):
    id: str
    competitor: str
    branch_id: str
    parent_branch_id: str | None
    collection_task_id: str
    research_task_id: str
    analysis_dimension_id: str
    schema_field_ids: list[str]
    report_section_id: str
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
    success_criterion_ids: list[str]


class SuccessCriterion(TypedDict, total=False):
    id: str
    description: str
    evidence_ids: list[str]
    status: Literal["satisfied", "partial", "missing"]


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
    target_source_types: list[str]
    expected_claim_types: list[str]
    topic: str
    expansion_reason: str
    competitor: str
    analysis_dimension_id: str
    schema_field_ids: list[str]
    report_section_id: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    parent_dimension_id: str
    target_urls: list[str]
    query: str
    research_goal: str
    search_queries: list[str]
    success_criteria: list[SuccessCriterion]
    task_context: str
    file_rag_context: str


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
    "competitor_mismatch",
    "dimension_mismatch",
    "low_quality_text",
    "no_success_criterion_match",
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
    criterion_matches: list[dict[str, Any]]
    required_action: EvidenceReviewAction


BranchDriftRisk = Literal["low", "medium", "high"]
ClaimSupportStatus = Literal["supported", "weak", "contradicted", "unverifiable"]
ClaimSupportRecommendedAction = Literal[
    "accept",
    "revise",
    "suppress",
    "evidence_gap",
]


class ResearchBranch(TypedDict, total=False):
    id: str
    research_brief_id: str
    parent_id: str | None
    parent_task_id: str | None
    parent_dimension_id: str
    depth: int
    path: list[str]
    competitor: str
    analysis_dimension_id: str
    schema_field_ids: list[str]
    report_section_id: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    topic: str
    query: str
    research_goal: str
    search_queries: list[str]
    success_criteria: list[SuccessCriterion]
    task_context: str
    target_urls: list[str]
    search_stage: str
    generated_from_gap: str
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    source_hints: list[str]
    target_source_types: list[str]
    minimum_coverage: list[str]
    expected_claim_types: list[str]
    guiding_questions: list[str]
    evidence_ids: list[str]
    status: Literal["active", "expanded", "stopped"]
    coverage_state_id: str
    coverage_status: str
    expansion_reason: str


SearchStage = Literal["focused"]
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
    analysis_dimension_id: str
    schema_field_ids: list[str]
    report_section_id: str
    dimension_id: str
    dimension_name: str
    objective: str
    success_criteria: list[SuccessCriterion]
    guiding_questions: list[str]
    source_hints: list[str]
    minimum_coverage: list[str]
    expected_claim_types: list[str]
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
    analysis_dimension_id: str
    schema_field_ids: list[str]
    report_section_id: str
    dimension_id: str
    dimension_name: str
    search_stage: SearchStage
    objective: str
    query: str
    research_goal: str
    search_queries: list[str]
    success_criteria: list[SuccessCriterion]
    task_context: str
    target_urls: list[str]
    source_hints: list[str]
    target_source_types: list[str]
    expected_claim_types: list[str]
    generated_from_gap: str
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    reason: str
    drift_risk: BranchDriftRisk


class FollowUpTaskSpec(TypedDict, total=False):
    objective: str
    query: str
    success_criteria: list[SuccessCriterion]
    decision_action: ResearchRoutingAction
    decision_subtype: ResearchRoutingSubtype
    analysis_dimension_id: str
    schema_field_ids: list[str]
    report_section_id: str
    dimension_id: str
    dimension_name: str
    dimension_type: str
    parent_dimension_id: str
    target_urls: list[str]
    target_source_types: list[str]
    expected_claim_types: list[str]
    generated_from_gap: str
    triggering_finding_codes: list[str]
    baseline_accepted_count: int
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


class SourceCoverageGap(TypedDict, total=False):
    gap_type: Literal["source_coverage"]
    code: str
    query_focus: str
    target_source_types: list[str]
    accepted_count: int
    minimum_count: int
    blocking: bool
    criterion_id: str
    criterion_description: str
    success_criteria: list[SuccessCriterion]
    reason: str


class CoverageAssessment(TypedDict, total=False):
    id: str
    stage_contract: StageContract
    branch_id: str
    brief_id: str
    research_task_ids: list[str]
    accepted_evidence_ids: list[str]
    rejected_evidence_ids: list[str]
    found_source_types: list[str]
    source_type_gaps: list[SourceCoverageGap]
    source_coverage_gaps: list[SourceCoverageGap]
    quality_gap_codes: list[str]
    covered_questions: list[str]
    missing_questions: list[str]
    satisfied_criteria: list[SuccessCriterion]
    partial_criteria: list[SuccessCriterion]
    missing_criteria: list[SuccessCriterion]
    criterion_matches: list[dict[str, Any]]
    contradictions: list[str]
    next_action: CoverageNextAction
    follow_up_task_specs: list[FollowUpTaskSpec]
    selected_follow_up_specs: list[FollowUpTaskSpec]
    decision_candidates: list[ResearchRoutingDecisionCandidate]
    arbitration: dict[str, Any]
    decision: ResearchRoutingDecision
    confidence: float


CoverageGapStatus = Literal["open", "resolved", "blocked"]
BranchCoverageStatus = Literal["ready_for_analysis", "needs_followup", "blocked"]


class BranchCoverageGap(TypedDict, total=False):
    id: str
    gap_type: str
    code: str
    criterion_id: str
    description: str
    status: CoverageGapStatus
    root_branch_id: str
    opened_by_branch_id: str
    opened_by_coverage_assessment_id: str
    target_source_types: list[str]
    baseline_accepted_count: int
    blocking: bool
    resolved_by_branch_ids: list[str]
    resolved_by_evidence_ids: list[str]
    reason: str


class BranchCoverageState(TypedDict, total=False):
    id: str
    root_branch_id: str
    branch_ids: list[str]
    competitor: str
    analysis_dimension_id: str
    dimension_id: str
    dimension_name: str
    status: BranchCoverageStatus
    accepted_evidence_ids: list[str]
    found_source_types: list[str]
    success_criteria: list[SuccessCriterion]
    coverage_gaps: list[BranchCoverageGap]
    open_gap_codes: list[str]
    resolved_gap_codes: list[str]
    blocked_gap_codes: list[str]


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
    origin: Literal[
        "industry_template",
        "planner_suggested",
        "user_requested",
        "llm_fallback",
    ]


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
    selection_method: str
    fallback_reason: str
    fallback_model: str
    user_confirmed: bool
    created_at: str


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
    feature_tree: list[FeatureNode]
    pricing_model: PricingModel
    user_personas: list[UserPersona]
    evidence_ids: list[str]
    confidence: float


class AnalysisClaim(TypedDict, total=False):
    id: str
    analysis_dimension_id: str
    knowledge_fact_ids: list[str]
    report_section_id: str
    claim_source: str
    claim_type: str
    claim_risk_level: ClaimRiskLevel
    normalized_key: str
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
    analysis_dimension_id: str
    report_section_id: str
    support_status: ClaimSupportStatus
    recommended_action: ClaimSupportRecommendedAction
    claim_risk_level: ClaimRiskLevel
    evidence_ids: list[str]
    knowledge_fact_ids: list[str]
    unsupported_phrases: list[str]
    required_follow_up_tasks: list[dict[str, Any]]
    suggested_revision: str
    reviewer_notes: str
    confidence: float


class ReportSectionTarget(TypedDict, total=False):
    section_id: str
    role: Literal["primary", "secondary"]
    reason: str


class AnalysisDimension(TypedDict, total=False):
    id: str
    name: str
    description: str
    objective: str
    priority: str
    source_hints: list[str]
    success_criteria: list[SuccessCriterion]
    guiding_questions: list[str]
    search_intent: str
    minimum_coverage: list[str]
    expected_claim_types: list[str]
    origin: str
    required: bool
    direction_id: str
    schema_field_ids: list[str]
    report_targets: list[ReportSectionTarget]
    report_order: int
    rank: int


class KnowledgeFact(TypedDict, total=False):
    id: str
    competitor: str
    analysis_dimension_id: str
    schema_field_id: str
    fact_type: str
    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, Any]
    normalized_key: str
    statement: str
    value: dict[str, Any]
    evidence_ids: list[str]
    report_section_id: str
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
    "research_plan",
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
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


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
    origin: Literal[
        "industry_template",
        "planner_suggested",
        "user_requested",
        "llm_fallback",
    ]


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
    selection_method: str = "rule_template"
    fallback_reason: str = ""
    fallback_model: str = ""
    user_confirmed: bool = False
    created_at: str


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
    feature_tree: list[FeatureNodePayload] = Field(default_factory=list)
    pricing_model: PricingModelPayload = Field(default_factory=PricingModelPayload)
    user_personas: list[UserPersonaPayload] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ReportSectionTargetPayload(StrictPayloadModel):
    section_id: str
    role: Literal["primary", "secondary"] = "primary"
    reason: str = ""


class AnalysisDimensionPayload(StrictPayloadModel):
    id: str
    name: str
    description: str = ""
    objective: str = ""
    priority: str = "P1"
    source_hints: list[str] = Field(default_factory=list)
    success_criteria: list[dict[str, Any]] = Field(default_factory=list)
    guiding_questions: list[str] = Field(default_factory=list)
    search_intent: str = ""
    minimum_coverage: list[str] = Field(default_factory=list)
    expected_claim_types: list[str] = Field(default_factory=list)
    origin: str = ""
    required: bool = True
    direction_id: str = ""
    schema_field_ids: list[str] = Field(default_factory=list)
    report_targets: list[ReportSectionTargetPayload] = Field(default_factory=list)
    report_order: int = 0
    rank: int = 0


class KnowledgeFactPayload(StrictPayloadModel):
    id: str
    competitor: str = ""
    analysis_dimension_id: str = ""
    schema_field_id: str = ""
    fact_type: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    normalized_key: str = ""
    statement: str
    value: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    report_section_id: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class AnalysisClaimPayload(StrictPayloadModel):
    id: str
    analysis_dimension_id: str = ""
    knowledge_fact_ids: list[str] = Field(default_factory=list)
    report_section_id: str = ""
    claim_source: str = ""
    claim_type: str = ""
    claim_risk_level: ClaimRiskLevel = "medium"
    normalized_key: str = ""
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


class ResearchPlanMessagePayload(StrictPayloadModel):
    candidate_count: int = Field(ge=0)
    industry_direction_plan: IndustryDirectionPlanPayload
    analysis_dimensions: list[AnalysisDimensionPayload] = Field(default_factory=list)


class SchemaMessagePayload(StrictPayloadModel):
    knowledge_count: int = Field(ge=0)
    competitor_knowledge: list[CompetitorKnowledgePayload] = Field(default_factory=list)
    knowledge_facts: list[KnowledgeFactPayload] = Field(default_factory=list)


class AnalysisMessagePayload(StrictPayloadModel):
    claim_count: int = Field(ge=0)
    claims: list[AnalysisClaimPayload] = Field(default_factory=list)


class ClaimSupportReviewPayload(StrictPayloadModel):
    id: str
    claim_id: str
    branch_id: str = ""
    analysis_dimension_id: str = ""
    report_section_id: str = ""
    support_status: ClaimSupportStatus
    recommended_action: ClaimSupportRecommendedAction = "revise"
    claim_risk_level: ClaimRiskLevel = "medium"
    evidence_ids: list[str] = Field(default_factory=list)
    knowledge_fact_ids: list[str] = Field(default_factory=list)
    unsupported_phrases: list[str] = Field(default_factory=list)
    required_follow_up_tasks: list[dict[str, Any]] = Field(default_factory=list)
    suggested_revision: str = ""
    reviewer_notes: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class ClaimSupportMessagePayload(StrictPayloadModel):
    review_count: int = Field(ge=0)
    supported_count: int = Field(ge=0)
    weak_count: int = Field(ge=0)
    contradicted_count: int = Field(default=0, ge=0)
    unverifiable_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    revision_count: int = Field(default=0, ge=0)
    suppressed_count: int = Field(default=0, ge=0)
    reviews: list[ClaimSupportReviewPayload] = Field(default_factory=list)


class ReportMessagePayload(StrictPayloadModel):
    report_length: int = Field(ge=0)


class PublishMessagePayload(StrictPayloadModel):
    markdown: str
    pdf: str = ""
    docx: str = ""
    html: str = ""


AgentMessagePayload = (
    ResearchPlanMessagePayload
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
    industry_direction_plan: IndustryDirectionPlan
    analysis_dimensions: list[AnalysisDimension]
    research_branches: list[ResearchBranch]
    research_briefs: list[ResearchBrief]
    research_tasks: list[ResearchTask]
    coverage_assessments: list[CoverageAssessment]
    branch_coverage_states: list[BranchCoverageState]
    evidence_reviews: list[EvidenceReviewResult]
    file_context: FileContext
    evidence_items: list[EvidenceItem]
    direction_results: list[DirectionResult]
    knowledge_facts: list[KnowledgeFact]
    competitor_knowledge: list[CompetitorKnowledge]
    analysis_claims: list[AnalysisClaim]
    claim_support_reviews: list[ClaimSupportReview]
    research_artifacts: list[ResearchArtifact]
    report: str
    published_artifacts: dict[str, str]
    agent_events: list[AgentEvent]
