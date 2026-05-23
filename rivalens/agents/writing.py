"""Report writer for structured competitor analysis output."""

from rivalens.agents.messages import create_agent_message
from rivalens.schema import CompetitorAnalysisState


class ReportWriterAgent:
    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        claims = state.get("analysis_claims", [])
        findings = state.get("quality_findings", [])

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

        lines.extend(["", "## Quality Findings"])
        if findings:
            for finding in findings:
                lines.append(f"- {finding.get('severity', 'medium')}: {finding.get('message', '')}")
        else:
            lines.append("- No blocking traceability issues found.")

        revision_notes = state.get("revision_notes", [])
        if revision_notes:
            lines.extend(["", "## Revision Notes"])
            for note in revision_notes:
                lines.append(f"- {note}")

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
                    "input": {"claim_count": len(claims), "finding_count": len(findings)},
                    "output": {"report_length": sum(len(line) for line in lines)},
                }
            ],
        }
