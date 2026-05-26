"""Evidence collection adapter for Rivalens collection workflows."""

from datetime import datetime, timezone
from typing import Any

from rivalens.research.agent import ResearchEngine
from rivalens.research.modes import REPORT_TYPE_BY_MODE, ResearchMode
from rivalens.research.utils.enum import ReportSource, Tone
from rivalens.schema import EvidenceCollectionResult, EvidenceCollectionTask, EvidenceItem


class ResearchEngineEvidenceCollector:
    """Collect public evidence through ResearchEngine and normalize sources."""

    def __init__(
        self,
        websocket=None,
        stream_output=None,
        tone: Tone | None = Tone.Objective,
        headers: dict[str, Any] | None = None,
    ):
        self.websocket = websocket
        self.stream_output = stream_output
        self.tone = tone or Tone.Objective
        self.headers = headers or {}

    async def collect(
        self,
        collection_task: EvidenceCollectionTask,
        deep: bool = False,
        verbose: bool = True,
        source: str = ReportSource.Web.value,
        query_domains: list[str] | None = None,
    ) -> EvidenceCollectionResult:
        """Run evidence collection for one schema-aware collection task."""
        mode = ResearchMode.DEEP_EVIDENCE if deep else ResearchMode.STANDARD_EVIDENCE
        researcher = ResearchEngine(
            query=collection_task["query"],
            report_type=REPORT_TYPE_BY_MODE[mode],
            report_source=source,
            tone=self.tone,
            verbose=verbose,
            websocket=self.websocket,
            headers=self.headers,
            query_domains=query_domains,
        )

        collected_context = await researcher.conduct_research()
        evidence_items = self._to_evidence_items(
            collection_task=collection_task,
            sources=researcher.get_research_sources(),
        )

        return {
            "task": dict(collection_task),
            "mode": mode.value,
            "query": collection_task["query"],
            "context": collected_context,
            "evidence_items": evidence_items,
            "costs": researcher.get_costs(),
        }

    def _to_evidence_items(
        self,
        collection_task: EvidenceCollectionTask,
        sources: list[dict[str, Any]],
    ) -> list[EvidenceItem]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        evidence_items: list[EvidenceItem] = []

        for source in sources:
            url = source.get("url") or source.get("href") or ""
            title = source.get("title") or url or "Untitled evidence"
            content = source.get("content") or source.get("raw_content") or source.get("body") or ""
            summary = source.get("summary") or content[:500]

            evidence_items.append(
                {
                    "competitor": collection_task.get("competitor", ""),
                    "branch_id": collection_task.get("branch_id", collection_task.get("id", "")),
                    "parent_branch_id": collection_task.get("parent_branch_id"),
                    "collection_task_id": collection_task.get("id", ""),
                    "dimension_id": collection_task.get("dimension_id", ""),
                    "dimension_name": collection_task.get("dimension_name", ""),
                    "title": title,
                    "url": url,
                    "source_type": source.get("source_type") or self._infer_source_type(url, title),
                    "published_at": source.get("published_at"),
                    "retrieved_at": retrieved_at,
                    "excerpt": content[:1000],
                    "summary": summary,
                    "confidence": 0.7 if url else 0.4,
                }
            )

        return evidence_items

    def _infer_source_type(self, url: str, title: str) -> str:
        normalized = f"{url} {title}".lower()
        if "pricing" in normalized or "price" in normalized:
            return "pricing_page"
        if "docs." in normalized or "/docs" in normalized or "documentation" in normalized:
            return "docs"
        if "blog" in normalized:
            return "blog"
        if "news" in normalized or "press" in normalized:
            return "news"
        if "review" in normalized or "g2.com" in normalized or "capterra" in normalized:
            return "review"
        if "marketplace" in normalized or "apps." in normalized:
            return "marketplace"
        return "other"
