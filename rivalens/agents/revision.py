"""Revision agent that responds to review findings."""

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import AnalysisClaim, CompetitorAnalysisState


class RevisionAgent:
    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        review_message = latest_message_for(
            state,
            receiver="reviser",
            message_type="review",
            sender="quality",
        )
        review_payload = review_message.get("payload", {}) if review_message else {}
        findings = state.get("quality_findings") or review_payload.get("findings", [])
        claims = state.get("analysis_claims", [])
        blocked_ids = {finding.get("target_id") for finding in findings if finding.get("severity") == "high"}

        revised_claims: list[AnalysisClaim] = [
            claim for claim in claims if claim.get("id") not in blocked_ids
        ]

        note = (
            f"Removed {len(claims) - len(revised_claims)} unsupported claims after reviewer audit."
            if blocked_ids
            else "No revision required after reviewer audit."
        )

        return {
            "analysis_claims": revised_claims,
            "quality_findings": [],
            "revision_notes": state.get("revision_notes", []) + [note],
            "messages": state.get("messages", [])
            + [
                create_agent_message(
                    sender="reviser",
                    receiver="writer",
                    message_type="revision",
                    payload={"note": note, "claim_count": len(revised_claims)},
                    evidence_ids=[evidence_id for claim in revised_claims for evidence_id in claim.get("evidence_ids", [])],
                )
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "reviser",
                    "action": "revise_claims_from_review_feedback",
                    "input": {
                        "finding_count": len(findings),
                        "claim_count": len(claims),
                        "message_id": review_message.get("id") if review_message else None,
                    },
                    "output": {"claim_count": len(revised_claims), "note": note},
                }
            ],
        }
