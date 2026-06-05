"""Coverage review for collection-stage research tasks."""

import re
from typing import Any
from urllib.parse import urlparse

from langsmith import traceable

from rivalens.agents.evidence_review import (
    _branch_trace_summary,
    _criteria_trace_summary,
    _evidence_trace_summary,
)
from rivalens.agents.success_criteria import (
    evidence_matches_success_criterion,
    normalize_success_criteria,
)
from rivalens.schema import CoverageAssessment, EvidenceReviewResult, ResearchBranch


def _follow_up_trace_summary(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "objective": spec.get("objective", ""),
            "query": spec.get("query", ""),
            "generated_from_gap": spec.get("generated_from_gap", ""),
            "decision_action": spec.get("decision_action", ""),
            "decision_subtype": spec.get("decision_subtype", ""),
            "target_source_types": list(spec.get("target_source_types", []))[:5],
            "success_criteria": _criteria_trace_summary(
                spec.get("success_criteria", []),
            ),
        }
        for spec in specs[:10]
        if isinstance(spec, dict)
    ]


def _coverage_review_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    branch = inputs.get("branch") or {}
    evidence_items = inputs.get("evidence_items") or []
    evidence_review = inputs.get("evidence_review") or {}
    return {
        "branch": _branch_trace_summary(branch),
        "research_task_ids": list(inputs.get("research_task_ids") or []),
        "evidence_count": len(evidence_items),
        "evidence": _evidence_trace_summary(evidence_items),
        "evidence_review": {
            "id": evidence_review.get("id", ""),
            "accepted": bool(evidence_review.get("accepted")),
            "required_action": evidence_review.get("required_action", ""),
            "score": evidence_review.get("score"),
            "accepted_evidence_ids": list(
                evidence_review.get("accepted_evidence_ids", []),
            )[:20],
            "rejected_evidence_ids": list(
                evidence_review.get("rejected_evidence_ids", []),
            )[:20],
            "criterion_matches": list(
                evidence_review.get("criterion_matches", []),
            )[:20],
        },
    }


def _coverage_review_trace_outputs(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"output_type": type(output).__name__}
    return {
        "coverage_id": output.get("id", ""),
        "branch_id": output.get("branch_id", ""),
        "next_action": output.get("next_action", ""),
        "confidence": output.get("confidence"),
        "decision": output.get("decision", {}),
        "accepted_evidence_ids": list(output.get("accepted_evidence_ids", []))[:20],
        "rejected_evidence_ids": list(output.get("rejected_evidence_ids", []))[:20],
        "found_source_types": list(output.get("found_source_types", []))[:10],
        "source_type_gaps": list(output.get("source_type_gaps", []))[:10],
        "source_coverage_gaps": list(output.get("source_coverage_gaps", []))[:10],
        "quality_gap_codes": list(output.get("quality_gap_codes", []))[:10],
        "covered_questions": list(output.get("covered_questions", []))[:10],
        "missing_questions": list(output.get("missing_questions", []))[:10],
        "satisfied_criteria": _criteria_trace_summary(
            output.get("satisfied_criteria", []),
        ),
        "partial_criteria": _criteria_trace_summary(
            output.get("partial_criteria", []),
        ),
        "missing_criteria": _criteria_trace_summary(
            output.get("missing_criteria", []),
        ),
        "criterion_matches": list(output.get("criterion_matches", []))[:20],
        "selected_follow_up_specs": _follow_up_trace_summary(
            output.get("selected_follow_up_specs", []),
        ),
        "arbitration": output.get("arbitration", {}),
    }


class CoverageReviewer:
    """Assess whether a branch has enough evidence coverage for analysis."""

    @traceable(
        name="rivalens_coverage_review",
        run_type="chain",
        tags=["rivalens", "collection", "coverage-review"],
        process_inputs=_coverage_review_trace_inputs,
        process_outputs=_coverage_review_trace_outputs,
    )
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
        found_source_types = self.found_source_types(branch, accepted_evidence)
        dimension_policy = self._dimension_policy(branch)
        source_type_gaps = self.source_type_gaps(
            branch,
            accepted_evidence,
            found_source_types,
        )
        quality_gap_codes = self.quality_gap_codes(evidence_review)
        guiding_questions = (
            branch.get("guiding_questions", [])
            or dimension_policy.get("guiding_questions", [])
        )
        success_criteria = normalize_success_criteria(
            branch.get("success_criteria", []),
        )
        covered_questions, missing_questions = self._question_coverage(
            guiding_questions,
            accepted_evidence,
            dimension_policy,
        )
        criterion_coverage = self._criterion_coverage(
            success_criteria,
            accepted_evidence,
            branch,
        )
        next_action = self._next_action(
            accepted_count=len(accepted_evidence),
            missing_questions=missing_questions,
            missing_criteria=criterion_coverage["missing_criteria"],
            source_type_gaps=source_type_gaps,
            evidence_review=evidence_review,
        )
        follow_up_specs = (
            self._follow_up_task_specs(
                branch,
                missing_questions,
                criterion_coverage["missing_criteria"],
                source_type_gaps,
                evidence_review,
            )
            if next_action in {"collect_more", "refine_query"}
            else []
        )
        routing = self._routing_from_review(
            branch=branch,
            evidence_review=evidence_review,
            missing_questions=missing_questions,
            next_action=next_action,
            follow_up_specs=follow_up_specs,
            confidence=self._confidence(
                len(accepted_evidence),
                missing_questions,
                source_type_gaps,
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
            "source_type_gaps": source_type_gaps,
            "source_coverage_gaps": source_type_gaps,
            "quality_gap_codes": quality_gap_codes,
            "covered_questions": covered_questions,
            "missing_questions": missing_questions,
            "satisfied_criteria": criterion_coverage["satisfied_criteria"],
            "partial_criteria": criterion_coverage["partial_criteria"],
            "missing_criteria": criterion_coverage["missing_criteria"],
            "criterion_matches": criterion_coverage["criterion_matches"],
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
        return {
            "search_stage": search_stage,
            "stage_role": "evidence_collection",
            "research_mode": "standard_evidence",
            "reviewer": "CoverageReviewer",
            "output_kind": "evidence_items",
            "produces_evidence": True,
            "state_sink": "coverage_assessments",
            "evidence_sink": "evidence_items",
        }

    def found_source_types(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        found = []
        for evidence in evidence_items:
            source_type = evidence.get("source_type", "other")
            if source_type and source_type not in found:
                found.append(source_type)
            if self.looks_official(evidence.get("url", ""), branch.get("competitor", "")):
                if "official_site" not in found:
                    found.append("official_site")
        return found

    def quality_gap_codes(self, evidence_review: EvidenceReviewResult) -> list[str]:
        return list(
            dict.fromkeys(
                str(finding.get("code", ""))
                for finding in evidence_review.get("findings", [])
                if finding.get("code")
            )
        )

    def source_type_gaps(
        self,
        branch: ResearchBranch,
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
    ) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        found = set(found_source_types)
        accepted_count = len(accepted_evidence)
        minimum_count = self._minimum_source_count(branch)
        if 0 < accepted_count < minimum_count:
            gaps.append(
                self._source_gap(
                    "insufficient_source_count",
                    "Collect additional independent public sources for this branch.",
                    self.fallback_target_source_types(branch),
                    accepted_count,
                    minimum_count,
                )
            )

        gaps.extend(
            self._preferred_source_type_gaps(
                branch,
                found,
                accepted_count,
                minimum_count,
            )
        )

        return gaps

    def _preferred_source_type_gaps(
        self,
        branch: ResearchBranch,
        found_source_types: set[str],
        accepted_count: int,
        minimum_count: int,
    ) -> list[dict[str, Any]]:
        preferred_source_types = self._preferred_source_types(branch)
        if not preferred_source_types or not accepted_count:
            return []
        if self._preferred_sources_matched(found_source_types, set(preferred_source_types)):
            return []
        return [
            self._source_gap(
                "missing_preferred_source_type",
                "Find preferred source-type evidence for this branch.",
                preferred_source_types,
                accepted_count,
                minimum_count,
                blocking=False,
            )
        ]

    def _source_gap(
        self,
        code: str,
        query_focus: str,
        target_source_types: list[str],
        accepted_count: int,
        minimum_count: int,
        blocking: bool = True,
        criterion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        gap = {
            "gap_type": "source_coverage",
            "code": code,
            "query_focus": query_focus,
            "target_source_types": target_source_types,
            "accepted_count": accepted_count,
            "minimum_count": minimum_count,
            "blocking": blocking,
            "reason": query_focus,
        }
        if criterion:
            gap["criterion_id"] = criterion.get("id", "")
            gap["criterion_description"] = criterion.get("description", "")
            gap["success_criteria"] = [criterion]
        return gap

    def _preferred_source_types(self, branch: ResearchBranch) -> list[str]:
        preferred = list(branch.get("target_source_types", []))
        if not preferred:
            preferred.extend(branch.get("source_hints", []))
        return list(dict.fromkeys(source_type for source_type in preferred if source_type))

    def _preferred_sources_matched(
        self,
        found_source_types: set[str],
        preferred_source_types: set[str],
    ) -> bool:
        return bool(found_source_types.intersection(preferred_source_types))

    def _minimum_source_count(self, branch: ResearchBranch) -> int:
        if self._normalize_dimension(branch.get("dimension_id", "")) == "competitor_profile":
            return 1
        return 2

    def fallback_target_source_types(self, branch: ResearchBranch) -> list[str]:
        source_hints = [
            source_type
            for source_type in branch.get("source_hints", [])
            if source_type
        ]
        return list(dict.fromkeys(source_hints[:3] or ["official_site", "news"]))

    def _source_type_gap_follow_up_spec(
        self,
        branch: ResearchBranch,
        gap: dict[str, Any],
    ) -> dict[str, Any]:
        target_source_types = list(gap.get("target_source_types", []))
        query_lines = [self._base_query(branch, str(gap.get("query_focus", "")))]
        if target_source_types:
            query_lines.append("Target source types: " + ", ".join(target_source_types))
        return {
            "objective": f"Resolve source coverage gap: {gap.get('code', '')}",
            "query": "\n".join(query_lines),
            "target_source_types": target_source_types,
            "success_criteria": list(gap.get("success_criteria", [])),
            "generated_from_gap": gap.get("code", ""),
            "triggering_finding_codes": [gap.get("code", "")],
            "baseline_accepted_count": int(gap.get("accepted_count", 0)),
            "decision_action": "source_discovery",
            "decision_subtype": "source_type_search",
            "reason": str(gap.get("query_focus", "")),
            "search_stage": "focused",
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "dimension_type": branch.get("dimension_type", ""),
            "parent_dimension_id": branch.get("parent_dimension_id", ""),
            "expected_claim_types": list(branch.get("expected_claim_types", [])),
        }

    def _question_coverage(
        self,
        guiding_questions: list[str],
        accepted_evidence: list[dict[str, Any]],
        dimension_policy: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        if not guiding_questions:
            return [], []
        if not accepted_evidence:
            return [], guiding_questions[:3]
        corpus = self._evidence_corpus(accepted_evidence)
        covered = []
        missing = []
        policy_terms = set(dimension_policy.get("coverage_terms", []))
        for question in guiding_questions:
            question_terms = self._question_terms(question)
            if not question_terms:
                question_terms = policy_terms
            overlap = [term for term in question_terms if term in corpus]
            if overlap or self._source_type_answers_question(question, accepted_evidence):
                covered.append(question)
            else:
                missing.append(question)
        return covered, missing[:3]

    def _next_action(
        self,
        accepted_count: int,
        missing_questions: list[str],
        missing_criteria: list[dict[str, Any]],
        source_type_gaps: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult,
    ) -> str:
        if accepted_count == 0:
            if evidence_review.get("required_action") == "retry":
                return "refine_query"
            return "collect_more"
        if source_type_gaps or missing_questions or missing_criteria:
            return "collect_more"
        return "ready_for_analysis"

    def _follow_up_task_specs(
        self,
        branch: ResearchBranch,
        missing_questions: list[str],
        missing_criteria: list[dict[str, Any]],
        source_type_gaps: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult,
    ) -> list[dict[str, Any]]:
        specs = []
        if evidence_review.get("required_action") == "retry":
            specs.append(
                {
                    "objective": f"Retry {branch.get('dimension_name', branch.get('dimension_id', 'research'))} collection for {branch.get('competitor', 'the competitor')}",
                    "query": self._base_query(branch, "official source URL"),
                    "generated_from_gap": "retry_source_quality",
                    "triggering_finding_codes": self.quality_gap_codes(evidence_review),
                    "baseline_accepted_count": len(evidence_review.get("accepted_evidence_ids", [])),
                    "decision_action": "scope_refinement",
                    "decision_subtype": "query_refinement",
                    "reason": "Source-level review rejected all usable evidence.",
                    "search_stage": "focused",
                    "dimension_id": branch.get("dimension_id", ""),
                    "dimension_name": branch.get("dimension_name", ""),
                    "dimension_type": branch.get("dimension_type", ""),
                    "parent_dimension_id": branch.get("parent_dimension_id", ""),
                }
            )
            return specs[:2]

        if self._has_finding(evidence_review, "no_evidence"):
            specs.append(
                {
                    "objective": f"Collect source-backed evidence for {branch.get('dimension_name', branch.get('dimension_id', 'research'))}",
                    "query": self._base_query(branch, "public source-backed evidence stable URL"),
                    "generated_from_gap": "no_evidence",
                    "triggering_finding_codes": ["no_evidence"],
                    "baseline_accepted_count": len(evidence_review.get("accepted_evidence_ids", [])),
                    "decision_action": "source_discovery",
                    "decision_subtype": "coverage_gap_search",
                    "reason": "Source-level review found no usable evidence for the branch.",
                    "search_stage": "focused",
                    "dimension_id": branch.get("dimension_id", ""),
                    "dimension_name": branch.get("dimension_name", ""),
                    "dimension_type": branch.get("dimension_type", ""),
                    "parent_dimension_id": branch.get("parent_dimension_id", ""),
                    "target_source_types": self.fallback_target_source_types(branch),
                    "expected_claim_types": list(branch.get("expected_claim_types", [])),
                }
            )

        for gap in source_type_gaps:
            specs.append(self._source_type_gap_follow_up_spec(branch, gap))
            if len(specs) >= 3:
                return specs[:3]

        for criterion in missing_criteria:
            gap = (
                "missing_guiding_question"
                if criterion.get("kind") == "guiding_question"
                else "missing_success_criterion"
            )
            description = str(criterion.get("description", "")).strip()
            specs.append(
                {
                    "objective": f"Answer missing success criterion: {description}",
                    "query": self._criterion_query(branch, criterion),
                    "success_criteria": [criterion],
                    "generated_from_gap": gap,
                    "triggering_finding_codes": [gap],
                    "baseline_accepted_count": len(evidence_review.get("accepted_evidence_ids", [])),
                    "decision_action": "source_discovery",
                    "decision_subtype": "coverage_gap_search",
                    "reason": "Coverage review found an unsatisfied success criterion.",
                    "search_stage": "focused",
                    "dimension_id": branch.get("dimension_id", ""),
                    "dimension_name": branch.get("dimension_name", ""),
                    "dimension_type": branch.get("dimension_type", ""),
                    "parent_dimension_id": branch.get("parent_dimension_id", ""),
                    "guiding_questions": [description] if criterion.get("kind") == "guiding_question" else [],
                }
            )
            if len(specs) >= 3:
                return specs[:3]

        for question in missing_questions:
            specs.append(
                {
                    "objective": f"Answer uncovered guiding question: {question}",
                    "query": self._question_query(branch, question),
                    "generated_from_gap": "missing_guiding_question",
                    "triggering_finding_codes": ["missing_guiding_question"],
                    "baseline_accepted_count": len(evidence_review.get("accepted_evidence_ids", [])),
                    "decision_action": "source_discovery",
                    "decision_subtype": "coverage_gap_search",
                    "reason": "Coverage review found an unanswered guiding question.",
                    "search_stage": "focused",
                    "dimension_id": branch.get("dimension_id", ""),
                    "dimension_name": branch.get("dimension_name", ""),
                    "dimension_type": branch.get("dimension_type", ""),
                    "parent_dimension_id": branch.get("parent_dimension_id", ""),
                    "guiding_questions": [question],
                }
            )
            if len(specs) >= 3:
                return specs[:3]
        return specs[:3]

    def _routing_from_review(
        self,
        branch: ResearchBranch,
        evidence_review: EvidenceReviewResult,
        missing_questions: list[str],
        next_action: str,
        follow_up_specs: list[dict[str, Any]],
        confidence: float,
    ) -> dict[str, Any]:
        candidates = self._decision_candidates(
            branch=branch,
            evidence_review=evidence_review,
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
        missing_questions: list[str],
        next_action: str,
        follow_up_specs: list[dict[str, Any]],
        confidence: float,
    ) -> list[dict[str, Any]]:
        candidates = [
            self._entity_resolution_candidate(branch, evidence_review),
            self._query_refinement_candidate(evidence_review, follow_up_specs),
            self._source_discovery_candidate(
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
            "triggering_finding_codes": ["competitor_mismatch"],
            "baseline_accepted_count": len(evidence_review.get("accepted_evidence_ids", [])),
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

    def _question_query(self, branch: ResearchBranch, question: str) -> str:
        return "\n".join(
            [
                self._base_query(branch, question),
                f"Guiding question to answer: {question}",
                "Return evidence that directly answers this question, not general company background.",
            ]
        )

    def _criterion_query(self, branch: ResearchBranch, criterion: dict[str, Any]) -> str:
        lines = [
            self._base_query(branch, str(criterion.get("description", ""))),
            f"Missing success criterion: {criterion.get('description', '')}",
            "Return evidence that directly satisfies this criterion.",
        ]
        return "\n".join(lines)

    def _base_query(self, branch: ResearchBranch, focus: str) -> str:
        return "\n".join(
            [
                f"{branch.get('competitor', '')} {branch.get('dimension_name', branch.get('dimension_id', ''))} {focus}".strip(),
                f"Competitor: {branch.get('competitor', '')}",
                f"Research focus: {branch.get('dimension_name', branch.get('dimension_id', ''))}",
                "Prefer public, source-backed pages with stable URLs.",
            ]
        )

    def _criterion_coverage(
        self,
        success_criteria: list[dict[str, Any]],
        accepted_evidence: list[dict[str, Any]],
        branch: ResearchBranch,
    ) -> dict[str, list[dict[str, Any]]]:
        satisfied = []
        partial = []
        missing = []
        matches = []

        for criterion in success_criteria:
            matched_evidence = [
                evidence
                for evidence in accepted_evidence
                if evidence_matches_success_criterion(evidence, criterion, branch)
            ]
            evidence_ids = [
                evidence.get("id", "")
                for evidence in matched_evidence
                if evidence.get("id")
            ]
            status = "missing"
            if evidence_ids:
                status = "satisfied"

            criterion_result = {
                **criterion,
                "evidence_ids": evidence_ids,
                "status": status,
            }
            matches.append(
                {
                    "criterion_id": criterion.get("id", ""),
                    "evidence_ids": evidence_ids,
                    "status": status,
                }
            )
            if status == "satisfied":
                satisfied.append(criterion_result)
            elif status == "partial":
                partial.append(criterion_result)
            else:
                missing.append(criterion_result)

        return {
            "satisfied_criteria": satisfied,
            "partial_criteria": partial,
            "missing_criteria": missing,
            "criterion_matches": matches,
        }

    def _confidence(
        self,
        accepted_count: int,
        missing_questions: list[str],
        source_type_gaps: list[dict[str, Any]],
    ) -> float:
        score = 0.35 + min(0.4, 0.15 * accepted_count)
        score -= 0.05 * len(missing_questions)
        score -= 0.06 * len(source_type_gaps)
        return round(max(0.0, min(1.0, score)), 2)

    def looks_official(self, url: str, competitor: str) -> bool:
        if not url or not competitor:
            return False
        hostname = urlparse(url).netloc.lower()
        tokens = [token for token in competitor.lower().replace("-", " ").split() if token]
        return any(token in hostname for token in tokens)

    def _dimension_policy(self, branch: ResearchBranch) -> dict[str, Any]:
        dimension_id = self._normalize_dimension(branch.get("dimension_id", ""))
        policies: dict[str, dict[str, Any]] = {
            "strategic_positioning": {
                "guiding_questions": [
                    "What positioning does the competitor use on official pages?",
                    "Which market segment or buyer does the competitor emphasize?",
                ],
                "coverage_terms": ["positioning", "segment", "market", "buyer", "official"],
            },
            "target_users": {
                "guiding_questions": [
                    "Which users or customer segments appear in public sources?",
                    "What use cases or jobs-to-be-done are supported by reviews or customer proof?",
                ],
                "coverage_terms": ["user", "customer", "review", "segment", "use", "persona"],
            },
            "user_personas": {
                "guiding_questions": [
                    "Which users or customer segments appear in public sources?",
                    "What use cases or jobs-to-be-done are supported by reviews or customer proof?",
                ],
                "coverage_terms": ["user", "customer", "review", "segment", "use", "persona"],
            },
            "product_capabilities": {
                "guiding_questions": [
                    "Which capabilities are stated on official product or documentation pages?",
                    "Which integrations or marketplace listings demonstrate capability breadth?",
                ],
                "coverage_terms": ["feature", "capability", "docs", "integration", "marketplace", "product"],
            },
            "feature_tree": {
                "guiding_questions": [
                    "Which capabilities are stated on official product or documentation pages?",
                    "Which integrations or marketplace listings demonstrate capability breadth?",
                ],
                "coverage_terms": ["feature", "capability", "docs", "integration", "marketplace", "product"],
            },
            "pricing_business_model": {
                "guiding_questions": [
                    "What public pricing, packaging, plans, or billing units are available?",
                    "Is there evidence of free tier, enterprise sales, or monetization model?",
                ],
                "coverage_terms": ["pricing", "price", "plan", "billing", "package", "enterprise", "free"],
            },
            "business_model_pricing": {
                "guiding_questions": [
                    "What public pricing, packaging, plans, or billing units are available?",
                    "Is there evidence of free tier, enterprise sales, or monetization model?",
                ],
                "coverage_terms": ["pricing", "price", "plan", "billing", "package", "enterprise", "free"],
            },
            "pricing_model": {
                "guiding_questions": [
                    "What public pricing, packaging, plans, or billing units are available?",
                    "Is there evidence of free tier, enterprise sales, or monetization model?",
                ],
                "coverage_terms": ["pricing", "price", "plan", "billing", "package", "enterprise", "free"],
            },
            "market_growth": {
                "guiding_questions": [
                    "What dated public signals show growth, traction, customers, funding, or expansion?",
                    "Which regions, verticals, or market opportunities are publicly evidenced?",
                ],
                "coverage_terms": ["growth", "customer", "funding", "launch", "market", "region", "expansion"],
            },
            "distribution_channels": {
                "guiding_questions": [
                    "Which channels, marketplaces, partner programs, or integrations distribute the product?",
                    "What evidence shows ecosystem or go-to-market distribution?",
                ],
                "coverage_terms": ["marketplace", "partner", "channel", "integration", "ecosystem", "distribution"],
            },
            "customer_proof": {
                "guiding_questions": [
                    "What reviews, testimonials, case studies, or customer logos support customer proof?",
                    "Are customer proof sources independent or only official?",
                ],
                "coverage_terms": ["review", "customer", "case", "testimonial", "logo", "rating"],
            },
            "technology_integrations": {
                "guiding_questions": [
                    "What docs, APIs, SDKs, integrations, or platform capabilities are public?",
                    "Which integration sources demonstrate technical maturity?",
                ],
                "coverage_terms": ["docs", "api", "sdk", "integration", "developer", "security", "platform"],
            },
            "compliance_risk": {
                "guiding_questions": [
                    "What trust, security, privacy, compliance, reliability, or risk evidence is public?",
                    "Are there public risk signals from news or policy documents?",
                ],
                "coverage_terms": ["security", "privacy", "compliance", "trust", "policy", "risk", "reliability"],
            },
            "competitive_moat": {
                "guiding_questions": [
                    "What evidence supports differentiation, switching costs, ecosystem lock-in, or proprietary advantage?",
                    "What public sources show substitution risk or defensibility?",
                ],
                "coverage_terms": ["differentiation", "switching", "ecosystem", "advantage", "moat", "risk", "defensible"],
            },
        }
        return policies.get(
            dimension_id,
            {
                "guiding_questions": [],
                "coverage_terms": [],
            },
        )

    def _evidence_corpus(self, evidence_items: list[dict[str, Any]]) -> set[str]:
        text = " ".join(
            str(item.get(field, ""))
            for item in evidence_items
            for field in ("title", "excerpt", "summary", "url", "source_type")
        )
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def _question_terms(self, question: str) -> set[str]:
        stopwords = {
            "and",
            "are",
            "does",
            "from",
            "how",
            "is",
            "of",
            "or",
            "the",
            "there",
            "to",
            "what",
            "which",
            "with",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", question.lower())
            if len(token) > 2 and token not in stopwords
        }

    def _source_type_answers_question(
        self,
        question: str,
        accepted_evidence: list[dict[str, Any]],
    ) -> bool:
        normalized_question = question.lower()
        source_types = {item.get("source_type", "other") for item in accepted_evidence}
        if any(term in normalized_question for term in ["pricing", "price", "billing"]):
            return "pricing_page" in source_types
        if any(term in normalized_question for term in ["review", "customer", "testimonial"]):
            return "review" in source_types or "news" in source_types
        if any(term in normalized_question for term in ["docs", "api", "security", "compliance"]):
            return "docs" in source_types
        if any(term in normalized_question for term in ["marketplace", "integration"]):
            return "marketplace" in source_types or "docs" in source_types
        return False

    def _normalize_dimension(self, value: str) -> str:
        return str(value or "").strip().lower().replace("-", "_")
