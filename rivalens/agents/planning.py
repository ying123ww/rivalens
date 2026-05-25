"""Planning agent for competitor-analysis tasks."""

from datetime import datetime, timezone
from typing import Any

from rivalens.agents.messages import create_agent_message
from rivalens.research import ResearchToolkit
from rivalens.schema import ActiveKnowledgeSchema, Competitor, CompetitorAnalysisState
from rivalens.schema_registry import CORE_SCHEMA_FIELDS, SchemaRegistry


class PlanningAgent:
    def __init__(
        self,
        research_toolkit: ResearchToolkit | None = None,
        schema_registry: SchemaRegistry | None = None,
    ):
        self.research_toolkit = research_toolkit or ResearchToolkit()
        self.schema_registry = schema_registry or SchemaRegistry()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []
        verbose = bool(task.get("verbose", True))

        normalized = self._normalize_competitors(competitors)
        outline = await self.research_toolkit.generate_outline(
            query=query,
            verbose=verbose,
        )
        active_schema = self._select_active_schema(query, normalized)
        candidate_industries = active_schema.get("candidate_industries", [])
        industry_extensions = active_schema.get("industry_extensions", [])

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
            receiver="collection",
            message_type="schema_selection",
            payload={
                "active_schema": active_schema,
                "candidate_count": len(candidate_industries),
            },
            artifact_ids=[artifact_id],
        )

        return {
            "competitors": normalized,
            "active_knowledge_schema": active_schema,
            "research_artifacts": research_artifacts,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "planner",
                    "action": "normalize_scope_generate_outline_and_select_schema",
                    "input": {"query": query, "competitors": competitors},
                    "output": {
                        "competitor_count": len(normalized),
                        "research_mode": outline["mode"],
                        "selected_industry": active_schema.get(
                            "selected_industry",
                            {},
                        ).get("industry_id"),
                        "confidence": active_schema.get("selected_industry", {}).get(
                            "confidence",
                        ),
                        "extension_count": len(industry_extensions),
                    },
                }
            ],
        }

    def _normalize_competitors(self, competitors: list[Any]) -> list[Competitor]:
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
        return normalized

    def _select_active_schema(
        self,
        query: str,
        competitors: list[Competitor],
    ) -> ActiveKnowledgeSchema:
        candidate_industries = self.schema_registry.rank_industries(
            query,
            competitors,
        )
        selected_industry = candidate_industries[0]
        industry_extensions = self.schema_registry.get_extensions(
            selected_industry["industry_id"],
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        return {
            "id": f"active_schema_{selected_industry['industry_id']}_{timestamp}",
            "version": "task_schema_v1",
            "core_fields": list(CORE_SCHEMA_FIELDS),
            "selected_industry": selected_industry,
            "candidate_industries": candidate_industries,
            "industry_extensions": industry_extensions,
            "candidate_extensions": [],
            "rationale": (
                "Selected from the schema registry during planning using query, competitor, "
                "alias, example-query, and known-competitor signals."
            ),
        }
