"""Analysis agent that turns evidence into traceable claims."""

from rivalens.research import ResearchToolkit
from rivalens.schema import AnalysisClaim, CompetitorAnalysisState


class AnalysisAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        verbose = bool(task.get("verbose", True))
        product_facts = state.get("product_facts", [])
        claims: list[AnalysisClaim] = []

        focused_research = await self.research_toolkit.focused_analysis(
            query=f"Analyze competitive implications for: {task.get('query', '')}",
            context=product_facts,
            verbose=verbose,
        )

        for fact in product_facts:
            competitor = fact.get("competitor", "")
            value = fact.get("value", "")
            if not value:
                continue

            claims.append(
                {
                    "id": f"claim_{len(claims) + 1}",
                    "dimension": fact.get("dimension", "public_signal"),
                    "claim": value[:500],
                    "competitors": [competitor] if competitor else [],
                    "evidence_ids": fact.get("evidence_ids", []),
                    "reasoning": "Derived from normalized competitor knowledge facts.",
                    "confidence": fact.get("confidence", 0.5),
                }
            )

        return {
            "analysis_claims": claims,
            "research_artifacts": state.get("research_artifacts", [])
            + [
                {
                    "id": "artifact_focused_analysis_1",
                    "agent": "analysis",
                    "mode": focused_research["mode"],
                    "query": focused_research["query"],
                    "report": focused_research["report"],
                    "context": focused_research["context"],
                    "costs": focused_research["costs"],
                }
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "analysis",
                    "action": "derive_traceable_claims",
                    "input": {"fact_count": len(product_facts)},
                    "output": {"claim_count": len(claims), "research_mode": focused_research["mode"]},
                }
            ],
        }
