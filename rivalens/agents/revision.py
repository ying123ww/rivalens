"""Revision agent that responds to review findings."""

from rivalens.schema import AnalysisClaim, CompetitorAnalysisState


class RevisionAgent:
    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        findings = state.get("quality_findings", [])
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
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "reviser",
                    "action": "revise_claims_from_review_feedback",
                    "input": {"finding_count": len(findings), "claim_count": len(claims)},
                    "output": {"claim_count": len(revised_claims), "note": note},
                }
            ],
        }
