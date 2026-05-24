"""Planning agent for competitor-analysis tasks."""

from rivalens.agents.messages import create_agent_message
from rivalens.research import ResearchToolkit
from rivalens.schema import Competitor, CompetitorAnalysisState


class PlanningAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []
        verbose = bool(task.get("verbose", True))

        normalized: list[Competitor] = []
        for competitor in competitors:
            if isinstance(competitor, str):
                normalized.append({"name": competitor})
            else:
                normalized.append(
                    {
                        "name": competitor.get("name", ""),
                        "product": competitor.get("product", ""),
                        "website": competitor.get("website", ""),
                        "category": competitor.get("category", ""),
                        "notes": competitor.get("notes", ""),
                    }
                )

        outline = await self.research_toolkit.generate_outline(query=query, verbose=verbose)
        research_artifacts = state.get("research_artifacts", []) + [
            {
                "id": "artifact_planning_outline_1",
                "agent": "planner",
                "mode": outline["mode"],
                "query": outline["query"],
                "report": outline["report"],
                "context": outline["context"],
                "costs": outline["costs"],
            }
        ]
        artifact_id = research_artifacts[-1]["id"]
        message = create_agent_message(
            sender="planner",
            receiver="schema_selection",
            message_type="plan",
            payload={
                "query": query,
                "competitors": normalized,
                "suggested_outline": outline["report"],
            },
            artifact_ids=[artifact_id],
        )

        return {
            "competitors": normalized,
            "research_artifacts": research_artifacts,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "planner",
                    "action": "normalize_scope_and_generate_outline",
                    "input": {"query": query, "competitors": competitors},
                    "output": {
                        "competitor_count": len(normalized),
                        "research_mode": outline["mode"],
                    },
                }
            ],
        }
