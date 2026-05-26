"""Planning agent for competitor-analysis tasks."""

from datetime import datetime, timezone
from typing import Any

from rivalens.agents.messages import create_agent_message
from rivalens.file_context import (
    build_file_context,
    file_context_summary,
    get_task_file_references,
)
from rivalens.research import ResearchToolkit
from rivalens.schema import (
    ActiveKnowledgeSchema,
    Competitor,
    CompetitorAnalysisState,
    SchemaExtension,
)
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

        file_context = state.get("file_context") or build_file_context(
            get_task_file_references(task)
        )
        planning_query = self._planning_query(query, file_context)
        normalized = self._normalize_competitors(competitors)
        outline = await self.research_toolkit.generate_outline(
            query=planning_query,
            verbose=verbose,
        )
        active_schema = self._select_active_schema(
            planning_query,
            normalized,
            file_context,
        )
        candidate_industries = active_schema.get("candidate_industries", [])
        industry_extensions = active_schema.get("industry_extensions", [])

        research_artifacts = state.get("research_artifacts", []) + [
            {
                "id": "artifact_planning_outline_1",
                "agent": "planner",
                "mode": outline["mode"],
                "query": query,
                "report": outline["report"],
                "context": {
                    "outline_context": outline["context"],
                    "file_context_summary": file_context.get("summary", ""),
                },
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
            "file_context": file_context,
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
                        "file_count": len(file_context.get("sources", [])),
                        "file_chunk_count": len(file_context.get("chunks", [])),
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
        file_context: dict[str, Any],
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
            "candidate_extensions": self._file_candidate_extensions(file_context),
            "rationale": (
                "Selected from the schema registry during planning using query, competitor, "
                "alias, example-query, known-competitor, and local file-context signals."
            ),
        }

    def _planning_query(self, query: str, file_context: dict[str, Any]) -> str:
        summary = file_context_summary(file_context)
        search_hints = file_context.get("search_hints", [])
        if not summary and not search_hints:
            return query

        return "\n".join(
            [
                query,
                "",
                "User-provided local file context for planning and schema selection:",
                summary,
                "Search/schema hints:",
                "\n".join(f"- {hint}" for hint in search_hints[:10]),
            ]
        )

    def _file_candidate_extensions(
        self,
        file_context: dict[str, Any],
    ) -> list[SchemaExtension]:
        extensions = []
        for index, hint in enumerate(
            file_context.get("search_hints", [])[:6],
            start=1,
        ):
            extensions.append(
                {
                    "id": f"file_signal_{index}",
                    "name": f"File signal {index}",
                    "description": hint[:400],
                    "origin": "user_requested",
                    "evidence_ids": [],
                    "confidence": 0.55,
                    "approved": False,
                }
            )
        return extensions
