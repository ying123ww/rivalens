"""Quality agent for citation and traceability checks."""

from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState, QualityFinding


class QualityAgent:
    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        analysis_message = latest_message_for(
            state,
            receiver="quality",
            message_type="analysis",
            sender="analysis",
        )
        analysis_payload = analysis_message.get("payload", {}) if analysis_message else {}
        claims = state.get("analysis_claims") or analysis_payload.get("claims", [])
        findings: list[QualityFinding] = []
        evidence_by_id = {
            item.get("id", ""): item
            for item in state.get("evidence_items", [])
            if item.get("id")
        }

        for claim in claims:
            evidence_ids = [
                evidence_id
                for evidence_id in claim.get("evidence_ids", [])
                if evidence_id
            ]
            if not evidence_ids:
                findings.append(
                    {
                        "id": f"qf_{len(findings) + 1}",
                        "severity": "high",
                        "target_id": claim.get("id", ""),
                        "message": "Analysis claim has no evidence binding.",
                        "recommendation": (
                            "Send the claim back for evidence collection or remove it."
                        ),
                    }
                )
                continue

            missing_evidence_ids = [
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id not in evidence_by_id
            ]
            if missing_evidence_ids:
                findings.append(
                    {
                        "id": f"qf_{len(findings) + 1}",
                        "severity": "high",
                        "target_id": claim.get("id", ""),
                        "message": (
                            "Analysis claim references evidence IDs that do not exist: "
                            f"{', '.join(missing_evidence_ids)}."
                        ),
                        "recommendation": (
                            "Collect or restore the referenced EvidenceItem records before "
                            "accepting the claim."
                        ),
                    }
                )

            linked_evidence = [
                evidence_by_id[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in evidence_by_id
            ]
            evidence_without_url = [
                evidence.get("id", "")
                for evidence in linked_evidence
                if not evidence.get("url")
            ]
            if evidence_without_url:
                findings.append(
                    {
                        "id": f"qf_{len(findings) + 1}",
                        "severity": "high",
                        "target_id": claim.get("id", ""),
                        "message": (
                            "Analysis claim is bound to evidence without source URLs: "
                            f"{', '.join(evidence_without_url)}."
                        ),
                        "recommendation": (
                            "Replace these bindings with EvidenceItem records that include "
                            "source URLs."
                        ),
                    }
                )

            competitor_gap = self._uncovered_competitors(claim, linked_evidence)
            if competitor_gap:
                findings.append(
                    {
                        "id": f"qf_{len(findings) + 1}",
                        "severity": "medium",
                        "target_id": claim.get("id", ""),
                        "message": (
                            "Analysis claim has no linked evidence for competitors: "
                            f"{', '.join(competitor_gap)}."
                        ),
                        "recommendation": (
                            "Bind at least one EvidenceItem from each named competitor or "
                            "narrow the claim scope."
                        ),
                    }
                )

            if linked_evidence and not self._has_dimension_support(claim, linked_evidence):
                findings.append(
                    {
                        "id": f"qf_{len(findings) + 1}",
                        "severity": "medium",
                        "target_id": claim.get("id", ""),
                        "message": "Analysis claim evidence does not cover the claim dimension.",
                        "recommendation": (
                            "Bind evidence collected for the same schema dimension or revise "
                            "the claim dimension."
                        ),
                    }
                )

        receiver = "reviser" if findings else "writer"
        message = create_agent_message(
            sender="quality",
            receiver=receiver,
            message_type="review",
            payload={
                "finding_count": len(findings),
                "findings": findings,
                "accepted": not findings,
            },
            evidence_ids=[
                evidence_id
                for claim in claims
                for evidence_id in claim.get("evidence_ids", [])
            ],
        )

        return {
            "quality_findings": findings,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "quality",
                    "action": "audit_traceability",
                    "input": {
                        "claim_count": len(claims),
                        "evidence_count": len(evidence_by_id),
                        "message_id": analysis_message.get("id") if analysis_message else None,
                    },
                    "output": {"finding_count": len(findings)},
                }
            ],
        }

    def _uncovered_competitors(
        self,
        claim: dict[str, Any],
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        claim_competitors = [
            competitor
            for competitor in claim.get("competitors", [])
            if self._normalize_token(competitor)
        ]
        if not claim_competitors:
            return []

        evidence_competitors = {
            self._normalize_token(evidence.get("competitor", ""))
            for evidence in evidence_items
            if self._normalize_token(evidence.get("competitor", ""))
        }
        if not evidence_competitors:
            return claim_competitors

        return [
            competitor
            for competitor in claim_competitors
            if self._normalize_token(competitor) not in evidence_competitors
        ]

    def _has_dimension_support(
        self,
        claim: dict[str, Any],
        evidence_items: list[dict[str, Any]],
    ) -> bool:
        claim_dimension = self._normalize_token(claim.get("dimension", ""))
        if not claim_dimension:
            return True

        supported_dimensions = self._compatible_dimensions(claim_dimension)
        for evidence in evidence_items:
            evidence_dimension = self._normalize_token(evidence.get("dimension_id", ""))
            if evidence_dimension in supported_dimensions:
                return True
        return False

    def _compatible_dimensions(self, claim_dimension: str) -> set[str]:
        compatibility = {
            "core_feature": {"core_feature", "feature_tree"},
            "feature_tree": {"core_feature", "feature_tree"},
            "pricing_model": {"pricing_model"},
            "user_personas": {"user_personas"},
        }
        return compatibility.get(claim_dimension, {claim_dimension})

    def _normalize_token(self, value: Any) -> str:
        return str(value or "").strip().lower()
