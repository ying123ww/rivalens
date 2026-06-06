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
    """Build short localized search seeds without competitor-specific aliases."""

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
        industry_direction_plan: dict[str, Any],
    ) -> SearchQueryPlan:
        subject = self._subject(competitor, original_query)
        zh_terms, en_terms = self._dimension_terms(dimension)
        zh_sources, en_sources = self._source_terms(dimension.get("source_hints", []))
        zh_industry, en_industry = self._industry_terms(industry_direction_plan)
        focused_candidates = self._focused_dimension_queries(
            subject=subject,
            dimension=dimension,
            prefers_chinese=self._prefers_chinese_queries(original_query, competitor),
            zh_sources=zh_sources,
            en_sources=en_sources,
        )

        if self._prefers_chinese_queries(original_query, competitor):
            candidates = [
                *focused_candidates,
                self._query([subject, *zh_terms[:2], *zh_sources[:2]]),
                self._query([subject, *zh_terms[:1], *zh_sources[:2]]),
                self._query([subject, *zh_terms[:2]]),
                self._query([subject, *zh_sources[:2]]),
                self._query([subject, *zh_industry[:1], *zh_terms[:1]]),
            ]
        else:
            candidates = [
                *focused_candidates,
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

    def _focused_dimension_queries(
        self,
        *,
        subject: str,
        dimension: dict[str, Any],
        prefers_chinese: bool,
        zh_sources: list[str],
        en_sources: list[str],
    ) -> list[str]:
        haystack = self._dimension_haystack(dimension)
        if not self._is_ai_dimension(haystack):
            return []
        if prefers_chinese:
            return [
                self._query([subject, "AI", "\u529f\u80fd", *zh_sources[:2]]),
                self._query([subject, "AI", "\u5b9a\u4ef7", "\u4f1a\u5458"]),
                self._query([subject, "AI", "\u7248\u672c", "\u6743\u76ca"]),
                self._query([subject, "AI", "\u989d\u5ea6", "\u70b9\u6570"]),
                self._query([subject, "AI", "\u6d88\u8017\u89c4\u5219", "\u6587\u6863"]),
            ]
        return [
            self._query([subject, "AI", "features", *en_sources[:2]]),
            self._query([subject, "AI", "pricing", "plans"]),
            self._query([subject, "AI", "versions", "entitlements"]),
            self._query([subject, "AI", "quota", "credits"]),
            self._query([subject, "AI", "usage", "docs"]),
        ]

    def _subject(self, competitor: str, original_query: str) -> str:
        if competitor.strip():
            return self._clean(competitor)
        return self._query(self._words(original_query, limit=4))

    def _dimension_terms(self, dimension: dict[str, Any]) -> tuple[list[str], list[str]]:
        haystack = self._dimension_haystack(dimension)
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

    def _dimension_haystack(self, dimension: dict[str, Any]) -> str:
        return " ".join(
            str(dimension.get(key, ""))
            for key in ("id", "name", "type", "description", "search_intent")
        ).lower()

    def _is_ai_dimension(self, haystack: str) -> bool:
        if re.search(r"(^|[^a-z0-9])ai([^a-z0-9]|$)", haystack):
            return True
        return any(
            needle in haystack
            for needle in (
                "artificial intelligence",
                "\u4eba\u5de5\u667a\u80fd",
                "\u667a\u80fd\u4f53",
            )
        )

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

    def _industry_terms(
        self,
        industry_direction_plan: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        industry = (industry_direction_plan.get("industry") or {}).get("name", "")
        words = self._words(industry, limit=4)
        zh_words = [word for word in words if self._contains_cjk(word)]
        en_words = [word for word in words if not self._contains_cjk(word)]
        return zh_words[:2], (en_words or words)[:2]

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
        return [
            word
            for word in self._clean(value).split()
            if any(character.isalnum() for character in word)
        ][:limit]

    def _prefers_chinese_queries(self, original_query: str, competitor: str) -> bool:
        return self._contains_cjk(original_query) or self._contains_cjk(competitor)

    def _contains_cjk(self, value: Any) -> bool:
        return bool(re.search(r"[\u3400-\u9fff]", str(value)))

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
