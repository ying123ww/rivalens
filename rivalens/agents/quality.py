"""Quality agent for citation and traceability checks."""

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.research import ResearchToolkit
from rivalens.schema import CompetitorAnalysisState, QualityFinding


class QualityAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        verbose = bool(task.get("verbose", True))
        analysis_message = latest_message_for(
            state,
            receiver="quality",
            message_type="analysis",
            sender="analysis",
        )
        analysis_payload = analysis_message.get("payload", {}) if analysis_message else {}
        claims = state.get("analysis_claims") or analysis_payload.get("claims", [])
        findings: list[QualityFinding] = []
        verification = await self.research_toolkit.discover_sources(
            query=f"Find authoritative sources to verify competitor claims for: {task.get('query', '')}",
            verbose=verbose,
        )

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

        artifact = {
            "id": "artifact_quality_source_discovery_1",
            "agent": "quality",
            "mode": verification["mode"],
            "query": verification["query"],
            "report": verification["report"],
            "context": verification["context"],
            "costs": verification["costs"],
        }
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
            artifact_ids=[artifact["id"]],
            evidence_ids=[evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", [])],
        )

        return {
            "quality_findings": findings,
            "research_artifacts": state.get("research_artifacts", []) + [artifact],
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
                    "output": {"finding_count": len(findings), "research_mode": verification["mode"]},
                }
            ],
        }
