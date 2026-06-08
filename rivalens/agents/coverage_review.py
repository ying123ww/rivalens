"""Coverage review for collection-stage research tasks."""

import re
from typing import Any
from urllib.parse import urlparse

from rivalens.research.source_identity import identify_source_url
from rivalens.agents.source_gap_advisor import (
    LLMSourceGapAdvisor,
    SourceGapAdvisor,
    SourceGapDecision,
)
from rivalens.agents.success_criteria import (
    evidence_matches_success_criterion,
    normalize_success_criteria,
)
from rivalens.schema import (
    CoverageAssessment,
    EvidenceQualityStability,
    EvidenceReviewResult,
    QualityStabilityGap,
    ResearchBranch,
    SourceMetrics,
    TriggeredGapResolution,
)
from rivalens.schema.competitive import EvidenceType


class CoverageReviewer:
    """Assess whether a branch has enough evidence coverage for analysis."""

    def __init__(self, source_gap_advisor: SourceGapAdvisor | None = None) -> None:
        self.source_gap_advisor = source_gap_advisor or LLMSourceGapAdvisor()

    async def review(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult,
        source_metrics: SourceMetrics | None = None,
        research_task_ids: list[str] | None = None,
    ) -> CoverageAssessment:
        coverage_assessment_id = self._coverage_assessment_id(branch)
        accepted_ids = set(evidence_review.get("accepted_evidence_ids", []))
        rejected_ids = list(evidence_review.get("rejected_evidence_ids", []))
        accepted_evidence = [
            item
            for item in evidence_items
            if item.get("id", "") in accepted_ids
        ]
        found_source_types = self.found_source_types(branch, accepted_evidence)
        source_gap_assessment = await self.assess_source_type_gaps(
            branch,
            accepted_evidence,
            found_source_types,
            source_metrics or {},
        )
        source_type_gaps = source_gap_assessment["gaps"]
        quality_gap_codes = self.quality_gap_codes(evidence_review)
        quality_stability = self._quality_stability(
            evidence_items,
            evidence_review,
        )
        quality_stability_gaps = self._quality_stability_gaps(
            quality_stability,
        )
        guiding_questions = branch.get("guiding_questions", [])
        success_criteria = normalize_success_criteria(
            branch.get("success_criteria", []),
        )
        covered_questions, missing_questions = self._question_coverage(
            guiding_questions,
            accepted_evidence,
        )
        criterion_coverage = self._criterion_coverage(
            success_criteria,
            accepted_evidence,
            branch,
        )
        triggered_gap_resolution = self._triggered_gap_resolution(
            branch,
            accepted_evidence,
            found_source_types,
            quality_stability,
            quality_stability_gaps,
            criterion_coverage,
        )
        next_action = self._next_action(
            accepted_count=len(accepted_evidence),
            missing_questions=missing_questions,
            missing_criteria=criterion_coverage["missing_criteria"],
            source_type_gaps=source_type_gaps,
            quality_stability_gaps=quality_stability_gaps,
            evidence_review=evidence_review,
            triggered_gap_resolution=triggered_gap_resolution,
        )
        raw_follow_up_specs = (
            self._follow_up_task_specs(
                branch,
                missing_questions,
                criterion_coverage["missing_criteria"],
                source_type_gaps,
                quality_stability_gaps,
                evidence_review,
            )
            if next_action in {"collect_more", "refine_query"}
            else []
        )
        follow_up_specs = self._annotated_follow_up_specs(
            branch,
            coverage_assessment_id,
            evidence_review,
            raw_follow_up_specs,
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
            "id": coverage_assessment_id,
            "stage_contract": self._stage_contract(branch),
            "branch_id": branch.get("id", ""),
            "brief_id": branch.get("research_brief_id", ""),
            "research_task_ids": research_task_ids or [],
            "accepted_evidence_ids": list(accepted_ids),
            "rejected_evidence_ids": rejected_ids,
            "found_source_types": found_source_types,
            "source_type_gaps": source_type_gaps,
            "source_coverage_gaps": source_type_gaps,
            "source_gap_review": source_gap_assessment["review"],
            "source_metrics": source_metrics or {},
            "quality_stability": quality_stability,
            "quality_stability_gaps": quality_stability_gaps,
            "triggered_gap_resolution": triggered_gap_resolution,
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

    def _coverage_assessment_id(self, branch: ResearchBranch) -> str:
        return f"coverage_{branch.get('id', 'unknown')}"

    def _annotated_follow_up_specs(
        self,
        branch: ResearchBranch,
        coverage_assessment_id: str,
        evidence_review: EvidenceReviewResult,
        follow_up_specs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        annotated = []
        for spec in follow_up_specs:
            enriched = dict(spec)
            gap_code = str(enriched.get("generated_from_gap", ""))
            enriched.setdefault(
                "triggered_by_gap_type",
                self._follow_up_gap_type(enriched),
            )
            enriched.setdefault("triggered_by_gap_code", gap_code)
            enriched.setdefault("parent_branch_id", branch.get("id", ""))
            enriched.setdefault("triggered_by_branch_id", branch.get("id", ""))
            enriched.setdefault(
                "triggered_by_coverage_assessment_id",
                coverage_assessment_id,
            )
            enriched.setdefault(
                "triggered_by_evidence_review_id",
                evidence_review.get("id", ""),
            )
            criterion_id = self._follow_up_criterion_id(enriched)
            if criterion_id:
                enriched.setdefault("triggered_by_criterion_id", criterion_id)
            annotated.append(enriched)
        return annotated

    def _follow_up_gap_type(self, spec: dict[str, Any]) -> str:
        gap_code = str(spec.get("generated_from_gap", ""))
        if spec.get("quality_stability_baseline"):
            return "quality_stability"
        if spec.get("decision_subtype") == "source_type_search":
            return "source_coverage"
        if gap_code in {"missing_success_criterion", "missing_guiding_question"}:
            return "success_criterion"
        if spec.get("success_criteria"):
            return "success_criterion"
        if gap_code in {"retry_source_quality", "no_evidence"}:
            return "evidence_quality"
        return "coverage"

    def _follow_up_criterion_id(self, spec: dict[str, Any]) -> str:
        criteria = spec.get("success_criteria", []) or []
        if not criteria:
            return ""
        criterion = criteria[0]
        return str(criterion.get("id", "")) if isinstance(criterion, dict) else ""

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

    async def assess_source_type_gaps(
        self,
        branch: ResearchBranch,
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
        source_metrics: SourceMetrics,
    ) -> dict[str, Any]:
        accepted_count = len(accepted_evidence)
        minimum_count = self._minimum_source_count(branch)
        source_preferences = self._source_preferences(branch)
        review = {
            "mode": "llm_source_gap_advisor",
            "status": "skipped_no_accepted_evidence",
            "provider": getattr(self.source_gap_advisor, "provider", None),
            "model": getattr(self.source_gap_advisor, "model", None),
            "source_preferences": source_preferences,
            "found_source_types": found_source_types,
            "accepted_count": accepted_count,
            "minimum_count": minimum_count,
            "source_metrics_summary": self._source_metrics_summary(source_metrics),
            "no_rule_fallback": True,
        }
        if not accepted_evidence:
            return {"gaps": [], "review": review}

        try:
            raw_decision = await self.source_gap_advisor.decide(
                branch=branch,
                accepted_evidence=accepted_evidence,
                found_source_types=found_source_types,
                source_preferences=source_preferences,
                minimum_count=minimum_count,
                source_metrics=source_metrics,
            )
            decision = (
                raw_decision
                if isinstance(raw_decision, SourceGapDecision)
                else SourceGapDecision.model_validate(raw_decision)
            )
        except ValueError as exc:
            not_configured = "not configured" in str(exc).lower()
            review["status"] = "not_configured" if not_configured else "failed"
            review["error"] = str(exc)
            if not_configured:
                review["mode"] = "rule_fallback"
                return await self._rule_based_source_gap_assessment(
                    branch=branch,
                    accepted_evidence=accepted_evidence,
                    accepted_count=accepted_count,
                    minimum_count=minimum_count,
                    found_source_types=found_source_types,
                    source_preferences=source_preferences,
                    source_metrics=source_metrics,
                    review=review,
                )
            return {"gaps": [], "review": review}
        except Exception as exc:
            review["status"] = "failed"
            review["error"] = str(exc)
            return {"gaps": [], "review": review}

        decision.target_source_types = self._valid_source_types(
            decision.target_source_types,
        )
        decision.gap_code = self._slug(decision.gap_code)[:80]
        review.update(
            {
                "status": "completed",
                "decision": decision.model_dump(exclude={"metadata"}),
                "metadata": decision.metadata,
            }
        )
        if not decision.open_gap:
            return {"gaps": [], "review": review}

        gap_code = decision.gap_code or "llm_source_coverage_gap"
        query_focus = (
            decision.query_focus
            or decision.reason
            or "Collect targeted public sources to improve source coverage."
        )
        gap = self._source_gap(
            gap_code,
            query_focus,
            decision.target_source_types,
            accepted_count,
            minimum_count,
            blocking=bool(decision.blocking),
            reason=decision.reason,
            expected_improvement=decision.expected_improvement,
            confidence=decision.confidence,
        )
        return {"gaps": [gap], "review": review}

    def _source_metrics_summary(self, source_metrics: SourceMetrics) -> dict[str, Any]:
        return {
            "accepted_evidence_count": source_metrics.get("accepted_evidence_count", 0),
            "unique_canonical_url_count": source_metrics.get(
                "unique_canonical_url_count",
                0,
            ),
            "unique_domain_count": source_metrics.get("unique_domain_count", 0),
            "independent_source_count": source_metrics.get(
                "independent_source_count",
                0,
            ),
            "primary_source_count": source_metrics.get("primary_source_count", 0),
            "duplicate_group_count": len(source_metrics.get("duplicate_source_groups", [])),
        }

    def _quality_stability(
        self,
        evidence_items: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult,
    ) -> EvidenceQualityStability:
        accepted_count = len(evidence_review.get("accepted_evidence_ids", []))
        rejected_ids = set(evidence_review.get("rejected_evidence_ids", []))
        rejected_count = len(rejected_ids)
        total_count = accepted_count + rejected_count
        rejection_code_counts: dict[str, int] = {}
        high_severity_rejection_count = 0
        reliable_rejection_count = 0
        reliable_codes = {
            "missing_source_url",
            "low_quality_text",
            "no_success_criterion_match",
        }

        for finding in evidence_review.get("findings", []):
            evidence_id = finding.get("evidence_id")
            if evidence_id not in rejected_ids:
                continue
            code = str(finding.get("code", ""))
            if not code:
                continue
            rejection_code_counts[code] = rejection_code_counts.get(code, 0) + 1
            if finding.get("severity") == "high":
                high_severity_rejection_count += 1
            if code in reliable_codes:
                reliable_rejection_count += 1

        rejected_ratio = round(
            rejected_count / total_count,
            3,
        ) if total_count else 0.0
        status = "stable"
        if rejected_count:
            status = "mixed_quality"
        if total_count >= 3 and (
            rejected_ratio >= 0.67
            or high_severity_rejection_count >= 2
            or reliable_rejection_count >= 3
        ):
            status = "unstable"

        return {
            "status": status,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "total_evidence_count": total_count,
            "rejected_ratio": rejected_ratio,
            "high_severity_rejection_count": high_severity_rejection_count,
            "reliable_rejection_count": reliable_rejection_count,
            "rejection_code_counts": rejection_code_counts,
            "excluded_canonical_urls": self._rejected_canonical_urls(
                evidence_items,
                rejected_ids,
            ),
        }

    def _quality_stability_gaps(
        self,
        quality_stability: EvidenceQualityStability,
    ) -> list[QualityStabilityGap]:
        if quality_stability.get("status") != "unstable":
            return []

        rejection_code_counts = quality_stability.get("rejection_code_counts", {})
        triggering_codes = [
            code
            for code, _count in sorted(
                rejection_code_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ][:5]
        code = (
            "mixed_quality_high_rejected_ratio"
            if quality_stability.get("rejected_ratio", 0.0) >= 0.67
            else "mixed_quality_high_severity_rejections"
        )
        return [
            {
                "gap_type": "quality_stability",
                "code": code,
                "recommended_action": "refine_query",
                "accepted_count": int(quality_stability.get("accepted_count", 0)),
                "rejected_count": int(quality_stability.get("rejected_count", 0)),
                "total_evidence_count": int(
                    quality_stability.get("total_evidence_count", 0),
                ),
                "rejected_ratio": float(quality_stability.get("rejected_ratio", 0.0)),
                "high_severity_rejection_count": int(
                    quality_stability.get("high_severity_rejection_count", 0),
                ),
                "triggering_finding_codes": triggering_codes,
                "excluded_canonical_urls": list(
                    quality_stability.get("excluded_canonical_urls", []),
                ),
                "reason": (
                    "Most collected sources were rejected or unusable; retry with "
                    "a more stable source query before treating the branch as ready."
                ),
                "expected_improvement": (
                    "Reduce rejected evidence and collect readable, source-backed "
                    "evidence for the same branch."
                ),
                "blocking": False,
            }
        ]

    def _rejected_canonical_urls(
        self,
        evidence_items: list[dict[str, Any]],
        rejected_ids: set[str],
    ) -> list[str]:
        excluded = []
        for evidence in evidence_items:
            if evidence.get("id", "") not in rejected_ids:
                continue
            source_cache = evidence.get("source_cache") or {}
            canonical_url = (
                evidence.get("canonical_url")
                or source_cache.get("canonical_url")
                or identify_source_url(evidence.get("url", "")).canonical_url
            )
            if canonical_url and canonical_url not in excluded:
                excluded.append(canonical_url)
        return excluded

    def _triggered_gap_resolution(
        self,
        branch: ResearchBranch,
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
        quality_stability: EvidenceQualityStability,
        quality_stability_gaps: list[QualityStabilityGap],
        criterion_coverage: dict[str, list[dict[str, Any]]],
    ) -> TriggeredGapResolution:
        gap_type = str(branch.get("triggered_by_gap_type", ""))
        gap_code = str(
            branch.get("triggered_by_gap_code")
            or branch.get("generated_from_gap", ""),
        )
        if not branch.get("parent_id") or not gap_type or not gap_code:
            return {}

        if gap_type == "source_coverage":
            resolved_ids = self._source_resolution_evidence_ids(
                branch,
                accepted_evidence,
            )
            return self._triggered_resolution_payload(
                gap_type=gap_type,
                gap_code=gap_code,
                resolved_ids=resolved_ids,
                unresolved_reason="No accepted evidence matched the target source type.",
                reason="Accepted evidence matched the triggering source coverage target.",
            )

        if gap_type == "quality_stability":
            repeated_codes = {
                str(gap.get("code", ""))
                for gap in quality_stability_gaps
                if gap.get("code")
            }
            resolved = (
                quality_stability.get("status") != "unstable"
                and gap_code not in repeated_codes
                and bool(accepted_evidence)
            )
            resolved_ids = [
                evidence.get("id", "")
                for evidence in accepted_evidence
                if evidence.get("id")
            ] if resolved else []
            return self._triggered_resolution_payload(
                gap_type=gap_type,
                gap_code=gap_code,
                resolved_ids=resolved_ids,
                unresolved_reason="Follow-up evidence is still unstable or has no accepted evidence.",
                reason="Follow-up evidence quality stabilized for the triggering gap.",
            )

        if gap_type == "success_criterion":
            criterion_id = str(branch.get("triggered_by_criterion_id", ""))
            resolved_ids = self._criterion_resolution_evidence_ids(
                criterion_id,
                criterion_coverage,
            )
            return self._triggered_resolution_payload(
                gap_type=gap_type,
                gap_code=gap_code,
                resolved_ids=resolved_ids,
                unresolved_reason="The triggering success criterion is still unsatisfied.",
                reason="Accepted evidence satisfied the triggering success criterion.",
            )

        return {}

    def _source_resolution_evidence_ids(
        self,
        branch: ResearchBranch,
        accepted_evidence: list[dict[str, Any]],
    ) -> list[str]:
        target_source_types = set(branch.get("target_source_types", []))
        if not target_source_types:
            return []
        resolved_ids = []
        for evidence in accepted_evidence:
            source_type = evidence.get("source_type", "")
            if source_type in target_source_types or (
                "official_site" in target_source_types
                and self.looks_official(evidence.get("url", ""), branch.get("competitor", ""))
            ):
                evidence_id = evidence.get("id", "")
                if evidence_id:
                    resolved_ids.append(evidence_id)
        return list(dict.fromkeys(resolved_ids))

    def _criterion_resolution_evidence_ids(
        self,
        criterion_id: str,
        criterion_coverage: dict[str, list[dict[str, Any]]],
    ) -> list[str]:
        if not criterion_id:
            return []
        for match in criterion_coverage.get("criterion_matches", []):
            if match.get("criterion_id") != criterion_id:
                continue
            if match.get("status") != "satisfied":
                return []
            return list(match.get("evidence_ids", []))
        return []

    def _triggered_resolution_payload(
        self,
        *,
        gap_type: str,
        gap_code: str,
        resolved_ids: list[str],
        unresolved_reason: str,
        reason: str,
    ) -> TriggeredGapResolution:
        resolved = bool(resolved_ids)
        return {
            "scope": "gap_resolution",
            "gap_type": gap_type,
            "gap_code": gap_code,
            "status": "resolved" if resolved else "unresolved",
            "resolved_by_evidence_ids": resolved_ids,
            "unresolved_reason": "" if resolved else unresolved_reason,
            "reason": reason if resolved else "",
        }

    def _quality_stability_follow_up_spec(
        self,
        branch: ResearchBranch,
        gap: QualityStabilityGap,
    ) -> dict[str, Any]:
        excluded_urls = list(gap.get("excluded_canonical_urls", []))
        query_lines = [
            self._base_query(
                branch,
                "stable public source readable content",
            ),
            "Retry reason: previous collected sources were mostly unusable or off-target.",
            "Find a different stable public source with readable evidence.",
        ]
        if excluded_urls:
            query_lines.append(
                "Avoid previously unusable source URLs: "
                + ", ".join(excluded_urls[:5])
            )
        return {
            "objective": f"Refine collection after mixed-quality evidence: {gap.get('code', '')}",
            "query": "\n".join(query_lines),
            "generated_from_gap": gap.get("code", ""),
            "triggering_finding_codes": list(gap.get("triggering_finding_codes", [])),
            "baseline_accepted_count": int(gap.get("accepted_count", 0)),
            "decision_action": "scope_refinement",
            "decision_subtype": "query_refinement",
            "reason": str(gap.get("reason", "")),
            "retry_reason": str(gap.get("reason", "")),
            "expected_improvement": str(gap.get("expected_improvement", "")),
            "quality_stability_baseline": dict(gap),
            "excluded_canonical_urls": excluded_urls,
            "search_stage": "focused",
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "dimension_type": branch.get("dimension_type", ""),
            "parent_dimension_id": branch.get("parent_dimension_id", ""),
            "target_source_types": self.fallback_target_source_types(branch),
            "expected_claim_types": list(branch.get("expected_claim_types", [])),
        }

    def _source_gap(
        self,
        code: str,
        query_focus: str,
        target_source_types: list[str],
        accepted_count: int,
        minimum_count: int,
        blocking: bool = True,
        criterion: dict[str, Any] | None = None,
        reason: str | None = None,
        expected_improvement: str = "",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        gap = {
            "gap_type": "source_coverage",
            "code": code,
            "query_focus": query_focus,
            "target_source_types": target_source_types,
            "accepted_count": accepted_count,
            "minimum_count": minimum_count,
            "blocking": blocking,
            "reason": reason or query_focus,
            "source_gap_advisor": "llm",
        }
        if expected_improvement:
            gap["expected_improvement"] = expected_improvement
        if confidence is not None:
            gap["confidence"] = round(float(confidence), 3)
        if criterion:
            gap["criterion_id"] = criterion.get("id", "")
            gap["criterion_description"] = criterion.get("description", "")
            gap["success_criteria"] = [criterion]
        return gap

    def _source_preferences(self, branch: ResearchBranch) -> list[str]:
        preferred = list(branch.get("target_source_types", []))
        if not preferred:
            preferred.extend(branch.get("source_hints", []))
        return list(dict.fromkeys(source_type for source_type in preferred if source_type))

    def _valid_source_types(self, source_types: list[str]) -> list[str]:
        allowed = set(EvidenceType.__args__)
        return list(
            dict.fromkeys(
                source_type
                for source_type in source_types
                if source_type in allowed
            )
        )

    async def _rule_based_source_gap_assessment(
        self,
        *,
        branch: ResearchBranch,
        accepted_evidence: list[dict[str, Any]],
        accepted_count: int,
        minimum_count: int,
        found_source_types: list[str],
        source_preferences: list[str],
        source_metrics: SourceMetrics,
        review: dict[str, Any],
    ) -> dict[str, Any]:
        """Rule-based source coverage assessment when no LLM advisor is configured.

        Checks source type diversity, domain diversity, and evidence count
        against minimum thresholds to decide whether to open a source gap.
        """
        gaps: list[dict[str, Any]] = []

        unique_domains = source_metrics.get("unique_domain_count", 0)
        independent_count = source_metrics.get("independent_source_count", 0)
        unique_source_types = len(set(found_source_types)) if found_source_types else 0
        preferred_missing = [
            st for st in source_preferences
            if st not in set(found_source_types)
        ]

        # ── gap 1: count too low ──
        if accepted_count < minimum_count and accepted_evidence:
            gaps.append(self._source_gap(
                f"rule_count_below_minimum_{accepted_count}_of_{minimum_count}",
                f"Only {accepted_count} accepted source(s) — need {minimum_count}.",
                source_preferences or ["official_site", "news", "review"],
                accepted_count,
                minimum_count,
                blocking=True,
                reason=(
                    f"Accepted evidence count ({accepted_count}) is below "
                    f"the minimum ({minimum_count})."
                ),
                expected_improvement=(
                    f"Searching for additional public sources should raise "
                    f"accepted count to at least {minimum_count}."
                ),
                confidence=0.9,
            ))

        # ── gap 2: single source type only ──
        if unique_source_types <= 1 and accepted_count >= 2:
            target_types = preferred_missing[:3] or ["news", "review", "official_site"]
            gaps.append(self._source_gap(
                "rule_single_source_type",
                "Only one source type found — diversify sources.",
                target_types,
                accepted_count,
                minimum_count,
                blocking=False,
                reason=(
                    f"Found source types: {found_source_types}. "
                    "A single source type risks bias; need at least 2 types."
                ),
                expected_improvement="Adding a second source type improves traceability.",
                confidence=0.8,
            ))

        # ── gap 3: no independent source ──
        if independent_count == 0 and accepted_count >= 2:
            gaps.append(self._source_gap(
                "rule_no_independent_source",
                "Search for independent third-party coverage.",
                ["news", "review", "analyst_report", "academic"],
                accepted_count,
                minimum_count,
                blocking=False,
                reason="No independent (non-official) sources found.",
                expected_improvement="Independent sources add authority and reduce bias.",
                confidence=0.85,
            ))

        # ── gap 4: single domain only ──
        if unique_domains <= 1 and accepted_count >= 2:
            gaps.append(self._source_gap(
                "rule_single_domain",
                "All evidence from one domain — search for other publishers.",
                preferred_missing[:3] or ["news", "review"],
                accepted_count,
                minimum_count,
                blocking=False,
                reason=f"Only {unique_domains} unique domain(s).",
                expected_improvement="Multiple domains improve source independence.",
                confidence=0.85,
            ))

        # ── gap 5: preferred source types completely missing ──
        if preferred_missing and accepted_count >= minimum_count:
            gaps.append(self._source_gap(
                "rule_missing_preferred_types",
                f"Preferred source types not found: {', '.join(preferred_missing[:3])}.",
                preferred_missing[:3],
                accepted_count,
                minimum_count,
                blocking=False,
                reason=f"Missing preferred types: {', '.join(preferred_missing[:3])}.",
                expected_improvement="Targeted search for preferred source types.",
                confidence=0.7,
            ))

        review["gaps_found"] = len(gaps)
        return {"gaps": gaps, "review": review}

    def _slug(self, value: str) -> str:
        slug = "".join(
            character.lower() if character.isalnum() else "_"
            for character in value
        )
        return slug.strip("_")

    def _minimum_source_count(self, branch: ResearchBranch) -> int:
        raw_count = branch.get("minimum_source_count")
        if raw_count not in (None, ""):
            try:
                return max(1, int(raw_count))
            except (TypeError, ValueError):
                pass
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
            "guiding_questions": [
                criterion.get("description", "")
                for criterion in gap.get("success_criteria", [])
                if criterion.get("kind") == "guiding_question"
            ],
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
    ) -> tuple[list[str], list[str]]:
        if not guiding_questions:
            return [], []
        if not accepted_evidence:
            return [], guiding_questions[:3]
        corpus = self._evidence_corpus(accepted_evidence)
        covered = []
        missing = []
        for question in guiding_questions:
            question_terms = self._question_terms(question)
            overlap = [term for term in question_terms if term in corpus]
            if overlap:
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
        quality_stability_gaps: list[QualityStabilityGap],
        evidence_review: EvidenceReviewResult,
        triggered_gap_resolution: TriggeredGapResolution,
    ) -> str:
        if triggered_gap_resolution.get("status") == "resolved":
            return "ready_for_parent_merge"
        if accepted_count == 0:
            if evidence_review.get("required_action") == "retry":
                return "refine_query"
            return "collect_more"
        if quality_stability_gaps:
            if any(
                gap.get("recommended_action") == "refine_query"
                for gap in quality_stability_gaps
            ):
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
        quality_stability_gaps: list[QualityStabilityGap],
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

        for gap in quality_stability_gaps:
            specs.append(self._quality_stability_follow_up_spec(branch, gap))
            if len(specs) >= 3:
                return specs[:3]

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
            self._query_refinement_candidate(
                evidence_review,
                follow_up_specs,
                next_action,
            ),
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
        next_action: str,
    ) -> dict[str, Any]:
        refinement_specs = [
            spec
            for spec in follow_up_specs
            if spec.get("decision_action") == "scope_refinement"
        ]
        if (
            evidence_review.get("required_action") != "retry"
            and next_action != "refine_query"
        ) or not refinement_specs:
            return self._candidate("scope_refinement", "query_refinement", 0.0, [], [])
        return self._candidate(
            "scope_refinement",
            "query_refinement",
            0.86,
            ["Focused evidence needs query refinement before analysis."],
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
        if next_action == "ready_for_parent_merge":
            return self._candidate(
                "stop",
                "gap_resolution_complete",
                max(0.78, confidence),
                ["Triggered follow-up gap is resolved and ready to merge into parent coverage."],
                [],
            )
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
            ("stop", "gap_resolution_complete"): 3,
            ("stop", "sufficient_stop"): 4,
            ("stop", "no_viable_followup"): 5,
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
