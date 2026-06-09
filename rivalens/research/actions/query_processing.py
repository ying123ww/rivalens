import json_repair

from langsmith import traceable

from rivalens.research.llm_provider.generic.base import ReasoningEfforts
from ..utils.llm import create_chat_completion
from ..prompts import PromptFamily
from typing import Any, List, Dict
from ..config import Config
from ..trace_context import (
    RIVALENS_TRACE_CONTEXT_KEY,
    compact_trace_context,
    trace_context_from_researcher,
)
import logging

logger = logging.getLogger(__name__)


def _retriever_name(retriever: Any) -> str:
    return getattr(retriever, "__name__", retriever.__class__.__name__)


def _search_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    trace_context = compact_trace_context(inputs.get("trace_context"))
    if not trace_context:
        trace_context = trace_context_from_researcher(inputs.get("researcher"))
    return {
        "query": inputs.get("query", ""),
        "retriever": _retriever_name(inputs.get("retriever")),
        "query_domains": list(inputs.get("query_domains") or []),
        "collection_task": trace_context,
    }


def _search_trace_outputs(output: Any) -> dict[str, Any]:
    results = output if isinstance(output, list) else []
    return {
        "result_count": len(results),
        "results": [
            {
                "title": item.get("title", ""),
                "url": item.get("href") or item.get("url") or item.get("link") or "",
                "body_chars": len(str(item.get("body") or item.get("content") or "")),
                "has_full_text": bool(item.get("content_is_full_text")),
            }
            for item in results[:10]
            if isinstance(item, dict)
        ],
    }


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text or text[0] not in "[{\"":
        return value

    try:
        return json_repair.loads(text)
    except Exception:
        return value


def _clean_sub_query(query: str) -> str:
    return " ".join(query.split()).strip().strip("\"'")


def _dedupe_sub_queries(queries: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for query in queries:
        cleaned = _clean_sub_query(query)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _normalize_sub_queries_response(response: Any) -> List[str]:
    parsed = _parse_jsonish(response)

    if isinstance(parsed, dict):
        for key in ("queries", "search_queries", "sub_queries", "query"):
            if key in parsed:
                return _normalize_sub_queries_response(parsed[key])
        text = parsed.get("text")
        if isinstance(text, str):
            return _normalize_sub_queries_response(text)
        return []

    if isinstance(parsed, list):
        queries = []
        for item in parsed:
            if isinstance(item, str):
                queries.append(item)
            elif isinstance(item, dict):
                queries.extend(_normalize_sub_queries_response(item))
        return _dedupe_sub_queries(queries)

    if isinstance(parsed, str):
        reparsed = _parse_jsonish(parsed)
        if reparsed is not parsed:
            return _normalize_sub_queries_response(reparsed)
        return _dedupe_sub_queries([parsed])

    return []


def _format_collection_planning_context(trace_context: dict[str, Any] | None) -> str:
    if not trace_context:
        return ""
    lines = []
    for label, key in (
        ("Competitor", "competitor"),
        ("Dimension", "dimension_name"),
        ("Dimension ID", "dimension_id"),
        ("Search stage", "search_stage"),
        ("Research goal", "research_goal"),
    ):
        value = trace_context.get(key)
        if value:
            lines.append(f"{label}: {value}")
    source_hints = trace_context.get("source_hints") or []
    if source_hints:
        lines.append("Preferred source types: " + ", ".join(source_hints[:10]))
    target_source_types = trace_context.get("target_source_types") or []
    if target_source_types:
        lines.append("Target source types: " + ", ".join(target_source_types[:5]))
    criteria = trace_context.get("success_criteria") or []
    if criteria:
        criterion_text = [
            criterion.get("description", "")
            for criterion in criteria
            if isinstance(criterion, dict) and criterion.get("description")
        ]
        if criterion_text:
            lines.append("Success criteria: " + " | ".join(criterion_text[:6]))
    return "\n".join(lines)


@traceable(
    name="rivalens_initial_search",
    run_type="retriever",
    tags=["rivalens", "collection", "search"],
    process_inputs=_search_trace_inputs,
    process_outputs=_search_trace_outputs,
)
async def get_search_results(
    query: str,
    retriever: Any,
    query_domains: List[str] = None,
    researcher=None,
    trace_context: dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """
    Get web search results for a given query.

    Args:
        query: The search query
        retriever: The retriever instance
        query_domains: Optional list of domains to search
        researcher: The researcher instance (needed for MCP retrievers)

    Returns:
        A list of search results
    """
    # Check if this is an MCP retriever and pass the researcher instance
    if "mcpretriever" in retriever.__name__.lower():
        search_retriever = retriever(
            query, 
            query_domains=query_domains,
            headers=getattr(researcher, "headers", None) if researcher else None,
            researcher=researcher  # Pass researcher instance for MCP retrievers
        )
    else:
        search_retriever = retriever(
            query,
            query_domains=query_domains,
            headers=getattr(researcher, "headers", None) if researcher else None,
        )
    
    return search_retriever.search()

async def generate_sub_queries(
    query: str,
    context: List[Dict[str, Any]],
    cfg: Config,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    trace_context: dict[str, Any] | None = None,
    **kwargs
) -> List[str]:
    """
    Generate sub-queries using the specified LLM model.

    Args:
        query: The original query
        max_iterations: Maximum number of research iterations
        context: Search results context
        cfg: Configuration object
        cost_callback: Callback for cost calculation
        prompt_family: Family of prompts

    Returns:
        A list of sub-queries
    """
    gen_queries_prompt = prompt_family.generate_search_queries_prompt(
        query,
        max_iterations=cfg.max_iterations or 3,
        context=context,
    )
    collection_context = _format_collection_planning_context(trace_context)
    if collection_context:
        gen_queries_prompt += (
            "\n\nStructured collection context. Use this to expand the seed query "
            "without changing the competitor or dimension:\n"
            f"{collection_context}"
        )

    response = await create_chat_completion(
        model=cfg.strategic_llm_model,
        messages=[{"role": "user", "content": gen_queries_prompt}],
        llm_provider=cfg.strategic_llm_provider,
        max_tokens=None,
        llm_kwargs=cfg.llm_kwargs,
        reasoning_effort=ReasoningEfforts.Medium.value,
        cost_callback=cost_callback,
        rivalens_operation="generate_sub_queries",
        **({RIVALENS_TRACE_CONTEXT_KEY: trace_context} if trace_context else {}),
        **kwargs
    )

    sub_queries = _normalize_sub_queries_response(response)
    if not sub_queries:
        raise ValueError("Sub-query LLM returned no parseable queries.")
    return sub_queries

async def plan_research_outline(
    query: str,
    search_results: List[Dict[str, Any]],
    agent_role_prompt: str,
    cfg: Config,
    cost_callback: callable = None,
    retriever_names: List[str] = None,
    trace_context: dict[str, Any] | None = None,
    **kwargs
) -> List[str]:
    """
    Plan the research outline by generating sub-queries.

    Args:
        query: Original query
        search_results: Initial search results
        agent_role_prompt: Agent role prompt
        cfg: Configuration object
        cost_callback: Callback for cost calculation
        retriever_names: Names of the retrievers being used

    Returns:
        A list of sub-queries
    """
    # Handle the case where retriever_names is not provided
    if retriever_names is None:
        retriever_names = []
    
    # For MCP retrievers, we may want to skip sub-query generation
    # Check if MCP is the only retriever or one of multiple retrievers
    if retriever_names and ("mcp" in retriever_names or "MCPRetriever" in retriever_names):
        mcp_only = (len(retriever_names) == 1 and 
                   ("mcp" in retriever_names or "MCPRetriever" in retriever_names))
        
        if mcp_only:
            # If MCP is the only retriever, skip sub-query generation
            logger.info("Using MCP retriever only - skipping sub-query generation")
            # Return the original query to prevent additional search iterations
            return [query]
        else:
            # If MCP is one of multiple retrievers, generate sub-queries for the others
            logger.info("Using MCP with other retrievers - generating sub-queries for non-MCP retrievers")

    # Generate sub-queries for research outline
    sub_queries = await generate_sub_queries(
        query,
        search_results,
        cfg,
        cost_callback,
        trace_context=trace_context,
        **kwargs
    )

    return sub_queries
