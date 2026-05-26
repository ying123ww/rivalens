"""Report writer for structured competitor analysis output."""

from rivalens.agents.messages import create_agent_message
from rivalens.schema import CompetitorAnalysisState


class ReportWriterAgent:
    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        claims = state.get("analysis_claims", [])

        lines = [
            "# Competitor Analysis Report",
            "",
            "## Key Claims",
        ]

        if claims:
            for claim in claims:
                evidence_ids = ", ".join(claim.get("evidence_ids", [])) or "no evidence"
                lines.append(f"- {claim.get('claim', '')} [evidence: {evidence_ids}]")
        else:
            lines.append("- No claims generated yet.")

        return {
            "report": "\n".join(lines),
            "messages": state.get("messages", [])
            + [
                create_agent_message(
                    sender="writer",
                    receiver="publisher",
                    message_type="report",
                    payload={"report_length": sum(len(line) for line in lines)},
                    evidence_ids=[evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", [])],
                )
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "writer",
                    "action": "compose_structured_report",
                    "input": {
                        "claim_count": len(claims),
                    },
                    "output": {"report_length": sum(len(line) for line in lines)},
                }
            ],
        }
