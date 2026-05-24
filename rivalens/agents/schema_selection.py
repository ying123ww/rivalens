"""Select the active knowledge schema for a competitor-analysis task."""

from datetime import datetime, timezone

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import ActiveKnowledgeSchema, CompetitorAnalysisState
from rivalens.schema_registry import CORE_SCHEMA_FIELDS, SchemaRegistry


class SchemaSelectionAgent:
    def __init__(self, schema_registry: SchemaRegistry | None = None):
        self.schema_registry = schema_registry or SchemaRegistry()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        plan_message = latest_message_for(
            state,
            receiver="schema_selection",
            message_type="plan",
            sender="planner",
        )
        plan_payload = plan_message.get("payload", {}) if plan_message else {}
        query = plan_payload.get("query") or task.get("query", "")
        competitors = plan_payload.get("competitors") or state.get("competitors") or []
        candidate_industries = self.schema_registry.rank_industries(query, competitors)
        selected_industry = candidate_industries[0]
        industry_extensions = self.schema_registry.get_extensions(selected_industry["industry_id"])
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        active_schema: ActiveKnowledgeSchema = {
            "id": f"active_schema_{selected_industry['industry_id']}_{timestamp}",
            "version": "task_schema_v1",
            "core_fields": list(CORE_SCHEMA_FIELDS),
            "selected_industry": selected_industry,
            "candidate_industries": candidate_industries,
            "industry_extensions": industry_extensions,
            "candidate_extensions": [],
            "rationale": (
                "Selected from the schema registry using query, competitor, "
                "alias, example-query, and known-competitor signals."
            ),
        }

        message = create_agent_message(
            sender="schema_selection",
            receiver="collection",
            message_type="schema_selection",
            payload={
                "active_schema": active_schema,
                "candidate_count": len(candidate_industries),
            },
        )

        return {
            "active_knowledge_schema": active_schema,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "schema_selection",
                    "action": "select_active_knowledge_schema",
                    "input": {
                        "query": query,
                        "competitor_count": len(competitors),
                        "message_id": plan_message.get("id") if plan_message else None,
                    },
                    "output": {
                        "selected_industry": selected_industry.get("industry_id"),
                        "confidence": selected_industry.get("confidence"),
                        "extension_count": len(industry_extensions),
                    },
                }
            ],
        }
