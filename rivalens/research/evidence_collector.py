"""Evidence collection adapter for Rivalens collection workflows."""

import re
from datetime import datetime, timezone
from typing import Any

from rivalens.research.agent import ResearchEngine
from rivalens.research.modes import REPORT_TYPE_BY_MODE, ResearchMode
from rivalens.research.utils.enum import ReportSource, Tone
from rivalens.schema import EvidenceCollectionResult, EvidenceCollectionTask, EvidenceItem


class ResearchEngineEvidenceCollector:
    """Collect public evidence through ResearchEngine and normalize sources."""

    excerpt_chars = 1000
    chunk_overlap_chars = 100

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
            content = self._source_content(source)
            relevant_chunk = self._most_relevant_chunk(
                content,
                query=collection_task.get("query", ""),
                title=title,
            )

            evidence_items.append(
                {
                    "competitor": collection_task.get("competitor", ""),
                    "branch_id": collection_task.get("branch_id", collection_task.get("id", "")),
                    "parent_branch_id": collection_task.get("parent_branch_id"),
                    "collection_task_id": collection_task.get("id", ""),
                    "research_task_id": collection_task.get("research_task_id", ""),
                    "dimension_id": collection_task.get("dimension_id", ""),
                    "dimension_name": collection_task.get("dimension_name", ""),
                    "title": title,
                    "url": url,
                    "source_type": source.get("source_type") or self._infer_source_type(url, title),
                    "published_at": source.get("published_at"),
                    "retrieved_at": retrieved_at,
                    "excerpt": relevant_chunk,
                    "confidence": 0.7 if url else 0.4,
                }
            )

        return evidence_items

    def _source_content(self, source: dict[str, Any]) -> str:
        content = (
            source.get("content")
            or source.get("raw_content")
            or source.get("body")
            or ""
        )
        return " ".join(str(content).split())

    def _most_relevant_chunk(self, content: str, query: str, title: str) -> str:
        if len(content) <= self.excerpt_chars:
            return content

        chunks = self._chunks(content)
        query_tokens = self._query_tokens(f"{query} {title}")
        if not query_tokens:
            return chunks[0]

        best_chunk = chunks[0]
        best_score = -1
        for position, chunk in enumerate(chunks):
            chunk_tokens = set(self._tokens(chunk))
            overlap = sum(1 for token in query_tokens if token in chunk_tokens)
            phrase_bonus = sum(
                2
                for token in query_tokens
                if len(token) > 4 and token in chunk.lower()
            )
            score = overlap + phrase_bonus
            if score > best_score:
                best_score = score
                best_chunk = chunk
            elif score == best_score and position == 0:
                best_chunk = chunk

        return best_chunk

    def _chunks(self, content: str) -> list[str]:
        step = self.excerpt_chars - self.chunk_overlap_chars
        chunks = []
        for start in range(0, len(content), step):
            chunk = content[start : start + self.excerpt_chars]
            if chunk:
                chunks.append(chunk)
            if start + self.excerpt_chars >= len(content):
                break
        return chunks or [content]

    def _query_tokens(self, text: str) -> list[str]:
        stopwords = {
            "and",
            "are",
            "branch",
            "collect",
            "competitor",
            "definition",
            "evidence",
            "focus",
            "from",
            "industry",
            "only",
            "pages",
            "prefer",
            "public",
            "query",
            "relevant",
            "research",
            "schema",
            "selected",
            "source",
            "sources",
            "the",
            "this",
            "when",
            "with",
        }
        return [
            token
            for token in dict.fromkeys(self._tokens(text))
            if len(token) > 2 and token not in stopwords
        ]

    def _tokens(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

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
