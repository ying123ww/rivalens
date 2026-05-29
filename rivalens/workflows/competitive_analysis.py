"""Main DAG for the Rivalens competitor-analysis workflow."""

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


def build_competitive_analysis_graph(
    websocket=None,
    stream_output=None,
    tone=None,
    headers: dict[str, Any] | None = None,
) -> Any:
    """Build the traceable multi-agent competitor-analysis DAG."""
    evidence_collector = ResearchEngineEvidenceCollector(websocket, stream_output, tone=tone, headers=headers)
    planner = PlanningAgent()
    collection = CollectionAgent(evidence_collector)
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
        "verbose": kwargs.get("verbose", True),
    }
    graph = build_competitive_analysis_graph(websocket, stream_output, tone, headers).compile()
    return await graph.ainvoke({"task": task})
