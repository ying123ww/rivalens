"""Planning agent for competitor-analysis tasks."""

from datetime import datetime, timezone
from typing import Any

from rivalens.agents.messages import create_agent_message
from rivalens.schema import ActiveKnowledgeSchema, Competitor, CompetitorAnalysisState
from rivalens.schema_registry import CORE_SCHEMA_FIELDS, SchemaRegistry


class PlanningAgent:
    def __init__(
        self,
        schema_registry: SchemaRegistry | None = None,
    ):
        self.schema_registry = schema_registry or SchemaRegistry()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []

        normalized = self._normalize_competitors(competitors)
        active_schema = self._select_active_schema(query, normalized)
        candidate_industries = active_schema.get("candidate_industries", [])
        industry_extensions = active_schema.get("industry_extensions", [])

        message = create_agent_message(
            sender="planner",
            receiver="collection",
            message_type="schema_selection",
            payload={
                "active_schema": active_schema,
                "candidate_count": len(candidate_industries),
            },
        )

        return {
            "competitors": normalized,
            "active_knowledge_schema": active_schema,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "planner",
                    "action": "normalize_scope_and_select_schema",
                    "input": {"query": query, "competitors": competitors},
                    "output": {
                        "competitor_count": len(normalized),
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
