"""Review research branches before expanding collection work."""

from typing import Any

from rivalens.schema import BranchReviewDecision, ResearchBranch


class BranchReviewAgent:
    """Decide whether a research branch should expand, stop, or be redirected."""

    def __init__(
        self,
        min_sources_per_branch: int = 2,
        max_depth: int = 1,
        max_child_queries: int = 2,
    ):
        self.min_sources_per_branch = min_sources_per_branch
        self.max_depth = max_depth
        self.max_child_queries = max_child_queries

    def review(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
        active_schema: dict[str, Any],
        root_query: str,
    ) -> BranchReviewDecision:
        """Return a structured branch decision using schema and evidence gaps."""
        if branch.get("depth", 0) >= self.max_depth:
            return self._stop(branch, ["Reached max branch depth."], evidence_items)

        relevant_evidence = [
            item
            for item in evidence_items
            if item.get("collection_task_id") == branch.get("id")
            or item.get("collection_task_id") == branch.get("collection_task_id")
        ]
        evidence_gaps = self._evidence_gaps(branch, relevant_evidence)
        drift_risk = self._drift_risk(branch, root_query, active_schema)

        if drift_risk == "high":
            return self._stop(branch, ["Branch is likely drifting away from the active schema."], relevant_evidence, drift_risk)

        if len(relevant_evidence) >= self.min_sources_per_branch and not evidence_gaps:
            return self._stop(branch, ["Branch has enough source coverage for this pass."], relevant_evidence, drift_risk)

        next_queries = self._next_queries(branch, evidence_gaps, root_query)
        if not next_queries:
            return self._stop(branch, ["No useful schema-aligned child query was identified."], relevant_evidence, drift_risk)

        score = min(0.95, 0.45 + 0.15 * len(evidence_gaps) + 0.1 * max(0, self.min_sources_per_branch - len(relevant_evidence)))
        return {
            "branch_id": branch["id"],
            "decision": "expand",
            "score": round(score, 2),
            "reasons": [
                "Evidence coverage is below the branch threshold or has source-quality gaps.",
                "Child queries remain aligned to the current competitor and schema dimension.",
            ],
            "evidence_gaps": evidence_gaps,
            "next_topics": [query.splitlines()[0] for query in next_queries],
            "next_queries": next_queries,
            "drift_risk": drift_risk,
        }

    def _evidence_gaps(self, branch: ResearchBranch, evidence_items: list[dict[str, Any]]) -> list[str]:
        gaps = []
        source_types = {item.get("source_type", "other") for item in evidence_items}
        urls = [item.get("url", "") for item in evidence_items]
        dimension_id = branch.get("dimension_id", "")

        if len(evidence_items) < self.min_sources_per_branch:
            gaps.append("insufficient_source_count")
        if not any(self._looks_official(url, branch.get("competitor", "")) for url in urls):
            gaps.append("missing_official_source")
        if dimension_id == "pricing_model" and "pricing_page" not in source_types:
            gaps.append("missing_pricing_page")
        if dimension_id in {"security_compliance", "admin_governance", "integration_ecosystem"} and "docs" not in source_types:
            gaps.append("missing_docs_or_security_source")
        if dimension_id == "user_personas" and "review" not in source_types:
            gaps.append("missing_customer_or_review_source")

        return gaps[:4]

    def _drift_risk(
        self,
        branch: ResearchBranch,
        root_query: str,
        active_schema: dict[str, Any],
    ) -> str:
        text = " ".join(
            [
                branch.get("query", ""),
                branch.get("topic", ""),
                branch.get("dimension_name", ""),
                branch.get("competitor", ""),
                root_query,
            ]
        ).lower()
        allowed_terms = {
            branch.get("competitor", "").lower(),
            branch.get("dimension_id", "").replace("_", " ").lower(),
            branch.get("dimension_name", "").lower(),
            active_schema.get("selected_industry", {}).get("name", "").lower(),
        }
        allowed_terms.update(field.replace("_", " ").lower() for field in active_schema.get("core_fields", []))
        allowed_terms.update(
            extension.get("name", "").lower()
            for extension in active_schema.get("industry_extensions", [])
            if extension.get("name")
        )
        matched_terms = [term for term in allowed_terms if term and term in text]
        if matched_terms:
            return "low"
        return "medium"

    def _next_queries(
        self,
        branch: ResearchBranch,
        evidence_gaps: list[str],
        root_query: str,
    ) -> list[str]:
        competitor = branch.get("competitor", "") or "the competitor"
        dimension_name = branch.get("dimension_name", branch.get("dimension_id", ""))
        base = [
            root_query,
            f"Competitor: {competitor}",
            f"Research focus: {dimension_name}",
        ]
        templates = {
            "insufficient_source_count": f"{competitor} {dimension_name} official evidence",
            "missing_official_source": f"{competitor} {dimension_name} official page documentation",
            "missing_pricing_page": f"{competitor} pricing plans enterprise add-ons official",
            "missing_docs_or_security_source": f"{competitor} {dimension_name} docs security compliance",
            "missing_customer_or_review_source": f"{competitor} customer reviews personas use cases",
        }
        queries = []
        for gap in evidence_gaps:
            topic = templates.get(gap)
            if not topic:
                continue
            queries.append(
                "\n".join(
                    base
                    + [
                        f"Child topic: {topic}",
                        f"Evidence gap: {gap}",
                        "Stay within the active schema dimension. Prefer public, source-backed pages.",
                    ]
                )
            )
        return queries[: self.max_child_queries]

    def _looks_official(self, url: str, competitor: str) -> bool:
        if not url or not competitor:
            return False
        normalized_url = url.lower()
        tokens = [token for token in competitor.lower().replace("-", " ").split() if token]
        return any(token in normalized_url for token in tokens)

    def _stop(
        self,
        branch: ResearchBranch,
        reasons: list[str],
        evidence_items: list[dict[str, Any]],
        drift_risk: str = "low",
    ) -> BranchReviewDecision:
        score = 0.75 if evidence_items else 0.35
        return {
            "branch_id": branch["id"],
            "decision": "stop",
            "score": score,
            "reasons": reasons,
            "evidence_gaps": self._evidence_gaps(branch, evidence_items),
            "next_topics": [],
            "next_queries": [],
            "drift_risk": drift_risk,
        }
