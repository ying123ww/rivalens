"""Collection-time evidence quality review."""

from typing import Any

from rivalens.schema import EvidenceReviewFinding, EvidenceReviewResult, ResearchBranch


class EvidenceQualityReviewer:
    """Judge whether standard-search evidence is fit for downstream analysis."""

    def __init__(self, min_sources_per_branch: int = 2):
        self.min_sources_per_branch = min_sources_per_branch

    def review(
        self,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
    ) -> EvidenceReviewResult:
        item_findings: list[EvidenceReviewFinding] = []
        accepted_evidence_ids: list[str] = []
        rejected_evidence_ids: list[str] = []

        for evidence in evidence_items:
            evidence_id = evidence.get("id", "")
            item_rejected = False
            if not evidence.get("url"):
                item_findings.append(
                    self._finding(
                        branch,
                        code="missing_source_url",
                        severity="high",
                        evidence_id=evidence_id,
                        message="Evidence item has no source URL.",
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
                        message="Evidence item does not match the branch competitor.",
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
                        message="Evidence item does not match the branch schema dimension.",
                        recommendation="Use this source only for its matching dimension.",
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
                    message="Standard search returned no evidence.",
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
                    message="Accepted evidence count is below the branch threshold.",
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
                    message="No accepted source appears to be an official competitor source.",
                    recommendation="Expand collection toward official pages or docs.",
                )
            )
        if dimension_id == "pricing_model" and "pricing_page" not in source_types:
            findings.append(
                self._finding(
                    branch,
                    code="missing_pricing_page",
                    severity="medium",
                    evidence_id=None,
                    message="Pricing branch lacks a pricing-page source.",
                    recommendation="Expand collection toward official pricing pages.",
                )
            )
        if (
            dimension_id
            in {"security_compliance", "admin_governance", "integration_ecosystem"}
            and "docs" not in source_types
        ):
            findings.append(
                self._finding(
                    branch,
                    code="missing_docs_or_security_source",
                    severity="medium",
                    evidence_id=None,
                    message="Technical branch lacks docs or security-focused sources.",
                    recommendation="Expand collection toward docs, trust, or security pages.",
                )
            )
        if dimension_id == "user_personas" and "review" not in source_types:
            findings.append(
                self._finding(
                    branch,
                    code="missing_customer_or_review_source",
                    severity="medium",
                    evidence_id=None,
                    message="Persona branch lacks review or customer evidence.",
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
