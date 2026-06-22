"""Main DAG for the Rivalens competitor-analysis workflow."""

import os
from typing import Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

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


def _workflow_run_config(
    task: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    competitors = task.get("competitors") or []
    if not isinstance(competitors, list):
        competitors = [competitors]
    business_run_id = str(
        task.get("run_id")
        or uuid5(NAMESPACE_URL, f"rivalens-task:{task.get('query', '')}")
    )
    trace_id = _langsmith_trace_id(
        business_run_id,
        task.get("langsmith_trace_id"),
    )
    thread_id = str(task.get("langsmith_thread_id") or business_run_id)

    config = {
        "run_id": UUID(trace_id),
        "run_name": "rivalens_competitive_analysis",
        "tags": [
            "rivalens",
            "competitive-analysis",
            "langgraph",
        ],
        "metadata": {
            "workflow": "competitive_analysis",
            "entrypoint": "run_competitive_analysis_task",
            "business_run_id": business_run_id,
            "thread_id": thread_id,
            "langsmith_trace_id": trace_id,
            "collector": "CollectionAgent",
            "query_length": len(task.get("query", "")),
            "competitor_count": len(competitors),
            "competitors": [
                competitor.get("name", "")
                if isinstance(competitor, dict)
                else str(competitor)
                for competitor in competitors
            ],
            "industry_directions_confirmed": bool(
                task.get("industry_directions_confirmed")
            ),
            "custom_analysis_direction_count": len(
                task.get("custom_analysis_directions") or []
            ),
            "retriever": os.getenv("RETRIEVER", ""),
            "scraper": os.getenv("SCRAPER", ""),
            "max_branch_depth": _int_budget(
                kwargs.get("max_branch_depth"),
                "RIVALENS_MAX_BRANCH_DEPTH",
                1,
            ),
            "max_expansion_branches": _int_budget(
                kwargs.get("max_expansion_branches"),
                "RIVALENS_MAX_EXPANSION_BRANCHES",
                24,
            ),
            "max_root_branch_hard_limit": _int_budget(
                kwargs.get("max_root_branch_hard_limit"),
                "RIVALENS_MAX_ROOT_BRANCHES",
                20,
                minimum=1,
            ),
        },
    }
    if task.get("user_id"):
        config["metadata"]["user_id"] = str(task["user_id"])
    return config


def _langsmith_trace_id(run_id: str, explicit_trace_id: Any = None) -> str:
    if explicit_trace_id:
        return str(UUID(str(explicit_trace_id)))
    try:
        return str(UUID(run_id))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"rivalens:{run_id}"))


def _route_after_claim_support(state: CompetitorAnalysisState) -> str:
    review_events = [
        event
        for event in state.get("agent_events", [])
        if event.get("agent") == "claim_support"
        and event.get("action") == "review_claim_support"
    ]
    if len(review_events) >= 2:
        return "report_writer"
    if any(
        review.get("recommended_action") == "revise"
        and review.get("suggested_revision")
        for review in state.get("claim_support_reviews", [])
    ):
        return "dimension_analysis"
    return "report_writer"


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
            20,
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
        _route_after_claim_support,
        {
            "dimension_analysis": "dimension_analysis",
            "report_writer": "report_writer",
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
    run_id = str(kwargs.get("run_id") or uuid4())
    task = {
        "run_id": run_id,
        "user_id": kwargs.get("user_id"),
        "langsmith_trace_id": _langsmith_trace_id(
            run_id,
            kwargs.get("langsmith_trace_id"),
        ),
        "langsmith_thread_id": str(kwargs.get("langsmith_thread_id") or run_id),
        "langsmith_trace_url": kwargs.get("langsmith_trace_url"),
        "langsmith_project": (
            os.getenv("LANGSMITH_PROJECT")
            or os.getenv("LANGCHAIN_PROJECT")
            or ""
        ),
        "query": query,
        "competitors": kwargs.get("competitors", []),
        "report_source": kwargs.get("report_source", "web"),
        "files": kwargs.get("files", kwargs.get("file_paths", [])),
        "attachments": kwargs.get("attachments", []),
        "industry_direction_plan": kwargs.get("industry_direction_plan"),
        "custom_analysis_directions": kwargs.get("custom_analysis_directions", []),
        "industry_directions_confirmed": kwargs.get(
            "industry_directions_confirmed",
            False,
        ),
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
    return await graph.ainvoke(
        {"task": task},
        config=_workflow_run_config(task, kwargs),
    )
