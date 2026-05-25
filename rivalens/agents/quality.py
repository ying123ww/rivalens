"""Quality agent for citation and traceability checks."""

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

        for claim in claims:
            if not claim.get("evidence_ids"):
                findings.append(
                    {
                        "id": f"qf_{len(findings) + 1}",
                        "severity": "high",
                        "target_id": claim.get("id", ""),
                        "message": "Analysis claim has no evidence binding.",
                        "recommendation": "Send the claim back for evidence collection or remove it.",
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
            evidence_ids=[evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", [])],
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
                        "message_id": analysis_message.get("id") if analysis_message else None,
                    },
                    "output": {"finding_count": len(findings)},
                }
            ],
        }
