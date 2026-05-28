"""Competitor-analysis specialist agents."""

__all__ = [
    "AnalysisAgent",
    "BranchReviewAgent",
    "CollectionAgent",
    "EvidenceQualityReviewer",
    "IndustryDirectionSkill",
    "KnowledgeStructuringAgent",
    "PlanningAgent",
    "ReportWriterAgent",
    "PublisherAgent",
]


def __getattr__(name: str):
    if name == "AnalysisAgent":
        from .analysis import AnalysisAgent

        return AnalysisAgent
    if name == "BranchReviewAgent":
        from .branch_review import BranchReviewAgent

        return BranchReviewAgent
    if name == "CollectionAgent":
        from .collection import CollectionAgent

        return CollectionAgent
    if name == "EvidenceQualityReviewer":
        from .evidence_review import EvidenceQualityReviewer

        return EvidenceQualityReviewer
    if name == "IndustryDirectionSkill":
        from .industry_direction import IndustryDirectionSkill

        return IndustryDirectionSkill
    if name == "KnowledgeStructuringAgent":
        from .knowledge_structuring import KnowledgeStructuringAgent

        return KnowledgeStructuringAgent
    if name == "PlanningAgent":
        from .planning import PlanningAgent

        return PlanningAgent
    if name == "ReportWriterAgent":
        from .writing import ReportWriterAgent

        return ReportWriterAgent
    if name == "PublisherAgent":
        from .publishing import PublisherAgent

        return PublisherAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
