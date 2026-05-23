"""Evidence collection agent for competitor analysis."""

from typing import Any

from rivalens.research import ResearchToolkit
from rivalens.schema import CompetitorAnalysisState


class CollectionAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []
        deep = bool(task.get("deep_research", True))
        verbose = bool(task.get("verbose", True))

        evidence_items = list(state.get("evidence_items", []))
        research_artifacts = list(state.get("research_artifacts", []))
        contexts: list[dict[str, Any]] = []

        if competitors:
            for competitor in competitors:
                name = competitor.get("name", "") if isinstance(competitor, dict) else str(competitor)
                research = await self.research_toolkit.collect_evidence(
                    query=f"{query}\nCompetitor: {name}",
                    competitor=name,
                    deep=deep,
                    verbose=verbose,
                )
                sources = self._assign_evidence_ids(research["sources"], len(evidence_items))
                evidence_items.extend(sources)
                contexts.append(research)
                research_artifacts.append(
                    {
                        "id": f"artifact_collection_{len(research_artifacts) + 1}",
                        "agent": "collection",
                        "mode": research["mode"],
                        "query": research["query"],
                        "competitor": name,
                        "context": research["context"],
                        "evidence_ids": [source.get("id", "") for source in sources],
                        "costs": research["costs"],
                    }
                )
        else:
            research = await self.research_toolkit.collect_evidence(query=query, deep=deep, verbose=verbose)
            sources = self._assign_evidence_ids(research["sources"], len(evidence_items))
            evidence_items.extend(sources)
            contexts.append(research)
            research_artifacts.append(
                {
                    "id": f"artifact_collection_{len(research_artifacts) + 1}",
                    "agent": "collection",
                    "mode": research["mode"],
                    "query": research["query"],
                    "context": research["context"],
                    "evidence_ids": [source.get("id", "") for source in sources],
                    "costs": research["costs"],
                }
            )

        return {
            "evidence_items": evidence_items,
            "research_artifacts": research_artifacts,
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "collection",
                    "action": "collect_public_evidence",
                    "input": {"query": query, "competitors": competitors},
                    "output": {"evidence_count": len(evidence_items), "research_runs": len(contexts)},
                }
            ],
        }

    def _assign_evidence_ids(self, sources: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
        assigned = []
        for index, source in enumerate(sources, start=offset + 1):
            item = dict(source)
            item["id"] = f"ev_{index}"
            assigned.append(item)
        return assigned
