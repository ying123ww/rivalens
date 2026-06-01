"""Rule-based search query builder for competitor evidence collection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchQueryPlan:
    primary_query: str
    search_queries: list[str]


class SearchQueryBuilder:
    """Build short bilingual search seeds without competitor-specific aliases."""

    max_queries = 5
    max_query_words = 15

    _dimension_rules: tuple[tuple[tuple[str, ...], tuple[list[str], list[str]]], ...] = (
        (
            ("profile", "identity", "official", "category", "position"),
            (["\u5b98\u7f51", "\u4ea7\u54c1"], ["official site", "product"]),
        ),
        (
            ("pricing", "price", "fee", "packag", "tier", "business_model", "plan"),
            (["\u5b9a\u4ef7", "\u5957\u9910"], ["pricing", "plans"]),
        ),
        (
            ("feature", "capabil", "workflow", "use_case", "template", "function"),
            (["\u529f\u80fd", "\u80fd\u529b"], ["features", "capabilities"]),
        ),
        (
            ("integration", "ecosystem", "developer", "api", "plugin"),
            (["\u96c6\u6210", "API"], ["integrations", "API"]),
        ),
        (
            ("security", "compliance", "privacy", "admin", "risk", "license"),
            (["\u5b89\u5168", "\u5408\u89c4"], ["security", "compliance"]),
        ),
        (
            ("reliability", "sla", "status", "latency", "speed", "performance"),
            (["\u7a33\u5b9a\u6027", "SLA"], ["reliability", "SLA"]),
        ),
        (
            ("review", "sentiment", "customer", "case", "proof", "complaint"),
            (["\u7528\u6237\u8bc4\u4ef7", "\u6848\u4f8b"], ["reviews", "customers"]),
        ),
        (
            ("market", "growth", "trend", "expansion", "demand"),
            (["\u5e02\u573a", "\u589e\u957f"], ["market", "growth"]),
        ),
        (
            ("moat", "position", "differentiation", "advantage", "strategy"),
            (["\u5b9a\u4f4d", "\u4f18\u52bf"], ["positioning", "advantages"]),
        ),
    )

    _source_hint_terms: dict[str, tuple[list[str], list[str]]] = {
        "official_site": (["\u5b98\u7f51"], ["official site"]),
        "pricing_page": (["\u5b9a\u4ef7"], ["pricing"]),
        "docs": (["\u6587\u6863"], ["docs"]),
        "developer_docs": (["API"], ["API docs"]),
        "review": (["\u8bc4\u4ef7"], ["reviews"]),
        "customer_review": (["\u7528\u6237\u8bc4\u4ef7"], ["user reviews"]),
        "news": (["\u65b0\u95fb"], ["news"]),
        "marketplace": (["\u5e94\u7528\u5e02\u573a"], ["marketplace"]),
        "public_registry": (["\u516c\u5f00\u767b\u8bb0"], ["public registry"]),
        "security_page": (["\u5b89\u5168"], ["security"]),
        "status_page": (["\u72b6\u6001"], ["status"]),
    }

    def build(
        self,
        *,
        original_query: str,
        competitor: str,
        dimension: dict[str, Any],
        active_schema: dict[str, Any],
    ) -> SearchQueryPlan:
        subject = self._subject(competitor, original_query)
        zh_terms, en_terms = self._dimension_terms(dimension)
        zh_sources, en_sources = self._source_terms(dimension.get("source_hints", []))
        zh_industry, en_industry = self._industry_terms(active_schema)

        candidates = [
            self._query([subject, *zh_terms[:2], *zh_sources[:2]]),
            self._query([subject, *en_terms[:2], *en_sources[:2]]),
            self._query([subject, *zh_terms[:1], *zh_sources[:2]]),
            self._query([subject, *en_terms[:1], *en_sources[:2]]),
            self._query([subject, *zh_industry[:1], *zh_terms[:1]]),
            self._query([subject, *en_industry[:1], *en_terms[:1]]),
        ]
        search_queries = self._dedupe(candidates)[: self.max_queries]
        if not search_queries:
            search_queries = [self._query([original_query])]
        return SearchQueryPlan(
            primary_query=search_queries[0],
            search_queries=search_queries,
        )

    def _subject(self, competitor: str, original_query: str) -> str:
        if competitor.strip():
            return self._clean(competitor)
        return self._query(self._words(original_query, limit=4))

    def _dimension_terms(self, dimension: dict[str, Any]) -> tuple[list[str], list[str]]:
        haystack = " ".join(
            str(dimension.get(key, ""))
            for key in ("id", "name", "type", "description", "search_intent")
        ).lower()
        zh_terms: list[str] = []
        en_terms: list[str] = []
        for needles, terms in self._dimension_rules:
            if any(needle in haystack for needle in needles):
                zh_terms.extend(terms[0])
                en_terms.extend(terms[1])
        if not zh_terms:
            zh_terms = self._fallback_zh_terms(dimension)
        if not en_terms:
            en_terms = self._fallback_en_terms(dimension)
        return self._dedupe(zh_terms), self._dedupe(en_terms)

    def _source_terms(self, source_hints: list[str]) -> tuple[list[str], list[str]]:
        zh_terms: list[str] = []
        en_terms: list[str] = []
        for source_hint in source_hints:
            terms = self._source_hint_terms.get(str(source_hint))
            if not terms:
                continue
            zh_terms.extend(terms[0])
            en_terms.extend(terms[1])
        return self._dedupe(zh_terms), self._dedupe(en_terms)

    def _industry_terms(self, active_schema: dict[str, Any]) -> tuple[list[str], list[str]]:
        industry = active_schema.get("selected_industry", {}).get("name", "")
        words = self._words(industry, limit=2)
        return words, words

    def _fallback_zh_terms(self, dimension: dict[str, Any]) -> list[str]:
        name = self._clean(str(dimension.get("name", "")))
        if name:
            return [name]
        return ["\u516c\u5f00\u4fe1\u606f"]

    def _fallback_en_terms(self, dimension: dict[str, Any]) -> list[str]:
        identifier = str(dimension.get("id", ""))
        words = self._words(identifier.replace("_", " "), limit=2)
        return words or ["public", "evidence"]

    def _query(self, parts: list[str] | str) -> str:
        if isinstance(parts, str):
            return self._truncate_words(self._clean(parts))
        query = " ".join(self._dedupe([self._clean(part) for part in parts]))
        return self._truncate_words(query)

    def _words(self, value: str, limit: int) -> list[str]:
        return self._clean(value).split()[:limit]

    def _clean(self, value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text.strip(" \t\r\n\"'`.,;:|()[]{}")

    def _truncate_words(self, query: str) -> str:
        words = query.split()
        if len(words) <= self.max_query_words:
            return query
        return " ".join(words[: self.max_query_words])

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            cleaned = self._clean(value)
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cleaned)
        return deduped
