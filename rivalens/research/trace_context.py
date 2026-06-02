"""Trace context helpers for Rivalens research spans."""

from __future__ import annotations

from typing import Any

RIVALENS_TRACE_CONTEXT_KEY = "rivalens_trace_context"
RIVALENS_SEARCH_QUERIES_KEY = "rivalens_search_queries"

_TRACE_CONTEXT_KEYS = (
    "id",
    "research_task_id",
    "research_brief_id",
    "branch_id",
    "parent_branch_id",
    "depth",
    "competitor",
    "dimension_id",
    "dimension_name",
    "search_stage",
    "generated_from_gap",
    "decision_action",
    "decision_subtype",
    "query",
    "research_goal",
    "search_queries",
    "success_criteria",
    "target_url_count",
    "source_hints",
)


def compact_trace_context(trace_context: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stable, compact branch context suitable for trace inputs."""
    if not isinstance(trace_context, dict):
        return {}

    compact: dict[str, Any] = {}
    for key in _TRACE_CONTEXT_KEYS:
        value = trace_context.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "search_queries":
            compact[key] = list(value)[:6] if isinstance(value, list) else value
        elif key == "success_criteria":
            compact[key] = list(value)[:6] if isinstance(value, list) else value
        elif key == "source_hints":
            compact[key] = list(value)[:10] if isinstance(value, list) else value
        else:
            compact[key] = value
    return compact


def trace_context_from_researcher(researcher: Any) -> dict[str, Any]:
    direct_context = getattr(researcher, "rivalens_trace_context", None)
    if direct_context:
        return compact_trace_context(direct_context)

    kwargs = getattr(researcher, "kwargs", {}) or {}
    return compact_trace_context(kwargs.get(RIVALENS_TRACE_CONTEXT_KEY))


def trace_context_from_conductor(conductor: Any) -> dict[str, Any]:
    return trace_context_from_researcher(getattr(conductor, "researcher", None))


def langsmith_extra_for_trace_context(
    trace_context: dict[str, Any] | None,
    *,
    operation: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build dynamic LangSmith metadata and tags for a branch-aware span."""
    compact = compact_trace_context(trace_context)
    trace_metadata = {
        f"rivalens_{key}": value
        for key, value in compact.items()
        if key != "search_queries"
    }
    if "search_queries" in compact:
        trace_metadata["rivalens_search_queries"] = compact["search_queries"]
    trace_metadata["rivalens_operation"] = operation
    trace_metadata.update(metadata or {})

    trace_tags = list(tags or [])
    branch_id = compact.get("branch_id")
    if branch_id:
        trace_tags.append(f"branch:{branch_id}")
    search_stage = compact.get("search_stage")
    if search_stage:
        trace_tags.append(f"stage:{search_stage}")

    return {
        "metadata": trace_metadata,
        "tags": list(dict.fromkeys(trace_tags)),
    }
