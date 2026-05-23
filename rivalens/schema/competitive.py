"""Core schema for traceable competitor analysis workflows."""

from typing import Any, Literal, TypedDict


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
