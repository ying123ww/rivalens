"""Main DAG for the Rivalens competitor-analysis workflow."""

from typing import Any

from langgraph.graph import END, StateGraph

from rivalens.agents import (
    AnalysisAgent,
    CollectionAgent,
    PlanningAgent,
    PublisherAgent,
    QualityAgent,
    ReportWriterAgent,
    RevisionAgent,
    SchemaBuilderAgent,
)
from rivalens.research import ResearchToolkit
from rivalens.schema import CompetitorAnalysisState


def build_competitive_analysis_graph(
    websocket=None,
    stream_output=None,
    tone=None,
    headers: dict[str, Any] | None = None,
) -> Any:
    """Build the traceable multi-agent competitor-analysis DAG."""
    research_toolkit = ResearchToolkit(websocket, stream_output, tone=tone, headers=headers)
    planner = PlanningAgent(research_toolkit)
    collection = CollectionAgent(research_toolkit)
    schema_builder = SchemaBuilderAgent(research_toolkit)
    analysis = AnalysisAgent(research_toolkit)
    reviewer = QualityAgent(research_toolkit)
    reviser = RevisionAgent()
    writer = ReportWriterAgent()
    publisher = PublisherAgent()

    workflow = StateGraph(CompetitorAnalysisState)
    workflow.add_node("scope_planner", planner.run)
    workflow.add_node("source_collection", collection.run)
    workflow.add_node("schema_extraction", schema_builder.run)
    workflow.add_node("dimension_analysis", analysis.run)
    workflow.add_node("reviewer", reviewer.run)
    workflow.add_node("reviser", reviser.run)
    workflow.add_node("report_writer", writer.run)
    workflow.add_node("publisher", publisher.run)

    workflow.set_entry_point("scope_planner")
    workflow.add_edge("scope_planner", "source_collection")
    workflow.add_edge("source_collection", "schema_extraction")
    workflow.add_edge("schema_extraction", "dimension_analysis")
    workflow.add_edge("dimension_analysis", "reviewer")
    workflow.add_conditional_edges(
        "reviewer",
        lambda state: "revise" if state.get("quality_findings") else "accept",
        {"revise": "reviser", "accept": "report_writer"},
    )
    workflow.add_edge("reviser", "report_writer")
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
        "deep_research": kwargs.get("deep_research", True),
        "verbose": kwargs.get("verbose", True),
    }
    graph = build_competitive_analysis_graph(websocket, stream_output, tone, headers).compile()
    return await graph.ainvoke({"task": task})
