"""Quality agent for citation and traceability checks."""

from rivalens.research import ResearchToolkit
from rivalens.schema import CompetitorAnalysisState, QualityFinding


class QualityAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        verbose = bool(task.get("verbose", True))
        findings: list[QualityFinding] = []
        verification = await self.research_toolkit.discover_sources(
            query=f"Find authoritative sources to verify competitor claims for: {task.get('query', '')}",
            verbose=verbose,
        )

        for claim in state.get("analysis_claims", []):
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

        return {
            "quality_findings": findings,
            "research_artifacts": state.get("research_artifacts", [])
            + [
                {
                    "id": "artifact_quality_source_discovery_1",
                    "agent": "quality",
                    "mode": verification["mode"],
                    "query": verification["query"],
                    "report": verification["report"],
                    "context": verification["context"],
                    "costs": verification["costs"],
                }
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "quality",
                    "action": "audit_traceability",
                    "input": {"claim_count": len(state.get("analysis_claims", []))},
                    "output": {"finding_count": len(findings), "research_mode": verification["mode"]},
                }
            ],
        }
