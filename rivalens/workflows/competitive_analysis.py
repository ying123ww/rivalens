"""Main DAG for the Rivalens competitor-analysis workflow."""

import os
from typing import Any

from langgraph.graph import END, StateGraph

from rivalens.agents import (
    AnalysisAgent,
    ClaimSupportReviewer,
    CollectionAgent,
    KnowledgeStructuringAgent,
    PlanningAgent,
    PublisherAgent,
    ReportWriterAgent,
)
from rivalens.research import ResearchEngineEvidenceCollector
from rivalens.schema import CompetitorAnalysisState


def route_after_claim_support(state: CompetitorAnalysisState) -> str:
    """Route weak claims through one claim-driven verification pass."""
    if state.get("verification_task_queue") and not state.get("verification_rounds", 0):
        return "needs_verification"
    return "supported_enough"


def _int_budget(
    value: Any,
    env_name: str,
    default: int,
    minimum: int = 0,
) -> int:
    raw_value = value if value is not None else os.getenv(env_name)
    if raw_value in (None, ""):
        return default
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def build_competitive_analysis_graph(
    websocket=None,
    stream_output=None,
    tone=None,
    headers: dict[str, Any] | None = None,
    max_branch_depth: int | None = None,
    max_expansion_branches: int | None = None,
    max_root_branch_hard_limit: int | None = None,
) -> Any:
    """Build the traceable multi-agent competitor-analysis DAG."""
    evidence_collector = ResearchEngineEvidenceCollector(websocket, stream_output, tone=tone, headers=headers)
    planner = PlanningAgent()
    collection = CollectionAgent(
        evidence_collector,
        max_branch_depth=_int_budget(
            max_branch_depth,
            "RIVALENS_MAX_BRANCH_DEPTH",
            1,
        ),
        max_expansion_branches=_int_budget(
            max_expansion_branches,
            "RIVALENS_MAX_EXPANSION_BRANCHES",
            24,
        ),
        max_root_branch_hard_limit=_int_budget(
            max_root_branch_hard_limit,
            "RIVALENS_MAX_ROOT_BRANCHES",
            80,
            minimum=1,
        ),
    )
    knowledge_structuring = KnowledgeStructuringAgent()
    analysis = AnalysisAgent()
    claim_support = ClaimSupportReviewer()
    writer = ReportWriterAgent()
    publisher = PublisherAgent()

    workflow = StateGraph(CompetitorAnalysisState)
    workflow.add_node("scope_planner", planner.run)
    workflow.add_node("source_collection", collection.run)
    workflow.add_node("dimension_analysis", analysis.run)
    workflow.add_node("claim_support_review", claim_support.review)
    workflow.add_node("knowledge_structuring", knowledge_structuring.run)
    workflow.add_node("report_writer", writer.run)
    workflow.add_node("publisher", publisher.run)

    workflow.set_entry_point("scope_planner")
    workflow.add_edge("scope_planner", "source_collection")
    workflow.add_edge("source_collection", "knowledge_structuring")
    workflow.add_edge("knowledge_structuring", "dimension_analysis")
    workflow.add_edge("dimension_analysis", "claim_support_review")
    workflow.add_conditional_edges(
        "claim_support_review",
        route_after_claim_support,
        {
            "needs_verification": "source_collection",
            "supported_enough": "report_writer",
        },
    )
    workflow.add_edge("report_writer", "publisher")
    workflow.add_edge("publisher", END)

    return workflow


async def run_competitive_analysis_task(
    query: str,
    websocket=None,
    stream_output=None,
    tone=None,
    headers: dict[str, Any] | None = None,
    **kwargs,
) -> CompetitorAnalysisState:
    """Run Rivalens as the primary workflow entry point.

    The signature matches backend callers while keeping Rivalens as the only
    active workflow.
    """
    task = {
        "query": query,
        "competitors": kwargs.get("competitors", []),
        "files": kwargs.get("files", kwargs.get("file_paths", [])),
        "attachments": kwargs.get("attachments", []),
        "industry_direction_plan": kwargs.get("industry_direction_plan"),
        "custom_analysis_directions": kwargs.get("custom_analysis_directions", []),
        "industry_directions_confirmed": kwargs.get(
            "industry_directions_confirmed",
            False,
        ),
        "deep_research": kwargs.get("deep_research", False),
        "verbose": kwargs.get("verbose", True),
    }
    graph = build_competitive_analysis_graph(
        websocket,
        stream_output,
        tone,
        headers,
        max_branch_depth=kwargs.get("max_branch_depth"),
        max_expansion_branches=kwargs.get("max_expansion_branches"),
        max_root_branch_hard_limit=kwargs.get("max_root_branch_hard_limit"),
    ).compile()
    return await graph.ainvoke({"task": task})
