"""Build root-branch coverage state from collection reviews."""

from typing import Any

from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.success_criteria import (
    evidence_matches_success_criterion,
    normalize_success_criteria,
)
from rivalens.schema import (
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
            current_source_type_gaps = self.coverage_reviewer.source_type_gaps(
                root,
                accepted_evidence,
                found_source_types,
            )
            open_source_type_gap_codes = {
                str(gap.get("code", ""))
                for gap in current_source_type_gaps
                if gap.get("code")
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
            status = (
                "ready_for_analysis"
                if not open_gap_codes and not unresolved_criteria
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
            required_source_types = set(criterion.get("required_source_types", []))
            required_source_matched = (
                not required_source_types
                or any(
                    evidence.get("source_type") in required_source_types
                    for evidence in matched_evidence
                )
            )
            status = "missing"
            if evidence_ids and required_source_matched:
                status = "satisfied"
            elif evidence_ids:
                status = "partial"
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
                for gap in assessment.get("source_type_gaps", []):
                    code = str(gap.get("code", ""))
                    if not code:
                        continue
                    gap_id = f"gap_{assessment.get('id', branch_id)}_{code}"
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
                    status = "blocked" if code in open_gap_codes else "resolved"
                    gaps.append(
                        {
                            "id": gap_id,
                            "gap_type": "source_type",
                            "code": code,
                            "criterion_id": "",
                            "description": "",
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
                            "target_source_types": list(
                                criterion.get("target_source_types", []),
                            ),
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
        if code == "missing_pricing_page":
            return source_type == "pricing_page"
        if code == "missing_docs_or_security_source":
            return source_type in {"docs", "trust_center"}
        if code == "missing_customer_or_review_source":
            return source_type in {"review", "case_study", "news"}
        if code == "missing_official_source":
            return source_type == "official_site" or self.coverage_reviewer.looks_official(
                evidence.get("url", ""),
                root.get("competitor", ""),
            )
        target_source_types = set(gap.get("target_source_types", []))
        return bool(target_source_types and source_type in target_source_types)

    def _accepted_evidence_ids(
        self,
        evidence_reviews: list[EvidenceReviewResult],
    ) -> list[str]:
        accepted: list[str] = []
        for review in evidence_reviews:
            accepted.extend(review.get("accepted_evidence_ids", []))
        return list(dict.fromkeys(accepted))
