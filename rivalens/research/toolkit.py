"""Agent-facing research tools for Rivalens workflows."""

from datetime import datetime, timezone
from typing import Any

from rivalens.research.agent import ResearchEngine
from rivalens.research.modes import REPORT_TYPE_BY_MODE, ResearchMode
from rivalens.research.utils.enum import ReportSource, Tone
from rivalens.schema import EvidenceItem


class ResearchToolkit:
    """Expose research capabilities as business-level tools for agents."""

    def __init__(
        self,
        websocket=None,
        stream_output=None,
        tone: Tone = Tone.Objective,
        headers: dict[str, Any] | None = None,
    ):
        self.websocket = websocket
        self.stream_output = stream_output
        self.tone = tone
        self.headers = headers or {}
        self._research_pool: dict[str, Any] = {
            "runs": [],
            "sources_by_key": {},
        }

    async def collect_evidence(
        self,
        query: str,
        competitor: str = "",
        deep: bool = False,
        verbose: bool = True,
        source: str = ReportSource.Web.value,
        query_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        mode = ResearchMode.DEEP_EVIDENCE if deep else ResearchMode.STANDARD_EVIDENCE
        return await self.run_mode(
            mode=mode,
            query=query,
            competitor=competitor,
            source=source,
            verbose=verbose,
            query_domains=query_domains,
            write_report=False,
        )

    async def collect_schema_evidence(
        self,
        collection_task: dict[str, Any],
        deep: bool = False,
        verbose: bool = True,
        source: str = ReportSource.Web.value,
        query_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Collect evidence for one schema-aware collection task and pool it."""
        result = await self.collect_evidence(
            query=collection_task["query"],
            competitor=collection_task.get("competitor", ""),
            deep=deep,
            verbose=verbose,
            source=source,
            query_domains=query_domains,
        )
        return self.register_research_result(result, collection_task)

    def register_research_result(
        self,
        result: dict[str, Any],
        collection_task: dict[str, Any],
    ) -> dict[str, Any]:
        """Add a research result to the toolkit-level aggregation pool."""
        enriched_result = dict(result)
        enriched_sources = []
        for source in result.get("sources", []):
            enriched_source = dict(source)
            enriched_source.setdefault("competitor", collection_task.get("competitor", ""))
            enriched_source["collection_task_id"] = collection_task.get("id", "")
            enriched_source["dimension_id"] = collection_task.get("dimension_id", "")
            enriched_source["dimension_name"] = collection_task.get("dimension_name", "")
            enriched_sources.append(enriched_source)
            self._research_pool["sources_by_key"][self._source_key(enriched_source)] = enriched_source

        enriched_result["sources"] = enriched_sources
        self._research_pool["runs"].append(
            {
                "collection_task_id": collection_task.get("id", ""),
                "competitor": collection_task.get("competitor", ""),
                "dimension_id": collection_task.get("dimension_id", ""),
                "dimension_name": collection_task.get("dimension_name", ""),
                "mode": result.get("mode", ""),
                "query": result.get("query", ""),
                "source_count": len(enriched_sources),
                "costs": result.get("costs", 0),
            }
        )
        return enriched_result

    def get_research_pool_snapshot(self) -> dict[str, Any]:
        """Return a deterministic snapshot of pooled research runs and sources."""
        sources = list(self._research_pool["sources_by_key"].values())
        return {
            "run_count": len(self._research_pool["runs"]),
            "source_count": len(sources),
            "runs": list(self._research_pool["runs"]),
            "sources": sources,
            "by_competitor": self._count_by(sources, "competitor"),
            "by_dimension": self._count_by(sources, "dimension_id"),
        }

    def summarize_research_pool(self) -> dict[str, Any]:
        """Summarize pooled research coverage without making another LLM call."""
        snapshot = self.get_research_pool_snapshot()
        return {
            "run_count": snapshot["run_count"],
            "source_count": snapshot["source_count"],
            "competitors": sorted(snapshot["by_competitor"].keys()),
            "dimensions": sorted(snapshot["by_dimension"].keys()),
            "coverage": {
                "by_competitor": snapshot["by_competitor"],
                "by_dimension": snapshot["by_dimension"],
            },
        }

    def clear_research_pool(self) -> None:
        """Clear pooled research state for callers that reuse a toolkit."""
        self._research_pool = {
            "runs": [],
            "sources_by_key": {},
        }

    async def discover_sources(self, query: str, verbose: bool = True) -> dict[str, Any]:
        return await self.run_mode(
            mode=ResearchMode.SOURCE_DISCOVERY,
            query=query,
            verbose=verbose,
            write_report=True,
        )

    async def generate_outline(self, query: str, verbose: bool = True) -> dict[str, Any]:
        return await self.run_mode(
            mode=ResearchMode.OUTLINE_ASSISTED,
            query=query,
            verbose=verbose,
            write_report=True,
        )

    async def extract_schema(self, query: str, context: Any, verbose: bool = True) -> dict[str, Any]:
        prompt = (
            "Extract competitor-analysis facts from the provided context. "
            "Return concise structured facts with dimensions, evidence references, "
            "and confidence. Do not invent unsupported claims."
        )
        return await self.run_mode(
            mode=ResearchMode.SCHEMA_EXTRACTION,
            query=query,
            context=context,
            custom_prompt=prompt,
            verbose=verbose,
            write_report=True,
        )

    async def focused_analysis(self, query: str, context: Any, verbose: bool = True) -> dict[str, Any]:
        return await self.run_mode(
            mode=ResearchMode.FOCUSED_ANALYSIS,
            query=query,
            context=context,
            verbose=verbose,
            write_report=True,
        )

    async def subtopic_evidence(
        self,
        query: str,
        parent_query: str,
        competitor: str = "",
        verbose: bool = True,
    ) -> dict[str, Any]:
        return await self.run_mode(
            mode=ResearchMode.SUBTOPIC_EVIDENCE,
            query=query,
            competitor=competitor,
            parent_query=parent_query,
            verbose=verbose,
            write_report=False,
        )

    async def run_mode(
        self,
        mode: ResearchMode,
        query: str,
        competitor: str = "",
        source: str = ReportSource.Web.value,
        verbose: bool = True,
        query_domains: list[str] | None = None,
        parent_query: str = "",
        context: Any = None,
        custom_prompt: str = "",
        write_report: bool = False,
    ) -> dict[str, Any]:
        researcher = ResearchEngine(
            query=query,
            report_type=REPORT_TYPE_BY_MODE[mode],
            report_source=source,
            tone=self.tone,
            verbose=verbose,
            websocket=self.websocket,
            headers=self.headers,
            query_domains=query_domains,
            parent_query=parent_query,
            context=context,
        )

        collected_context = await researcher.conduct_research()
        report = ""
        if write_report:
            report = await researcher.write_report(
                ext_context=context or collected_context,
                custom_prompt=custom_prompt,
            )

        sources = self._to_evidence_items(
            competitor=competitor,
            sources=researcher.get_research_sources(),
            prefix=mode.value,
        )
        return {
            "mode": mode.value,
            "query": query,
            "competitor": competitor,
            "context": collected_context,
            "report": report,
            "sources": sources,
            "costs": researcher.get_costs(),
        }

    def _to_evidence_items(
        self,
        competitor: str,
        sources: list[dict[str, Any]],
        prefix: str,
    ) -> list[EvidenceItem]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        evidence_items: list[EvidenceItem] = []

        for index, source in enumerate(sources):
            url = source.get("url") or source.get("href") or ""
            title = source.get("title") or url or f"Evidence {index + 1}"
            content = source.get("content") or source.get("raw_content") or ""
            summary = source.get("summary") or content[:500]

            evidence_items.append(
                {
                    "id": f"{prefix}_ev_{index + 1}",
                    "competitor": competitor,
                    "title": title,
                    "url": url,
                    "source_type": "other",
                    "published_at": source.get("published_at"),
                    "retrieved_at": retrieved_at,
                    "excerpt": content[:1000],
                    "summary": summary,
                    "confidence": 0.7 if url else 0.4,
                }
            )

        return evidence_items

    def _source_key(self, source: dict[str, Any]) -> str:
        url = source.get("url", "")
        title = source.get("title", "")
        competitor = source.get("competitor", "")
        dimension_id = source.get("dimension_id", "")
        return "|".join([competitor, dimension_id, url or title])

    def _count_by(self, sources: list[dict[str, Any]], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for source in sources:
            key = source.get(field) or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts
