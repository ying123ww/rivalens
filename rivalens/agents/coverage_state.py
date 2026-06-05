"""Build root-branch coverage state from collection reviews."""

from typing import Any

from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.success_criteria import (
    evidence_matches_success_criterion,
    normalize_success_criteria,
)
from rivalens.schema import (
    BranchImprovementAssessment,
    BranchCoverageState,
    CoverageAssessment,
    EvidenceItem,
    EvidenceReviewResult,
    ResearchBranch,
)


class BranchCoverageStateBuilder:
    """Aggregate a root branch and its follow-ups into a coverage ledger."""

    def __init__(self, coverage_reviewer: CoverageReviewer):
        self.coverage_reviewer = coverage_reviewer

    def build(
        self,
        research_branches: list[ResearchBranch],
        evidence_reviews: list[EvidenceReviewResult],
        evidence_items: list[EvidenceItem],
        coverage_assessments: list[CoverageAssessment],
    ) -> list[BranchCoverageState]:
        children_by_parent: dict[str, list[ResearchBranch]] = {}
        for branch in research_branches:
            parent_id = branch.get("parent_id")
            if parent_id:
                children_by_parent.setdefault(parent_id, []).append(branch)

        reviews_by_branch: dict[str, list[EvidenceReviewResult]] = {}
        for review in evidence_reviews:
            reviews_by_branch.setdefault(review.get("branch_id", ""), []).append(review)

        assessments_by_branch: dict[str, list[CoverageAssessment]] = {}
        for assessment in coverage_assessments:
            assessments_by_branch.setdefault(
                assessment.get("branch_id", ""),
                [],
            ).append(assessment)

        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }

        states: list[BranchCoverageState] = []
        for root in research_branches:
            if root.get("parent_id"):
                continue
            root_id = root.get("id", "")
            branch_ids = self._branch_lineage_ids(root_id, children_by_parent)
            accepted_evidence_ids = self._accepted_evidence_ids(
                [
                    review
                    for branch_id in branch_ids
                    for review in reviews_by_branch.get(branch_id, [])
                ],
            )
            accepted_evidence = [
                evidence_by_id[evidence_id]
                for evidence_id in accepted_evidence_ids
                if evidence_id in evidence_by_id
            ]
            found_source_types = self.coverage_reviewer.found_source_types(
                root,
                accepted_evidence,
            )
            current_source_type_gaps = self._open_recorded_source_type_gaps(
                root,
                branch_ids,
                accepted_evidence,
                assessments_by_branch,
            )
            open_source_type_gap_codes = {
                str(gap.get("code", ""))
                for gap in current_source_type_gaps
                if gap.get("code")
            }
            open_blocking_source_type_gap_codes = {
                str(gap.get("code", ""))
                for gap in current_source_type_gaps
                if gap.get("code") and gap.get("blocking", True)
            }
            success_criteria = self._cumulative_success_criteria(
                root,
                accepted_evidence,
            )
            coverage_gaps = self._cumulative_coverage_gaps(
                root,
                branch_ids,
                accepted_evidence,
                assessments_by_branch,
                open_source_type_gap_codes,
            )
            coverage_gaps.extend(
                self._cumulative_criterion_gaps(
                    root,
                    branch_ids,
                    success_criteria,
                    accepted_evidence,
                    assessments_by_branch,
                ),
            )
            improvement_assessments = self._improvement_assessments(
                root,
                branch_ids,
                children_by_parent,
                assessments_by_branch,
                coverage_gaps,
            )
            unresolved_criteria = [
                criterion
                for criterion in success_criteria
                if criterion.get("status") in {"missing", "partial"}
            ]
            open_criterion_gap_codes = {
                "missing_guiding_question"
                if criterion.get("kind") == "guiding_question"
                else "missing_success_criterion"
                for criterion in unresolved_criteria
            }
            open_gap_codes = open_source_type_gap_codes | open_criterion_gap_codes
            blocking_gap_codes = (
                open_blocking_source_type_gap_codes | open_criterion_gap_codes
            )
            status = (
                "ready_for_analysis"
                if not blocking_gap_codes and not unresolved_criteria
                else "blocked"
            )
            states.append(
                {
                    "id": f"coverage_state_{root_id}",
                    "root_branch_id": root_id,
                    "branch_ids": branch_ids,
                    "competitor": root.get("competitor", ""),
                    "analysis_dimension_id": root.get(
                        "analysis_dimension_id",
                        root.get("dimension_id", ""),
                    ),
                    "dimension_id": root.get("dimension_id", ""),
                    "dimension_name": root.get("dimension_name", ""),
                    "status": status,
                    "accepted_evidence_ids": accepted_evidence_ids,
                    "found_source_types": found_source_types,
                    "success_criteria": success_criteria,
                    "coverage_gaps": coverage_gaps,
                    "improvement_assessments": improvement_assessments,
                    "open_gap_codes": sorted(open_gap_codes),
                    "resolved_gap_codes": sorted(
                        {
                            gap.get("code", "")
                            for gap in coverage_gaps
                            if gap.get("status") == "resolved"
                        },
                    ),
                    "blocked_gap_codes": sorted(
                        {
                            gap.get("code", "")
                            for gap in coverage_gaps
                            if gap.get("status") == "blocked"
                        },
                    ),
                },
            )
        return states

    def attach_to_root_branches(
        self,
        research_branches: list[ResearchBranch],
        branch_coverage_states: list[BranchCoverageState],
    ) -> None:
        state_by_root = {
            state.get("root_branch_id", ""): state
            for state in branch_coverage_states
            if state.get("root_branch_id")
        }
        for branch in research_branches:
            state = state_by_root.get(branch.get("id", ""))
            if not state:
                continue
            branch["coverage_state_id"] = state.get("id", "")
            branch["coverage_status"] = state.get("status", "")

    def _branch_lineage_ids(
        self,
        root_branch_id: str,
        children_by_parent: dict[str, list[ResearchBranch]],
    ) -> list[str]:
        ordered = []
        frontier = [root_branch_id]
        while frontier:
            branch_id = frontier.pop(0)
            if branch_id in ordered:
                continue
            ordered.append(branch_id)
            frontier.extend(
                child.get("id", "")
                for child in children_by_parent.get(branch_id, [])
                if child.get("id")
            )
        return ordered

    def _cumulative_success_criteria(
        self,
        root: ResearchBranch,
        accepted_evidence: list[EvidenceItem],
    ) -> list[dict[str, Any]]:
        results = []
        for criterion in normalize_success_criteria(root.get("success_criteria", [])):
            matched_evidence = [
                evidence
                for evidence in accepted_evidence
                if evidence_matches_success_criterion(evidence, criterion, root)
            ]
            evidence_ids = [
                evidence.get("id", "")
                for evidence in matched_evidence
                if evidence.get("id")
            ]
            status = "missing"
            if evidence_ids:
                status = "satisfied"
            results.append(
                {
                    **criterion,
                    "evidence_ids": evidence_ids,
                    "status": status,
                },
            )
        return results

    def _cumulative_coverage_gaps(
        self,
        root: ResearchBranch,
        branch_ids: list[str],
        accepted_evidence: list[EvidenceItem],
        assessments_by_branch: dict[str, list[CoverageAssessment]],
        open_gap_codes: set[str],
    ) -> list[dict[str, Any]]:
        gaps = []
        seen_gap_ids: set[str] = set()
        for branch_id in branch_ids:
            for assessment in assessments_by_branch.get(branch_id, []):
                for gap in self._assessment_source_gaps(assessment):
                    code = str(gap.get("code", ""))
                    if not code:
                        continue
                    criterion_id = str(gap.get("criterion_id", ""))
                    gap_id_parts = [
                        "gap",
                        str(assessment.get("id", branch_id)),
                        code,
                    ]
                    if criterion_id:
                        gap_id_parts.append(criterion_id)
                    gap_id = "_".join(gap_id_parts)
                    if gap_id in seen_gap_ids:
                        continue
                    seen_gap_ids.add(gap_id)
                    resolved_evidence_ids = self._resolved_evidence_ids_for_gap(
                        root,
                        gap,
                        accepted_evidence,
                    )
                    resolved_branch_ids = list(
                        dict.fromkeys(
                            evidence.get("branch_id", "")
                            for evidence in accepted_evidence
                            if evidence.get("id", "") in resolved_evidence_ids
                            and evidence.get("branch_id")
                        ),
                    )
                    blocking = bool(gap.get("blocking", True))
                    status = "resolved"
                    if code in open_gap_codes:
                        status = "blocked" if blocking else "open"
                    gaps.append(
                        {
                            "id": gap_id,
                            "gap_type": "source_type",
                            "code": code,
                            "criterion_id": criterion_id,
                            "description": str(
                                gap.get("criterion_description")
                                or gap.get("query_focus", ""),
                            ),
                            "blocking": blocking,
                            "status": status,
                            "root_branch_id": root.get("id", ""),
                            "opened_by_branch_id": branch_id,
                            "opened_by_coverage_assessment_id": assessment.get("id", ""),
                            "target_source_types": list(gap.get("target_source_types", [])),
                            "baseline_accepted_count": int(gap.get("accepted_count", 0)),
                            "resolved_by_branch_ids": resolved_branch_ids
                            if status == "resolved"
                            else [],
                            "resolved_by_evidence_ids": resolved_evidence_ids
                            if status == "resolved"
                            else [],
                            "reason": str(gap.get("query_focus", "")),
                        },
                    )
        return gaps

    def _open_recorded_source_type_gaps(
        self,
        root: ResearchBranch,
        branch_ids: list[str],
        accepted_evidence: list[EvidenceItem],
        assessments_by_branch: dict[str, list[CoverageAssessment]],
    ) -> list[dict[str, Any]]:
        gaps = []
        for branch_id in branch_ids:
            for assessment in assessments_by_branch.get(branch_id, []):
                for gap in self._assessment_source_gaps(assessment):
                    code = str(gap.get("code", ""))
                    if not code:
                        continue
                    if self._resolved_evidence_ids_for_gap(
                        root,
                        gap,
                        accepted_evidence,
                    ):
                        continue
                    gaps.append(gap)
        return gaps

    def _assessment_source_gaps(
        self,
        assessment: CoverageAssessment,
    ) -> list[dict[str, Any]]:
        return list(
            assessment.get("source_coverage_gaps")
            or assessment.get("source_type_gaps", [])
        )

    def _cumulative_criterion_gaps(
        self,
        root: ResearchBranch,
        branch_ids: list[str],
        final_success_criteria: list[dict[str, Any]],
        accepted_evidence: list[EvidenceItem],
        assessments_by_branch: dict[str, list[CoverageAssessment]],
    ) -> list[dict[str, Any]]:
        final_by_id = {
            criterion.get("id", ""): criterion
            for criterion in final_success_criteria
            if criterion.get("id")
        }
        gaps = []
        seen_gap_ids: set[str] = set()
        for branch_id in branch_ids:
            for assessment in assessments_by_branch.get(branch_id, []):
                criteria_with_status = [
                    *assessment.get("missing_criteria", []),
                    *assessment.get("partial_criteria", []),
                ]
                for criterion in criteria_with_status:
                    criterion_id = str(criterion.get("id", ""))
                    if not criterion_id:
                        continue
                    code = (
                        "missing_guiding_question"
                        if criterion.get("kind") == "guiding_question"
                        else "missing_success_criterion"
                    )
                    gap_id = f"gap_{assessment.get('id', branch_id)}_{code}_{criterion_id}"
                    if gap_id in seen_gap_ids:
                        continue
                    seen_gap_ids.add(gap_id)
                    final_criterion = final_by_id.get(criterion_id, {})
                    status = (
                        "resolved"
                        if final_criterion.get("status") == "satisfied"
                        else "blocked"
                    )
                    resolved_evidence_ids = list(
                        final_criterion.get("evidence_ids", []),
                    ) if status == "resolved" else []
                    resolved_branch_ids = list(
                        dict.fromkeys(
                            evidence.get("branch_id", "")
                            for evidence in accepted_evidence
                            if evidence.get("id", "") in resolved_evidence_ids
                            and evidence.get("branch_id")
                        ),
                    )
                    gaps.append(
                        {
                            "id": gap_id,
                            "gap_type": "success_criterion",
                            "code": code,
                            "criterion_id": criterion_id,
                            "description": str(criterion.get("description", "")),
                            "status": status,
                            "root_branch_id": root.get("id", ""),
                            "opened_by_branch_id": branch_id,
                            "opened_by_coverage_assessment_id": assessment.get("id", ""),
                            "baseline_accepted_count": len(
                                assessment.get("accepted_evidence_ids", []),
                            ),
                            "resolved_by_branch_ids": resolved_branch_ids
                            if status == "resolved"
                            else [],
                            "resolved_by_evidence_ids": resolved_evidence_ids
                            if status == "resolved"
                            else [],
                            "reason": str(criterion.get("description", "")),
                        },
                    )
        return gaps

    def _improvement_assessments(
        self,
        root: ResearchBranch,
        branch_ids: list[str],
        children_by_parent: dict[str, list[ResearchBranch]],
        assessments_by_branch: dict[str, list[CoverageAssessment]],
        coverage_gaps: list[dict[str, Any]],
    ) -> list[BranchImprovementAssessment]:
        assessments = []
        assessment_by_id = {
            assessment.get("id", ""): assessment
            for branch_id in branch_ids
            for assessment in assessments_by_branch.get(branch_id, [])
            if assessment.get("id")
        }

        for parent_id in branch_ids:
            for child in children_by_parent.get(parent_id, []):
                child_id = child.get("id", "")
                if child_id not in branch_ids:
                    continue
                gap_code = str(
                    child.get("triggered_by_gap_code")
                    or child.get("generated_from_gap", "")
                )
                if not gap_code:
                    continue
                follow_up_assessment = self._latest_assessment(
                    assessments_by_branch,
                    child_id,
                )
                if not follow_up_assessment:
                    continue

                baseline_assessment_id = str(
                    child.get("triggered_by_coverage_assessment_id", ""),
                )
                baseline_assessment = assessment_by_id.get(
                    baseline_assessment_id,
                ) or self._latest_assessment(assessments_by_branch, parent_id)
                if not baseline_assessment:
                    continue

                gap_type = str(
                    child.get("triggered_by_gap_type")
                    or self._infer_gap_type(gap_code, child),
                )
                criterion_id = str(child.get("triggered_by_criterion_id", ""))
                resolved_gap = self._resolved_gap(
                    gap_type,
                    gap_code,
                    criterion_id,
                    baseline_assessment,
                    follow_up_assessment,
                    coverage_gaps,
                )
                resolution = self._resolution_provenance(
                    gap_type,
                    gap_code,
                    criterion_id,
                    baseline_assessment,
                    follow_up_assessment,
                    coverage_gaps,
                    resolved_gap,
                )
                assessments.append(
                    self._build_improvement_assessment(
                        root=root,
                        parent_branch_id=parent_id,
                        child=child,
                        gap_type=gap_type,
                        gap_code=gap_code,
                        criterion_id=criterion_id,
                        baseline_assessment=baseline_assessment,
                        follow_up_assessment=follow_up_assessment,
                        resolved_gap=resolved_gap,
                        resolution=resolution,
                    ),
                )
        return assessments

    def _build_improvement_assessment(
        self,
        *,
        root: ResearchBranch,
        parent_branch_id: str,
        child: ResearchBranch,
        gap_type: str,
        gap_code: str,
        criterion_id: str,
        baseline_assessment: CoverageAssessment,
        follow_up_assessment: CoverageAssessment,
        resolved_gap: bool,
        resolution: dict[str, Any],
    ) -> BranchImprovementAssessment:
        baseline = self._assessment_snapshot(baseline_assessment)
        follow_up = self._assessment_snapshot(follow_up_assessment)
        deltas = self._snapshot_deltas(baseline, follow_up)
        improved_signals, regression_signals = self._improvement_signals(
            gap_type,
            baseline,
            follow_up,
            deltas,
            resolved_gap,
            list(child.get("target_source_types", [])),
        )
        status = self._improvement_status(
            resolved_gap,
            improved_signals,
            regression_signals,
        )
        child_id = child.get("id", "")
        return {
            "id": "_".join(
                [
                    "improvement",
                    root.get("id", "root"),
                    parent_branch_id,
                    child_id,
                    gap_code,
                ],
            ),
            "root_branch_id": root.get("id", ""),
            "parent_branch_id": parent_branch_id,
            "follow_up_branch_id": child_id,
            "gap_type": gap_type,
            "gap_code": gap_code,
            "criterion_id": criterion_id,
            "baseline_coverage_assessment_id": baseline_assessment.get("id", ""),
            "follow_up_coverage_assessment_id": follow_up_assessment.get("id", ""),
            "status": status,
            "baseline": baseline,
            "follow_up": follow_up,
            "deltas": deltas,
            "resolved_gap": resolved_gap,
            "resolved_gap_codes": list(resolution.get("resolved_gap_codes", [])),
            "unresolved_gap_codes": list(resolution.get("unresolved_gap_codes", [])),
            "resolved_by_branch_ids": list(
                resolution.get("resolved_by_branch_ids", []),
            ),
            "resolved_by_evidence_ids": list(
                resolution.get("resolved_by_evidence_ids", []),
            ),
            "improved_signals": improved_signals,
            "regression_signals": regression_signals,
            "notes": self._improvement_notes(status, improved_signals, regression_signals),
        }

    def _resolution_provenance(
        self,
        gap_type: str,
        gap_code: str,
        criterion_id: str,
        baseline_assessment: CoverageAssessment,
        follow_up_assessment: CoverageAssessment,
        coverage_gaps: list[dict[str, Any]],
        resolved_gap: bool,
    ) -> dict[str, Any]:
        if gap_type == "quality_stability":
            accepted_ids = list(follow_up_assessment.get("accepted_evidence_ids", []))
            branch_id = str(follow_up_assessment.get("branch_id", ""))
            return {
                "resolved_gap_codes": [gap_code] if resolved_gap else [],
                "unresolved_gap_codes": [] if resolved_gap else [gap_code],
                "resolved_by_branch_ids": [branch_id]
                if resolved_gap and branch_id
                else [],
                "resolved_by_evidence_ids": accepted_ids if resolved_gap else [],
            }

        baseline_assessment_id = baseline_assessment.get("id", "")
        matched_gaps = [
            gap
            for gap in coverage_gaps
            if gap.get("code") == gap_code
            and gap.get("opened_by_coverage_assessment_id") == baseline_assessment_id
            and (not criterion_id or gap.get("criterion_id") == criterion_id)
        ]
        if not matched_gaps:
            return {
                "resolved_gap_codes": [],
                "unresolved_gap_codes": [gap_code],
                "resolved_by_branch_ids": [],
                "resolved_by_evidence_ids": [],
            }

        resolved_codes = []
        unresolved_codes = []
        resolved_branch_ids: list[str] = []
        resolved_evidence_ids: list[str] = []
        for gap in matched_gaps:
            code = str(gap.get("code", ""))
            if gap.get("status") == "resolved":
                resolved_codes.append(code)
                resolved_branch_ids.extend(gap.get("resolved_by_branch_ids", []))
                resolved_evidence_ids.extend(gap.get("resolved_by_evidence_ids", []))
            else:
                unresolved_codes.append(code)

        return {
            "resolved_gap_codes": list(dict.fromkeys(resolved_codes)),
            "unresolved_gap_codes": list(dict.fromkeys(unresolved_codes)),
            "resolved_by_branch_ids": list(dict.fromkeys(resolved_branch_ids)),
            "resolved_by_evidence_ids": list(dict.fromkeys(resolved_evidence_ids)),
        }

    def _latest_assessment(
        self,
        assessments_by_branch: dict[str, list[CoverageAssessment]],
        branch_id: str,
    ) -> CoverageAssessment | None:
        assessments = assessments_by_branch.get(branch_id, [])
        return assessments[-1] if assessments else None

    def _infer_gap_type(self, gap_code: str, branch: ResearchBranch) -> str:
        if gap_code.startswith("mixed_quality_"):
            return "quality_stability"
        if gap_code in {"missing_success_criterion", "missing_guiding_question"}:
            return "success_criterion"
        if branch.get("target_source_types"):
            return "source_coverage"
        return "coverage"

    def _resolved_gap(
        self,
        gap_type: str,
        gap_code: str,
        criterion_id: str,
        baseline_assessment: CoverageAssessment,
        follow_up_assessment: CoverageAssessment,
        coverage_gaps: list[dict[str, Any]],
    ) -> bool:
        if gap_type == "quality_stability":
            follow_up_quality = follow_up_assessment.get("quality_stability", {})
            repeated_codes = {
                str(gap.get("code", ""))
                for gap in follow_up_assessment.get("quality_stability_gaps", [])
            }
            return (
                follow_up_quality.get("status") != "unstable"
                and gap_code not in repeated_codes
            )

        baseline_assessment_id = baseline_assessment.get("id", "")
        for gap in coverage_gaps:
            if gap.get("code") != gap_code:
                continue
            if gap.get("opened_by_coverage_assessment_id") != baseline_assessment_id:
                continue
            if criterion_id and gap.get("criterion_id") != criterion_id:
                continue
            return gap.get("status") == "resolved"
        return False

    def _assessment_snapshot(
        self,
        assessment: CoverageAssessment,
    ) -> dict[str, Any]:
        quality = assessment.get("quality_stability", {})
        source_metrics = assessment.get("source_metrics", {})
        accepted_count = int(
            quality.get(
                "accepted_count",
                len(assessment.get("accepted_evidence_ids", [])),
            ),
        )
        rejected_count = int(
            quality.get(
                "rejected_count",
                len(assessment.get("rejected_evidence_ids", [])),
            ),
        )
        total_count = accepted_count + rejected_count
        rejected_ratio = float(
            quality.get(
                "rejected_ratio",
                round(rejected_count / total_count, 3) if total_count else 0.0,
            ),
        )
        return {
            "coverage_assessment_id": assessment.get("id", ""),
            "branch_id": assessment.get("branch_id", ""),
            "quality_status": quality.get("status", ""),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "total_evidence_count": total_count,
            "rejected_ratio": rejected_ratio,
            "independent_source_count": int(
                source_metrics.get("independent_source_count", 0),
            ),
            "unique_canonical_url_count": int(
                source_metrics.get("unique_canonical_url_count", 0),
            ),
            "unique_domain_count": int(source_metrics.get("unique_domain_count", 0)),
            "primary_source_count": int(source_metrics.get("primary_source_count", 0)),
            "source_gap_count": len(
                assessment.get("source_coverage_gaps")
                or assessment.get("source_type_gaps", []),
            ),
            "quality_gap_count": len(assessment.get("quality_stability_gaps", [])),
            "satisfied_criteria_count": len(
                assessment.get("satisfied_criteria", []),
            ),
            "partial_criteria_count": len(assessment.get("partial_criteria", [])),
            "missing_criteria_count": len(assessment.get("missing_criteria", [])),
            "covered_question_count": len(assessment.get("covered_questions", [])),
            "missing_question_count": len(assessment.get("missing_questions", [])),
            "found_source_types": list(assessment.get("found_source_types", [])),
        }

    def _snapshot_deltas(
        self,
        baseline: dict[str, Any],
        follow_up: dict[str, Any],
    ) -> dict[str, Any]:
        numeric_fields = [
            "accepted_count",
            "rejected_count",
            "total_evidence_count",
            "rejected_ratio",
            "independent_source_count",
            "unique_canonical_url_count",
            "unique_domain_count",
            "primary_source_count",
            "source_gap_count",
            "quality_gap_count",
            "satisfied_criteria_count",
            "partial_criteria_count",
            "missing_criteria_count",
            "covered_question_count",
            "missing_question_count",
        ]
        deltas: dict[str, Any] = {}
        for field in numeric_fields:
            baseline_value = baseline.get(field, 0)
            follow_up_value = follow_up.get(field, 0)
            if isinstance(baseline_value, float) or isinstance(follow_up_value, float):
                deltas[f"{field}_delta"] = round(
                    float(follow_up_value) - float(baseline_value),
                    3,
                )
            else:
                deltas[f"{field}_delta"] = int(follow_up_value) - int(baseline_value)
        return deltas

    def _improvement_signals(
        self,
        gap_type: str,
        baseline: dict[str, Any],
        follow_up: dict[str, Any],
        deltas: dict[str, Any],
        resolved_gap: bool,
        target_source_types: list[str],
    ) -> tuple[list[str], list[str]]:
        improved = []
        regressions = []
        if resolved_gap:
            improved.append("original_gap_resolved")

        self._append_delta_signal(
            deltas,
            "accepted_count_delta",
            positive_signal="accepted_count_increased",
            negative_signal="accepted_count_decreased",
            improved=improved,
            regressions=regressions,
        )
        self._append_delta_signal(
            deltas,
            "rejected_ratio_delta",
            positive_signal="rejected_ratio_increased",
            negative_signal="rejected_ratio_decreased",
            improved=regressions,
            regressions=improved,
        )
        self._append_delta_signal(
            deltas,
            "independent_source_count_delta",
            positive_signal="independent_source_count_increased",
            negative_signal="independent_source_count_decreased",
            improved=improved,
            regressions=regressions,
        )
        self._append_delta_signal(
            deltas,
            "unique_canonical_url_count_delta",
            positive_signal="unique_canonical_url_count_increased",
            negative_signal="unique_canonical_url_count_decreased",
            improved=improved,
            regressions=regressions,
        )
        self._append_delta_signal(
            deltas,
            "primary_source_count_delta",
            positive_signal="primary_source_count_increased",
            negative_signal="primary_source_count_decreased",
            improved=improved,
            regressions=regressions,
        )
        self._append_delta_signal(
            deltas,
            "missing_criteria_count_delta",
            positive_signal="missing_criteria_count_increased",
            negative_signal="missing_criteria_count_decreased",
            improved=regressions,
            regressions=improved,
        )
        self._append_delta_signal(
            deltas,
            "satisfied_criteria_count_delta",
            positive_signal="satisfied_criteria_count_increased",
            negative_signal="satisfied_criteria_count_decreased",
            improved=improved,
            regressions=regressions,
        )
        self._append_delta_signal(
            deltas,
            "missing_question_count_delta",
            positive_signal="missing_question_count_increased",
            negative_signal="missing_question_count_decreased",
            improved=regressions,
            regressions=improved,
        )
        self._append_delta_signal(
            deltas,
            "quality_gap_count_delta",
            positive_signal="quality_gap_count_increased",
            negative_signal="quality_gap_count_decreased",
            improved=regressions,
            regressions=improved,
        )

        quality_delta = self._quality_status_delta(
            str(baseline.get("quality_status", "")),
            str(follow_up.get("quality_status", "")),
        )
        if quality_delta > 0:
            improved.append("quality_status_improved")
        elif quality_delta < 0:
            regressions.append("quality_status_worsened")

        if gap_type == "source_coverage":
            found_source_types = set(follow_up.get("found_source_types", []))
            if set(target_source_types).intersection(found_source_types):
                improved.append("target_source_type_collected")

        return list(dict.fromkeys(improved)), list(dict.fromkeys(regressions))

    def _append_delta_signal(
        self,
        deltas: dict[str, Any],
        field: str,
        *,
        positive_signal: str,
        negative_signal: str,
        improved: list[str],
        regressions: list[str],
    ) -> None:
        delta = float(deltas.get(field, 0))
        if delta > 0:
            improved.append(positive_signal)
        elif delta < 0:
            regressions.append(negative_signal)

    def _quality_status_delta(self, baseline: str, follow_up: str) -> int:
        score = {
            "": 0,
            "unstable": 1,
            "mixed_quality": 2,
            "stable": 3,
        }
        return score.get(follow_up, 0) - score.get(baseline, 0)

    def _improvement_status(
        self,
        resolved_gap: bool,
        improved_signals: list[str],
        regression_signals: list[str],
    ) -> str:
        if resolved_gap:
            return "improved"
        if len(improved_signals) >= 2 and not regression_signals:
            return "improved"
        if regression_signals and not improved_signals:
            return "worse"
        if improved_signals and regression_signals:
            return "inconclusive"
        return "not_improved"

    def _improvement_notes(
        self,
        status: str,
        improved_signals: list[str],
        regression_signals: list[str],
    ) -> str:
        if status == "improved":
            return "Follow-up branch shows measurable improvement over its baseline."
        if status == "worse":
            return "Follow-up branch regressed against the baseline metrics."
        if status == "inconclusive":
            return "Follow-up branch has mixed improvement and regression signals."
        return "Follow-up branch did not produce measurable improvement."

    def _resolved_evidence_ids_for_gap(
        self,
        root: ResearchBranch,
        gap: dict[str, Any],
        accepted_evidence: list[EvidenceItem],
    ) -> list[str]:
        code = str(gap.get("code", ""))
        return [
            evidence.get("id", "")
            for evidence in accepted_evidence
            if evidence.get("id")
            and self._evidence_resolves_gap(root, gap, evidence, code)
        ]

    def _evidence_resolves_gap(
        self,
        root: ResearchBranch,
        gap: dict[str, Any],
        evidence: EvidenceItem,
        code: str,
    ) -> bool:
        source_type = evidence.get("source_type", "")
        if code == "insufficient_source_count":
            return True
        target_source_types = set(gap.get("target_source_types", []))
        if "official_site" in target_source_types and self.coverage_reviewer.looks_official(
            evidence.get("url", ""),
            root.get("competitor", ""),
        ):
            return True
        return bool(target_source_types and source_type in target_source_types)

    def _accepted_evidence_ids(
        self,
        evidence_reviews: list[EvidenceReviewResult],
    ) -> list[str]:
        accepted: list[str] = []
        for review in evidence_reviews:
            accepted.extend(review.get("accepted_evidence_ids", []))
        return list(dict.fromkeys(accepted))
