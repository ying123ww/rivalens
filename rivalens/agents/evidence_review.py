"""Collection-time evidence quality review."""

from typing import Any

from langsmith import traceable

from rivalens.agents.success_criteria import (
    matched_success_criterion_ids,
    normalize_success_criteria,
)
from rivalens.schema import EvidenceReviewFinding, EvidenceReviewResult, ResearchBranch
from rivalens.text_quality import is_low_quality_text


def _branch_trace_summary(branch: dict[str, Any]) -> dict[str, Any]:
    return {
        "branch_id": branch.get("id", ""),
        "research_brief_id": branch.get("research_brief_id", ""),
        "parent_branch_id": branch.get("parent_id"),
        "depth": branch.get("depth", 0),
        "competitor": branch.get("competitor", ""),
        "dimension_id": branch.get("dimension_id", ""),
        "dimension_name": branch.get("dimension_name", ""),
        "search_stage": branch.get("search_stage", ""),
        "generated_from_gap": branch.get("generated_from_gap", ""),
        "decision_action": branch.get("decision_action", ""),
        "decision_subtype": branch.get("decision_subtype", ""),
        "query": branch.get("query", ""),
        "research_goal": branch.get("research_goal", ""),
        "success_criteria": _criteria_trace_summary(
            branch.get("success_criteria", []),
        ),
    }


def _criteria_trace_summary(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": criterion.get("id", ""),
            "description": criterion.get("description", ""),
            "target_source_types": list(criterion.get("target_source_types", []))[:5],
            "required_source_types": list(criterion.get("required_source_types", []))[:5],
            "status": criterion.get("status", ""),
            "evidence_ids": list(criterion.get("evidence_ids", []))[:10],
        }
        for criterion in criteria[:10]
        if isinstance(criterion, dict)
    ]


def _evidence_trace_summary(evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source_type": item.get("source_type", ""),
            "confidence": item.get("confidence"),
            "excerpt_chars": len(str(item.get("excerpt") or "")),
            "success_criterion_ids": list(item.get("success_criterion_ids", []))[:10],
        }
        for item in evidence_items[:10]
    ]


def _evidence_review_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    branch = inputs.get("branch") or {}
    evidence_items = inputs.get("evidence_items") or []
    return {
        "branch": _branch_trace_summary(branch),
        "evidence_count": len(evidence_items),
        "evidence": _evidence_trace_summary(evidence_items),
    }


def _evidence_review_trace_outputs(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"output_type": type(output).__name__}
    findings = output.get("findings") or []
    return {
        "review_id": output.get("id", ""),
        "branch_id": output.get("branch_id", ""),
        "accepted": bool(output.get("accepted")),
        "score": output.get("score"),
        "required_action": output.get("required_action", ""),
        "accepted_evidence_ids": list(output.get("accepted_evidence_ids", []))[:20],
        "rejected_evidence_ids": list(output.get("rejected_evidence_ids", []))[:20],
        "criterion_matches": list(output.get("criterion_matches", []))[:20],
        "finding_count": len(findings),
        "finding_codes": [
            finding.get("code", "")
            for finding in findings[:20]
            if isinstance(finding, dict)
        ],
    }


class EvidenceQualityReviewer:
    """Judge whether standard-search evidence is fit for downstream analysis."""

    def __init__(self, min_sources_per_branch: int = 2):
        self.min_sources_per_branch = min_sources_per_branch

    @traceable(
        name="rivalens_evidence_quality_review",
        run_type="chain",
        tags=["rivalens", "collection", "evidence-review"],
        process_inputs=_evidence_review_trace_inputs,
        process_outputs=_evidence_review_trace_outputs,
    )
    def review(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
    ) -> EvidenceReviewResult:
        item_findings: list[EvidenceReviewFinding] = []
        accepted_evidence_ids: list[str] = []
        rejected_evidence_ids: list[str] = []
        criterion_matches: list[dict[str, Any]] = []
        success_criteria = normalize_success_criteria(
            branch.get("success_criteria", []),
        )

        for evidence in evidence_items:
            evidence_id = evidence.get("id", "")
            item_rejected = False
            matched_criterion_ids = matched_success_criterion_ids(
                evidence,
                success_criteria,
                branch,
            )
            if matched_criterion_ids:
                evidence["success_criterion_ids"] = matched_criterion_ids
                criterion_matches.append(
                    {
                        "evidence_id": evidence_id,
                        "criterion_ids": matched_criterion_ids,
                    }
                )
            elif success_criteria:
                item_findings.append(
                    self._finding(
                        branch,
                        code="no_success_criterion_match",
                        severity="medium",
                        evidence_id=evidence_id,
                        message="正在评估当前来源与维度目标的匹配度。",
                        recommendation="Reject this source for this branch and narrow the follow-up query to missing criteria.",
                    )
                )
                item_rejected = True

            if not evidence.get("url"):
                item_findings.append(
                    self._finding(
                        branch,
                        code="missing_source_url",
                        severity="high",
                        evidence_id=evidence_id,
                        message="正在重新抓取来源链接。",
                        recommendation="Retry scraping or replace the source.",
                    )
                )
                item_rejected = True
            if self._competitor_mismatch(branch, evidence):
                item_findings.append(
                    self._finding(
                        branch,
                        code="competitor_mismatch",
                        severity="high",
                        evidence_id=evidence_id,
                        message="正在验证来源与目标竞品的匹配关系。",
                        recommendation="Reject this source or redirect collection.",
                    )
                )
                item_rejected = True
            if self._dimension_mismatch(branch, evidence):
                item_findings.append(
                    self._finding(
                        branch,
                        code="dimension_mismatch",
                        severity="medium",
                        evidence_id=evidence_id,
                        message="正在将来源归类到对应分析维度。",
                        recommendation="Use this source only for its matching dimension.",
                    )
                )
                item_rejected = True
            if self._low_quality_text(evidence):
                item_findings.append(
                    self._finding(
                        branch,
                        code="low_quality_text",
                        severity="high",
                        evidence_id=evidence_id,
                        message="正在清理和校验来源文本质量。",
                        recommendation="Reject this source and collect a cleaner source.",
                    )
                )
                item_rejected = True

            if item_rejected:
                if evidence_id:
                    rejected_evidence_ids.append(evidence_id)
            elif evidence_id:
                accepted_evidence_ids.append(evidence_id)

        coverage_findings = self._coverage_findings(
            branch,
            evidence_items,
            accepted_evidence_ids,
        )
        findings = item_findings + coverage_findings
        required_action = self._required_action(
            item_findings,
            coverage_findings,
            len(accepted_evidence_ids),
        )
        accepted = required_action == "accept"

        return {
            "id": f"ev_review_{branch.get('id', 'unknown')}",
            "branch_id": branch.get("id", ""),
            "collection_task_id": branch.get("id", ""),
            "accepted": accepted,
            "score": self._score(findings),
            "findings": findings,
            "accepted_evidence_ids": accepted_evidence_ids,
            "rejected_evidence_ids": rejected_evidence_ids,
            "criterion_matches": criterion_matches,
            "required_action": required_action,
        }

    def _coverage_findings(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
        accepted_evidence_ids: list[str],
    ) -> list[EvidenceReviewFinding]:
        findings: list[EvidenceReviewFinding] = []
        accepted_id_set = set(accepted_evidence_ids)
        accepted_evidence = [
            item
            for item in evidence_items
            if item.get("id", "") in accepted_id_set
        ]
        source_types = {item.get("source_type", "other") for item in accepted_evidence}
        urls = [item.get("url", "") for item in accepted_evidence]
        dimension_id = branch.get("dimension_id", "")

        if not evidence_items:
            findings.append(
                self._finding(
                    branch,
                    code="no_evidence",
                    severity="high",
                    evidence_id=None,
                    message="证据收集中，尚未获取足够来源，正在进行补充检索。",
                    recommendation="Expand with a more targeted branch query.",
                )
            )
            return findings

        if len(accepted_evidence_ids) < self.min_sources_per_branch:
            findings.append(
                self._finding(
                    branch,
                    code="insufficient_source_count",
                    severity="medium",
                    evidence_id=None,
                    message="当前可用证据数量偏低，正在扩展检索范围补充更多来源。",
                    recommendation="Expand collection with additional source-backed queries.",
                )
            )
        if not any(self._looks_official(url, branch.get("competitor", "")) for url in urls):
            findings.append(
                self._finding(
                    branch,
                    code="missing_official_source",
                    severity="medium",
                    evidence_id=None,
                    message="正在检索官方来源，当前尚未匹配到竞品官方页面。",
                    recommendation="Expand collection toward official pages or docs.",
                )
            )
        if self._dimension_matches(dimension_id, {"pricing_model", "pricing_business_model", "business_model_pricing"}) and "pricing_page" not in source_types:
            findings.append(
                self._finding(
                    branch,
                    code="missing_pricing_page",
                    severity="medium",
                    evidence_id=None,
                    message="定价维度正在检索官方定价页面来源。",
                    recommendation="Expand collection toward official pricing pages.",
                )
            )
        if (
            self._dimension_matches(
                dimension_id,
                {"security_compliance", "admin_governance", "integration_ecosystem", "compliance_risk", "technology_integrations"},
            )
            and "docs" not in source_types
        ):
            findings.append(
                self._finding(
                    branch,
                    code="missing_docs_or_security_source",
                    severity="medium",
                    evidence_id=None,
                    message="技术维度正在检索文档与安全合规相关来源。",
                    recommendation="Expand collection toward docs, trust, or security pages.",
                )
            )
        if self._dimension_matches(dimension_id, {"user_personas", "target_users"}) and "review" not in source_types:
            findings.append(
                self._finding(
                    branch,
                    code="missing_customer_or_review_source",
                    severity="medium",
                    evidence_id=None,
                    message="用户画像维度正在检索客户评价与案例来源。",
                    recommendation="Expand collection toward reviews, case studies, or use cases.",
                )
            )

        return findings

    def _required_action(
        self,
        item_findings: list[EvidenceReviewFinding],
        coverage_findings: list[EvidenceReviewFinding],
        accepted_count: int,
    ) -> str:
        if not coverage_findings:
            return "accept"

        high_codes = {
            finding.get("code")
            for finding in item_findings + coverage_findings
            if finding.get("severity") == "high"
        }
        if "competitor_mismatch" in high_codes and accepted_count == 0:
            return "retry"
        if "no_evidence" in high_codes:
            return "expand"
        if "missing_source_url" in high_codes and accepted_count == 0:
            return "retry"
        if "low_quality_text" in high_codes and accepted_count == 0:
            return "retry"
        if (
            any(
                finding.get("code") == "no_success_criterion_match"
                for finding in item_findings
            )
            and accepted_count == 0
        ):
            return "retry"
        return "expand"

    def _score(self, findings: list[EvidenceReviewFinding]) -> float:
        score = 1.0
        for finding in findings:
            if finding.get("severity") == "high":
                score -= 0.35
            elif finding.get("severity") == "medium":
                score -= 0.18
            else:
                score -= 0.08
        return round(max(0.0, score), 2)

    def _finding(
        self,
        branch: ResearchBranch,
        code: str,
        severity: str,
        evidence_id: str | None,
        message: str,
        recommendation: str,
    ) -> EvidenceReviewFinding:
        evidence_part = evidence_id or "branch"
        return {
            "id": f"evq_{branch.get('id', 'unknown')}_{code}_{evidence_part}",
            "severity": severity,
            "code": code,
            "evidence_id": evidence_id,
            "branch_id": branch.get("id", ""),
            "message": message,
            "recommendation": recommendation,
        }

    def _competitor_mismatch(
        self,
        branch: ResearchBranch,
        evidence: dict[str, Any],
    ) -> bool:
        branch_competitor = self._normalize(branch.get("competitor", ""))
        evidence_competitor = self._normalize(evidence.get("competitor", ""))
        return bool(
            branch_competitor
            and evidence_competitor
            and branch_competitor != evidence_competitor
        )

    def _dimension_mismatch(
        self,
        branch: ResearchBranch,
        evidence: dict[str, Any],
    ) -> bool:
        branch_dimension = self._normalize(branch.get("dimension_id", ""))
        evidence_dimension = self._normalize(evidence.get("dimension_id", ""))
        return bool(
            branch_dimension
            and evidence_dimension
            and branch_dimension != evidence_dimension
        )

    def _looks_official(self, url: str, competitor: str) -> bool:
        if not url or not competitor:
            return False
        normalized_url = url.lower()
        tokens = [token for token in competitor.lower().replace("-", " ").split() if token]
        return any(token in normalized_url for token in tokens)

    def _normalize(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _dimension_matches(self, dimension_id: str, candidates: set[str]) -> bool:
        normalized = self._normalize(dimension_id)
        return normalized in {self._normalize(candidate) for candidate in candidates}

    def _low_quality_text(self, evidence: dict[str, Any]) -> bool:
        text = " ".join(
            str(part or "")
            for part in [
                evidence.get("title", ""),
                evidence.get("excerpt", ""),
            ]
        ).strip()
        return bool(text) and is_low_quality_text(text)
