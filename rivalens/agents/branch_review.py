"""Review research branches before expanding collection work."""

from typing import Any

from rivalens.schema import BranchReviewDecision, EvidenceReviewResult, ResearchBranch


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
        evidence_review: EvidenceReviewResult | None = None,
    ) -> BranchReviewDecision:
        """Return a structured branch decision using schema and evidence gaps."""
        review_id = evidence_review.get("id", "") if evidence_review else ""
        relevant_evidence = [
            item
            for item in evidence_items
            if item.get("collection_task_id") == branch.get("id")
            or item.get("collection_task_id") == branch.get("collection_task_id")
        ]
        evidence_gaps = self._evidence_gaps(branch, relevant_evidence, evidence_review)

        if branch.get("depth", 0) >= self.max_depth:
            return self._stop(
                branch,
                ["Reached max branch depth."],
                relevant_evidence,
                evidence_review=evidence_review,
            )

        if evidence_review and evidence_review.get("required_action") == "fail":
            return {
                "branch_id": branch["id"],
                "evidence_review_id": review_id,
                "decision": "fail",
                "score": evidence_review.get("score", 0.0),
                "reasons": [
                    "Evidence quality review found a branch-level blocking mismatch.",
                ],
                "evidence_gaps": evidence_gaps,
                "next_topics": [],
                "next_queries": [],
                "drift_risk": "high",
            }

        if evidence_review and evidence_review.get("required_action") == "accept":
            return self._stop(
                branch,
                ["Evidence quality review accepted this branch."],
                relevant_evidence,
                evidence_review=evidence_review,
            )

        if len(relevant_evidence) >= self.min_sources_per_branch and not evidence_gaps:
            return self._stop(
                branch,
                ["Branch has enough source coverage for this pass."],
                relevant_evidence,
                evidence_review=evidence_review,
            )

        child_candidates = self._child_candidates(branch, evidence_gaps, root_query)
        approved_candidates = [
            candidate
            for candidate in child_candidates
            if candidate["drift_risk"] != "high"
        ]
        if not approved_candidates:
            return self._stop(
                branch,
                ["No schema-aligned child query survived drift review."],
                relevant_evidence,
                self._highest_drift_risk(child_candidates),
                evidence_review=evidence_review,
            )

        missing_sources = max(0, self.min_sources_per_branch - len(relevant_evidence))
        score = min(0.95, 0.45 + 0.15 * len(evidence_gaps) + 0.1 * missing_sources)
        decision = (
            "retry"
            if evidence_review and evidence_review.get("required_action") == "retry"
            else "expand"
        )
        return {
            "branch_id": branch["id"],
            "evidence_review_id": review_id,
            "decision": decision,
            "score": round(score, 2),
            "reasons": [
                "Evidence coverage is below the branch threshold or has source-quality gaps.",
                "Child queries remain aligned to the current competitor and schema dimension.",
            ],
            "evidence_gaps": evidence_gaps,
            "next_topics": [candidate["topic"] for candidate in approved_candidates],
            "next_queries": [candidate["query"] for candidate in approved_candidates],
            "drift_risk": self._highest_drift_risk(approved_candidates),
        }

    def _evidence_gaps(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult | None = None,
    ) -> list[str]:
        if evidence_review:
            review_gaps = [
                finding.get("code", "")
                for finding in evidence_review.get("findings", [])
                if finding.get("code")
            ]
            return list(dict.fromkeys(review_gaps))[:4]

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
        if (
            dimension_id
            in {"security_compliance", "admin_governance", "integration_ecosystem"}
            and "docs" not in source_types
        ):
            gaps.append("missing_docs_or_security_source")
        if dimension_id == "user_personas" and "review" not in source_types:
            gaps.append("missing_customer_or_review_source")

        return gaps[:4]

    def _candidate_drift_risk(
        self,
        branch: ResearchBranch,
        candidate_topic: str,
        gap: str,
    ) -> str:
        text = candidate_topic.lower()
        competitor = branch.get("competitor", "").lower()
        dimension_terms = [
            branch.get("dimension_id", "").replace("_", " ").lower(),
            branch.get("dimension_name", "").lower(),
        ]
        gap_terms = gap.replace("_", " ").lower().split()
        off_topic_terms = {
            "founder",
            "funding",
            "hiring",
            "culture",
            "history",
            "stock",
            "lawsuit",
        }

        has_competitor = bool(competitor and competitor in text)
        has_dimension = any(term and term in text for term in dimension_terms)
        has_gap_intent = any(term and term in text for term in gap_terms)
        has_off_topic = any(term in text for term in off_topic_terms)

        if has_off_topic:
            return "high"
        if has_competitor and (has_dimension or has_gap_intent):
            return "low"
        if has_competitor or has_dimension or has_gap_intent:
            return "medium"
        return "medium"

    def _child_candidates(
        self,
        branch: ResearchBranch,
        evidence_gaps: list[str],
        root_query: str,
    ) -> list[dict[str, str]]:
        competitor = branch.get("competitor", "") or "the competitor"
        dimension_name = branch.get("dimension_name", branch.get("dimension_id", ""))
        base = [
            root_query,
            f"Competitor: {competitor}",
            f"Research focus: {dimension_name}",
        ]
        templates = {
            "no_evidence": f"{competitor} {dimension_name} official evidence",
            "missing_source_url": f"{competitor} {dimension_name} official source URL",
            "insufficient_source_count": f"{competitor} {dimension_name} official evidence",
            "missing_official_source": (
                f"{competitor} {dimension_name} official page documentation"
            ),
            "missing_pricing_page": f"{competitor} pricing plans enterprise add-ons official",
            "missing_docs_or_security_source": (
                f"{competitor} {dimension_name} docs security compliance"
            ),
            "missing_customer_or_review_source": (
                f"{competitor} customer reviews personas use cases"
            ),
            "dimension_mismatch": f"{competitor} {dimension_name} schema-specific evidence",
        }
        candidates = []
        for gap in evidence_gaps:
            topic = templates.get(gap)
            if not topic:
                continue
            query = "\n".join(
                base
                + [
                    f"Child topic: {topic}",
                    f"Evidence gap: {gap}",
                    "Stay within the active schema dimension. Prefer public, source-backed pages.",
                ]
            )
            candidates.append(
                {
                    "topic": topic,
                    "query": query,
                    "gap": gap,
                    "drift_risk": self._candidate_drift_risk(branch, topic, gap),
                }
            )
        return candidates[: self.max_child_queries]

    def _highest_drift_risk(self, candidates: list[dict[str, str]]) -> str:
        if any(candidate.get("drift_risk") == "high" for candidate in candidates):
            return "high"
        if any(candidate.get("drift_risk") == "medium" for candidate in candidates):
            return "medium"
        return "low"

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
        evidence_review: EvidenceReviewResult | None = None,
    ) -> BranchReviewDecision:
        if evidence_review:
            score = evidence_review.get("score", 0.75 if evidence_items else 0.35)
        else:
            score = 0.75 if evidence_items else 0.35
        return {
            "branch_id": branch["id"],
            "evidence_review_id": evidence_review.get("id", "") if evidence_review else "",
            "decision": "stop",
            "score": score,
            "reasons": reasons,
            "evidence_gaps": self._evidence_gaps(branch, evidence_items, evidence_review),
            "next_topics": [],
            "next_queries": [],
            "drift_risk": drift_risk,
        }
