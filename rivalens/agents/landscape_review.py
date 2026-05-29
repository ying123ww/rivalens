"""Landscape review for source-universe discovery."""

from typing import Any
from urllib.parse import urlparse

from rivalens.schema import LandscapeAssessment, ResearchBranch, ResearchTask


class LandscapeReviewer:
    """Turn landscape search results into focused collection tasks."""

    def review(
        self,
        branch: ResearchBranch,
        research_task: ResearchTask,
        sources: list[dict[str, Any]],
    ) -> LandscapeAssessment:
        candidate_sources = [
            self._candidate_source(branch, source)
            for source in sources
            if self._source_url(source)
        ]
        discovered_source_types = list(
            dict.fromkeys(
                source.get("source_type", "other")
                for source in candidate_sources
                if source.get("source_type")
            )
        )
        expected_source_types = branch.get("expected_source_types", []) or []
        missing_source_types = [
            source_type
            for source_type in expected_source_types
            if source_type not in discovered_source_types
        ]
        focused_task_specs = self._focused_task_specs(
            branch,
            candidate_sources,
            missing_source_types,
            research_task,
        )
        disambiguation = self._competitor_disambiguation(branch, candidate_sources)
        split_suggestions = self._dimension_split_suggestions(branch)
        split_task_specs = self._split_task_specs(branch, split_suggestions)
        if disambiguation.get("status") == "ambiguous":
            focused_task_specs = self._disambiguation_task_specs(
                branch,
                disambiguation,
            )
        decision = self._decision(
            focused_task_specs,
            disambiguation,
            split_task_specs,
        )

        return {
            "id": f"landscape_{research_task.get('id', branch.get('id', 'unknown'))}",
            "branch_id": branch.get("id", ""),
            "research_task_id": research_task.get("id", ""),
            "competitor": branch.get("competitor", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "discovered_source_types": discovered_source_types,
            "missing_source_types": missing_source_types,
            "candidate_sources": candidate_sources,
            "source_universe_confidence": self._confidence(candidate_sources, missing_source_types),
            "competitor_disambiguation": disambiguation,
            "dimension_split_suggestions": split_suggestions,
            "query_refinements": [spec.get("query", "") for spec in focused_task_specs],
            "focused_task_specs": focused_task_specs,
            "split_task_specs": split_task_specs,
            "decision": decision,
            "user_visible_summary": self._summary(
                discovered_source_types,
                missing_source_types,
                focused_task_specs,
                disambiguation,
            ),
        }

    def _candidate_source(
        self,
        branch: ResearchBranch,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        url = self._source_url(source)
        title = source.get("title") or url
        source_type = source.get("source_type") or self._infer_source_type(url, title)
        official = self._looks_official(url, branch.get("competitor", ""))
        if official:
            source_type = "official_site" if source_type == "other" else source_type
        return {
            "url": url,
            "title": title,
            "source_type": source_type,
            "domain": urlparse(url).netloc.lower(),
            "relevance_reason": (
                f"Candidate {source_type} source for "
                f"{branch.get('competitor', 'the competitor')} "
                f"{branch.get('dimension_name', branch.get('dimension_id', 'research'))}."
            ),
            "confidence": 0.75 if official else 0.55,
            "should_collect_deeply": True,
        }

    def _focused_task_specs(
        self,
        branch: ResearchBranch,
        candidate_sources: list[dict[str, Any]],
        missing_source_types: list[str],
        research_task: ResearchTask,
    ) -> list[dict[str, Any]]:
        if not candidate_sources:
            return [
                {
                    "objective": f"Refine landscape scan for {branch.get('dimension_name', branch.get('dimension_id', 'research'))}",
                    "query": self._refinement_query(branch, research_task),
                    "target_source_types": branch.get("expected_source_types", []),
                    "generated_from_gap": "landscape_refinement",
                    "decision_action": "scope_refinement",
                    "decision_subtype": "query_refinement",
                    "reason": "Landscape scan needs another pass before focused evidence collection.",
                    "search_stage": "landscape",
                }
            ]

        candidate_specs = []
        for source in candidate_sources[:2]:
            candidate_specs.append(
                {
                    "objective": f"Collect candidate source: {source.get('title', '')}",
                    "query": self._source_query(branch, source),
                    "target_source_types": [source.get("source_type", "other")],
                    "generated_from_gap": "landscape_candidate_source",
                    "decision_action": "evidence_extraction",
                    "decision_subtype": "targeted_url_extract",
                    "reason": "Landscape scan found a candidate source worth focused collection.",
                    "search_stage": "focused",
                    "target_urls": [source.get("url", "")],
                    "source_confidence": source.get("confidence", 0.5),
                }
            )

        missing_specs = []
        for source_type in missing_source_types[:2]:
            missing_specs.append(
                {
                    "objective": f"Find missing {source_type} source",
                    "query": self._source_type_query(branch, source_type),
                    "target_source_types": [source_type],
                    "generated_from_gap": f"landscape_missing_source_type:{source_type}",
                    "decision_action": "source_discovery",
                    "decision_subtype": "source_type_search",
                    "reason": f"Landscape scan did not discover a {source_type} source.",
                    "search_stage": "focused",
                }
            )
        return self._allocate_follow_up_specs(branch, candidate_specs, missing_specs)

    def _allocate_follow_up_specs(
        self,
        branch: ResearchBranch,
        candidate_specs: list[dict[str, Any]],
        missing_specs: list[dict[str, Any]],
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        expected = list(branch.get("expected_source_types", []))

        def source_type_rank(spec: dict[str, Any]) -> int:
            source_type = (spec.get("target_source_types") or ["other"])[0]
            return expected.index(source_type) if source_type in expected else len(expected)

        sorted_candidates = sorted(
            candidate_specs,
            key=lambda spec: (
                source_type_rank(spec),
                -float(spec.get("source_confidence", 0.5) or 0.5),
            ),
        )
        sorted_missing = sorted(missing_specs, key=source_type_rank)

        selected: list[dict[str, Any]] = []
        if sorted_candidates:
            selected.append(sorted_candidates[0])
        if sorted_missing and len(selected) < limit:
            selected.append(sorted_missing[0])

        remaining = sorted_candidates[1:] + sorted_missing[1:]
        remaining = sorted(
            remaining,
            key=lambda spec: (
                source_type_rank(spec),
                0 if spec.get("target_urls") else 1,
                -float(spec.get("source_confidence", 0.5) or 0.5),
            ),
        )

        for spec in remaining:
            if len(selected) >= limit:
                break
            selected.append(spec)
        return selected

    def _disambiguation_task_specs(
        self,
        branch: ResearchBranch,
        disambiguation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        competitor = branch.get("competitor", "")
        if not competitor:
            return []
        candidate_domains = [
            domain for domain in disambiguation.get("candidates", []) if domain
        ]
        candidate_line = (
            "Candidate domains to check: " + ", ".join(candidate_domains[:4])
            if candidate_domains
            else "No reliable candidate domain was found."
        )
        constraint = disambiguation.get("recommended_constraint") or f"{competitor} official site"
        return [
            {
                "objective": f"Disambiguate competitor identity for {competitor}",
                "query": "\n".join(
                    [
                        f"{competitor} official product website",
                        f"Competitor: {competitor}",
                        f"Research focus: {branch.get('dimension_name', branch.get('dimension_id', ''))}",
                        candidate_line,
                        f"Required constraint: {constraint}",
                        "Find public sources that clearly refer to the intended competitor, not a same-name company or unrelated product.",
                    ]
                ),
                "target_source_types": ["official_site"],
                "generated_from_gap": "competitor_disambiguation",
                "decision_action": "entity_resolution",
                "decision_subtype": "competitor_disambiguation",
                "reason": "Landscape scan could not bind candidate sources to the intended competitor.",
                "search_stage": "focused",
            }
        ]

    def _source_query(self, branch: ResearchBranch, source: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"Collect focused evidence from {source.get('url', '')}",
                f"Competitor: {branch.get('competitor', '')}",
                f"Research focus: {branch.get('dimension_name', branch.get('dimension_id', ''))}",
                "Use this candidate source only if it matches the competitor and dimension.",
            ]
        )

    def _source_type_query(self, branch: ResearchBranch, source_type: str) -> str:
        source_terms = {
            "pricing_page": "official pricing plans packaging",
            "official_site": "official product page",
            "docs": "documentation docs API security integration",
            "review": "customer reviews user feedback",
            "marketplace": "marketplace app store integrations listing",
            "news": "news announcement growth customers",
            "blog": "official blog product update",
        }
        return "\n".join(
            [
                f"{branch.get('competitor', '')} {branch.get('dimension_name', branch.get('dimension_id', ''))} {source_terms.get(source_type, source_type)}".strip(),
                f"Competitor: {branch.get('competitor', '')}",
                f"Target source type: {source_type}",
                "Prefer stable public URLs.",
            ]
        )

    def _competitor_disambiguation(
        self,
        branch: ResearchBranch,
        candidate_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        competitor = branch.get("competitor", "")
        if not competitor:
            return {"status": "unknown", "candidates": [], "recommended_constraint": ""}
        officialish = [
            source
            for source in candidate_sources
            if self._looks_official(source.get("url", ""), competitor)
        ]
        if officialish:
            return {
                "status": "clear",
                "candidates": [source.get("domain", "") for source in officialish[:3]],
                "recommended_constraint": "",
            }
        return {
            "status": "ambiguous" if candidate_sources else "unknown",
            "candidates": [source.get("domain", "") for source in candidate_sources[:3]],
            "recommended_constraint": f"{competitor} official site",
        }

    def _dimension_split_suggestions(self, branch: ResearchBranch) -> list[str]:
        if branch.get("dimension_id") == "competitive_moat":
            return [
                "switching_cost",
                "ecosystem_lock_in",
                "proprietary_data",
                "brand_distribution",
            ]
        return []

    def _split_task_specs(
        self,
        branch: ResearchBranch,
        split_suggestions: list[str],
    ) -> list[dict[str, Any]]:
        specs = []
        for suggestion in split_suggestions[:4]:
            split_name = suggestion.replace("_", " ").title()
            specs.append(
                {
                    "objective": f"Collect focused evidence for {split_name}",
                    "query": "\n".join(
                        [
                            f"{branch.get('competitor', '')} {split_name} public evidence".strip(),
                            f"Competitor: {branch.get('competitor', '')}",
                            f"Parent dimension: {branch.get('dimension_name', branch.get('dimension_id', ''))}",
                            f"Split focus: {split_name}",
                            "Prefer stable public URLs that directly address this split dimension.",
                        ]
                    ),
                    "dimension_id": f"{branch.get('dimension_id', 'dimension')}.{suggestion}",
                    "dimension_name": split_name,
                    "dimension_type": "dimension_split",
                    "parent_dimension_id": branch.get("dimension_id", ""),
                    "target_source_types": branch.get("expected_source_types", []),
                    "generated_from_gap": f"dimension_split:{suggestion}",
                    "decision_action": "scope_refinement",
                    "decision_subtype": "dimension_decomposition",
                    "reason": "Landscape scan marked this broad dimension as needing focused sub-dimensions.",
                    "search_stage": "focused",
                }
            )
        return specs

    def _decision(
        self,
        focused_task_specs: list[dict[str, Any]],
        disambiguation: dict[str, Any],
        split_task_specs: list[dict[str, Any]],
    ) -> dict[str, str]:
        if disambiguation.get("status") == "ambiguous" and focused_task_specs:
            return {
                "action": "entity_resolution",
                "subtype": "competitor_disambiguation",
                "rationale": "Candidate sources could not be safely bound to the intended competitor.",
            }
        if split_task_specs:
            return {
                "action": "scope_refinement",
                "subtype": "dimension_decomposition",
                "rationale": "The landscape dimension is broad enough to require narrower child dimensions.",
            }
        if focused_task_specs:
            if any(spec.get("search_stage") == "landscape" for spec in focused_task_specs):
                return {
                    "action": "scope_refinement",
                    "subtype": "query_refinement",
                    "rationale": "The landscape scan did not find a viable source universe entrance.",
                }
            if any(spec.get("target_urls") for spec in focused_task_specs):
                return {
                    "action": "evidence_extraction",
                    "subtype": "targeted_url_extract",
                    "rationale": "Landscape found concrete candidate URLs ready for focused extraction.",
                }
            return {
                "action": "source_discovery",
                "subtype": "source_type_search",
                "rationale": "Landscape identified missing source types that need focused source search.",
            }
        if disambiguation.get("status") == "clear":
            return {
                "action": "stop",
                "subtype": "sufficient_stop",
                "rationale": "The source universe is sufficiently clear and no follow-up task was required.",
            }
        return {
            "action": "stop",
            "subtype": "no_viable_followup",
            "rationale": "No viable landscape follow-up task was generated.",
        }

    def _summary(
        self,
        discovered_source_types: list[str],
        missing_source_types: list[str],
        focused_task_specs: list[dict[str, Any]],
        disambiguation: dict[str, Any],
    ) -> str:
        return (
            "Landscape scan discovered source types: "
            f"{', '.join(discovered_source_types) or 'none'}. "
            f"Missing source types: {', '.join(missing_source_types) or 'none'}. "
            f"Focused follow-up tasks: {len(focused_task_specs)}. "
            f"Competitor disambiguation: {disambiguation.get('status', 'unknown')}."
        )

    def _confidence(
        self,
        candidate_sources: list[dict[str, Any]],
        missing_source_types: list[str],
    ) -> float:
        score = 0.25 + min(0.45, 0.12 * len(candidate_sources))
        score -= 0.06 * len(missing_source_types)
        return round(max(0.0, min(1.0, score)), 2)

    def _source_url(self, source: dict[str, Any]) -> str:
        return source.get("url") or source.get("href") or ""

    def _refinement_query(
        self,
        branch: ResearchBranch,
        research_task: ResearchTask,
    ) -> str:
        return "\n".join(
            [
                f"Refine landscape search for {branch.get('competitor', '')} {branch.get('dimension_name', branch.get('dimension_id', ''))}".strip(),
                f"Research focus: {branch.get('dimension_name', branch.get('dimension_id', ''))}",
                f"Original query: {research_task.get('query', '')}",
                "Look for clearer source entrances, official domains, and disambiguating signals.",
            ]
        )

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

    def _looks_official(self, url: str, competitor: str) -> bool:
        if not url or not competitor:
            return False
        hostname = urlparse(url).netloc.lower()
        tokens = [token for token in competitor.lower().replace("-", " ").split() if token]
        return any(token in hostname for token in tokens)
