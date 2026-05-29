"""Coverage review for collection-stage research tasks."""

from typing import Any
from urllib.parse import urlparse

from rivalens.schema import CoverageAssessment, EvidenceReviewResult, ResearchBranch


class CoverageReviewer:
    """Assess whether a branch has enough evidence coverage for analysis."""

    def review(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult,
        research_task_ids: list[str] | None = None,
    ) -> CoverageAssessment:
        accepted_ids = set(evidence_review.get("accepted_evidence_ids", []))
        rejected_ids = list(evidence_review.get("rejected_evidence_ids", []))
        accepted_evidence = [
            item
            for item in evidence_items
            if item.get("id", "") in accepted_ids
        ]
        found_source_types = self._found_source_types(branch, accepted_evidence)
        expected_source_types = branch.get("expected_source_types", []) or []
        missing_source_types = [
            source_type
            for source_type in expected_source_types
            if source_type not in found_source_types
        ]
        guiding_questions = branch.get("guiding_questions", []) or []
        covered_questions, missing_questions = self._question_coverage(
            guiding_questions,
            accepted_evidence,
            missing_source_types,
        )
        next_action = self._next_action(
            accepted_count=len(accepted_evidence),
            missing_source_types=missing_source_types,
            missing_questions=missing_questions,
            evidence_review=evidence_review,
        )
        follow_up_specs = (
            self._follow_up_task_specs(
                branch,
                missing_source_types,
                missing_questions,
                evidence_review,
            )
            if next_action in {"collect_more", "refine_query"}
            else []
        )
        routing = self._routing_from_review(
            branch=branch,
            evidence_review=evidence_review,
            missing_source_types=missing_source_types,
            missing_questions=missing_questions,
            next_action=next_action,
            follow_up_specs=follow_up_specs,
            confidence=self._confidence(
                len(accepted_evidence),
                missing_source_types,
                missing_questions,
            ),
        )

        return {
            "id": f"coverage_{branch.get('id', 'unknown')}",
            "stage_contract": self._stage_contract(branch),
            "branch_id": branch.get("id", ""),
            "brief_id": branch.get("research_brief_id", ""),
            "research_task_ids": research_task_ids or [],
            "accepted_evidence_ids": list(accepted_ids),
            "rejected_evidence_ids": rejected_ids,
            "found_source_types": found_source_types,
            "missing_source_types": missing_source_types,
            "covered_questions": covered_questions,
            "missing_questions": missing_questions,
            "contradictions": [],
            "next_action": next_action,
            "follow_up_task_specs": follow_up_specs,
            "selected_follow_up_specs": routing["selected_follow_up_specs"],
            "decision_candidates": routing["decision_candidates"],
            "arbitration": routing["arbitration"],
            "decision": routing["decision"],
            "confidence": routing["confidence"],
        }

    def _stage_contract(self, branch: ResearchBranch) -> dict[str, Any]:
        search_stage = branch.get("search_stage", "focused")
        is_verification = search_stage == "verification"
        return {
            "search_stage": search_stage,
            "stage_role": "claim_verification" if is_verification else "evidence_collection",
            "research_mode": "standard_evidence",
            "reviewer": "CoverageReviewer",
            "output_kind": "claim_evidence_items" if is_verification else "evidence_items",
            "produces_evidence": True,
            "state_sink": "coverage_assessments",
            "evidence_sink": "evidence_items",
        }

    def _found_source_types(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        found = []
        for evidence in evidence_items:
            source_type = evidence.get("source_type", "other")
            if source_type and source_type not in found:
                found.append(source_type)
            if self._looks_official(evidence.get("url", ""), branch.get("competitor", "")):
                if "official_site" not in found:
                    found.append("official_site")
        return found

    def _question_coverage(
        self,
        guiding_questions: list[str],
        accepted_evidence: list[dict[str, Any]],
        missing_source_types: list[str],
    ) -> tuple[list[str], list[str]]:
        if not guiding_questions:
            return [], []
        if not accepted_evidence:
            return [], guiding_questions[:3]
        if missing_source_types:
            return guiding_questions[:1], guiding_questions[1:3]
        return guiding_questions, []

    def _next_action(
        self,
        accepted_count: int,
        missing_source_types: list[str],
        missing_questions: list[str],
        evidence_review: EvidenceReviewResult,
    ) -> str:
        if accepted_count == 0:
            if evidence_review.get("required_action") == "retry":
                return "refine_query"
            return "collect_more"
        if missing_source_types:
            return "collect_more"
        if missing_questions:
            return "collect_more"
        return "ready_for_analysis"

    def _follow_up_task_specs(
        self,
        branch: ResearchBranch,
        missing_source_types: list[str],
        missing_questions: list[str],
        evidence_review: EvidenceReviewResult,
    ) -> list[dict[str, Any]]:
        specs = []
        if evidence_review.get("required_action") == "retry":
            specs.append(
                {
                    "objective": f"Retry {branch.get('dimension_name', branch.get('dimension_id', 'research'))} collection for {branch.get('competitor', 'the competitor')}",
                    "query": self._base_query(branch, "official source URL"),
                    "target_source_types": branch.get("expected_source_types", []),
                    "generated_from_gap": "retry_source_quality",
                    "decision_action": "scope_refinement",
                    "decision_subtype": "query_refinement",
                    "reason": "Source-level review rejected all usable evidence.",
                    "search_stage": "focused",
                }
            )
            return specs[:2]

        for source_type in missing_source_types[:2]:
            specs.append(
                {
                    "objective": f"Find {source_type} evidence for {branch.get('dimension_name', branch.get('dimension_id', 'research'))}",
                    "query": self._query_for_source_type(branch, source_type),
                    "target_source_types": [source_type],
                    "generated_from_gap": f"missing_source_type:{source_type}",
                    "decision_action": "source_discovery",
                    "decision_subtype": "coverage_gap_search",
                    "reason": f"Coverage review found no accepted {source_type} source.",
                    "search_stage": "focused",
                }
            )
        if not specs and missing_questions:
            question = missing_questions[0]
            specs.append(
                {
                    "objective": f"Answer uncovered guiding question: {question}",
                    "query": self._base_query(branch, question),
                    "target_source_types": branch.get("expected_source_types", []),
                    "generated_from_gap": "missing_guiding_question",
                    "decision_action": "source_discovery",
                    "decision_subtype": "coverage_gap_search",
                    "reason": "Coverage review found an unanswered guiding question.",
                    "search_stage": "focused",
                }
            )
        return specs[:2]

    def _routing_from_review(
        self,
        branch: ResearchBranch,
        evidence_review: EvidenceReviewResult,
        missing_source_types: list[str],
        missing_questions: list[str],
        next_action: str,
        follow_up_specs: list[dict[str, Any]],
        confidence: float,
    ) -> dict[str, Any]:
        candidates = self._decision_candidates(
            branch=branch,
            evidence_review=evidence_review,
            missing_source_types=missing_source_types,
            missing_questions=missing_questions,
            next_action=next_action,
            follow_up_specs=follow_up_specs,
            confidence=confidence,
        )
        ranked_candidates = sorted(
            candidates,
            key=lambda candidate: (
                -float(candidate.get("score", 0.0)),
                self._decision_tie_breaker(candidate),
            ),
        )
        winner = ranked_candidates[0]
        decision = {
            "action": winner["action"],
            "subtype": winner["subtype"],
            "rationale": "; ".join(winner.get("reasons", [])),
        }
        return {
            "decision": decision,
            "decision_candidates": ranked_candidates,
            "arbitration": {
                "method": "rules_scorecard",
                "winning_score": winner.get("score", 0.0),
                "candidate_count": len(ranked_candidates),
            },
            "selected_follow_up_specs": winner.get("follow_up_task_specs", []),
            "confidence": confidence,
        }

    def _decision_candidates(
        self,
        branch: ResearchBranch,
        evidence_review: EvidenceReviewResult,
        missing_source_types: list[str],
        missing_questions: list[str],
        next_action: str,
        follow_up_specs: list[dict[str, Any]],
        confidence: float,
    ) -> list[dict[str, Any]]:
        candidates = [
            self._entity_resolution_candidate(branch, evidence_review),
            self._query_refinement_candidate(evidence_review, follow_up_specs),
            self._source_discovery_candidate(
                missing_source_types,
                missing_questions,
                follow_up_specs,
            ),
            self._stop_candidate(next_action, confidence),
        ]
        return [
            candidate
            for candidate in candidates
            if float(candidate.get("score", 0.0)) > 0.0
        ] or [
            self._candidate(
                "stop",
                "no_viable_followup",
                0.4,
                ["Focused review produced no viable follow-up task."],
                [],
            )
        ]

    def _entity_resolution_candidate(
        self,
        branch: ResearchBranch,
        evidence_review: EvidenceReviewResult,
    ) -> dict[str, Any]:
        if not self._has_finding(evidence_review, "competitor_mismatch"):
            return self._candidate("entity_resolution", "competitor_disambiguation", 0.0, [], [])
        spec = {
            "objective": f"Disambiguate competitor identity for {branch.get('competitor', 'the competitor')}",
            "query": self._base_query(branch, "official product website"),
            "target_source_types": ["official_site"],
            "generated_from_gap": "competitor_disambiguation",
            "decision_action": "entity_resolution",
            "decision_subtype": "competitor_disambiguation",
            "reason": "Focused evidence review found competitor mismatch.",
            "search_stage": "focused",
        }
        return self._candidate(
            "entity_resolution",
            "competitor_disambiguation",
            0.9,
            ["Focused evidence review found competitor mismatch."],
            [spec],
        )

    def _query_refinement_candidate(
        self,
        evidence_review: EvidenceReviewResult,
        follow_up_specs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        refinement_specs = [
            spec
            for spec in follow_up_specs
            if spec.get("decision_action") == "scope_refinement"
        ]
        if evidence_review.get("required_action") != "retry" or not refinement_specs:
            return self._candidate("scope_refinement", "query_refinement", 0.0, [], [])
        return self._candidate(
            "scope_refinement",
            "query_refinement",
            0.86,
            ["Source-level review rejected all usable focused evidence."],
            refinement_specs,
        )

    def _source_discovery_candidate(
        self,
        missing_source_types: list[str],
        missing_questions: list[str],
        follow_up_specs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        discovery_specs = [
            spec
            for spec in follow_up_specs
            if spec.get("decision_action") == "source_discovery"
        ]
        if not discovery_specs:
            return self._candidate("source_discovery", "coverage_gap_search", 0.0, [], [])
        reasons = []
        score = 0.68
        if missing_source_types:
            score += min(0.16, 0.06 * len(missing_source_types))
            reasons.append(
                "Focused coverage is missing source types: "
                + ", ".join(missing_source_types)
                + "."
            )
        if missing_questions:
            score += 0.08
            reasons.append("Focused coverage has unanswered guiding questions.")
        return self._candidate(
            "source_discovery",
            "coverage_gap_search",
            round(min(score, 0.9), 2),
            reasons,
            discovery_specs,
        )

    def _stop_candidate(self, next_action: str, confidence: float) -> dict[str, Any]:
        if next_action != "ready_for_analysis":
            return self._candidate("stop", "sufficient_stop", 0.0, [], [])
        return self._candidate(
            "stop",
            "sufficient_stop",
            max(0.72, confidence),
            ["Focused evidence coverage is ready for analysis."],
            [],
        )

    def _candidate(
        self,
        action: str,
        subtype: str,
        score: float,
        reasons: list[str],
        follow_up_task_specs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "action": action,
            "subtype": subtype,
            "score": round(score, 2),
            "reasons": reasons,
            "follow_up_task_specs": follow_up_task_specs,
        }

    def _decision_tie_breaker(self, candidate: dict[str, Any]) -> int:
        priority = {
            ("entity_resolution", "competitor_disambiguation"): 0,
            ("scope_refinement", "query_refinement"): 1,
            ("source_discovery", "coverage_gap_search"): 2,
            ("stop", "sufficient_stop"): 3,
            ("stop", "no_viable_followup"): 4,
        }
        return priority.get((candidate.get("action"), candidate.get("subtype")), 99)

    def _has_finding(
        self,
        evidence_review: EvidenceReviewResult,
        code: str,
    ) -> bool:
        return any(
            finding.get("code") == code
            for finding in evidence_review.get("findings", [])
        )

    def _query_for_source_type(self, branch: ResearchBranch, source_type: str) -> str:
        source_terms = {
            "pricing_page": "official pricing plans packaging free tier enterprise",
            "official_site": "official product page positioning features",
            "docs": "documentation docs API security integration",
            "review": "customer reviews user feedback complaints praise",
            "marketplace": "marketplace app store integrations listing",
            "news": "news announcement launch growth customers funding",
            "blog": "official blog announcement product update",
        }
        return self._base_query(branch, source_terms.get(source_type, source_type.replace("_", " ")))

    def _base_query(self, branch: ResearchBranch, focus: str) -> str:
        return "\n".join(
            [
                f"{branch.get('competitor', '')} {branch.get('dimension_name', branch.get('dimension_id', ''))} {focus}".strip(),
                f"Competitor: {branch.get('competitor', '')}",
                f"Research focus: {branch.get('dimension_name', branch.get('dimension_id', ''))}",
                "Prefer public, source-backed pages with stable URLs.",
            ]
        )

    def _confidence(
        self,
        accepted_count: int,
        missing_source_types: list[str],
        missing_questions: list[str],
    ) -> float:
        score = 0.35 + min(0.4, 0.15 * accepted_count)
        score -= 0.08 * len(missing_source_types)
        score -= 0.05 * len(missing_questions)
        return round(max(0.0, min(1.0, score)), 2)

    def _looks_official(self, url: str, competitor: str) -> bool:
        if not url or not competitor:
            return False
        hostname = urlparse(url).netloc.lower()
        tokens = [token for token in competitor.lower().replace("-", " ").split() if token]
        return any(token in hostname for token in tokens)
