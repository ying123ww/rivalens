"""Planning agent for competitor-analysis tasks."""

from datetime import datetime, timezone
from typing import Any

from rivalens.agents.industry_direction import IndustryDirectionSkill
from rivalens.agents.messages import create_agent_message
from rivalens.file_context import (
    build_file_context,
    file_context_summary,
    get_task_file_references,
)
from rivalens.schema import (
    ActiveKnowledgeSchema,
    Competitor,
    CompetitorAnalysisState,
    IndustryDirectionPlan,
    SchemaExtension,
)
from rivalens.schema_registry import CORE_SCHEMA_FIELDS, SchemaRegistry


class PlanningAgent:
    def __init__(
        self,
        schema_registry: SchemaRegistry | None = None,
        industry_direction_skill: IndustryDirectionSkill | None = None,
    ):
        self.schema_registry = schema_registry or SchemaRegistry()
        self.industry_direction_skill = (
            industry_direction_skill or IndustryDirectionSkill()
        )

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []

        file_context = state.get("file_context") or build_file_context(
            get_task_file_references(task)
        )
        planning_query = self._planning_query(query, file_context)
        normalized = self._normalize_competitors(competitors)
        industry_direction_plan = self._industry_direction_plan(
            task,
            planning_query,
            normalized,
        )
        active_schema = self._select_active_schema(
            planning_query,
            normalized,
            file_context,
            industry_direction_plan,
        )
        candidate_industries = active_schema.get("candidate_industries", [])
        industry_extensions = active_schema.get("industry_extensions", [])

        research_artifacts = state.get("research_artifacts", []) + [
            {
                "id": "artifact_planning_schema_1",
                "agent": "planner",
                "mode": "schema_selection",
                "query": query,
                "report": (
                    "Selected active knowledge schema "
                    f"{active_schema.get('id', '')} for "
                    f"{active_schema.get('selected_industry', {}).get('name', 'unknown industry')}."
                ),
                "context": {
                    "planning_query": planning_query,
                    "candidate_industries": candidate_industries,
                    "industry_extensions": industry_extensions,
                    "industry_direction_plan": industry_direction_plan,
                    "file_context_summary": file_context.get("summary", ""),
                },
                "costs": 0.0,
            }
        ]
        message = create_agent_message(
            sender="planner",
            receiver="collection",
            message_type="schema_selection",
            payload={
                "active_schema": active_schema,
                "candidate_count": len(candidate_industries),
                "industry_direction_plan": industry_direction_plan,
            },
        )

        return {
            "competitors": normalized,
            "active_knowledge_schema": active_schema,
            "industry_direction_plan": industry_direction_plan,
            "file_context": file_context,
            "research_artifacts": research_artifacts,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "planner",
                    "action": "normalize_scope_and_select_schema",
                    "input": {"query": query, "competitors": competitors},
                    "output": {
                        "competitor_count": len(normalized),
                        "file_count": len(file_context.get("sources", [])),
                        "file_chunk_count": len(file_context.get("chunks", [])),
                        "selected_industry": active_schema.get(
                            "selected_industry",
                        {},
                        ).get("industry_id"),
                        "default_direction_count": len(
                            industry_direction_plan.get("default_directions", []),
                        ),
                        "user_added_direction_count": len(
                            industry_direction_plan.get("user_added_directions", []),
                        ),
                        "final_direction_count": len(
                            industry_direction_plan.get("final_directions", []),
                        ),
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
        industry_direction_plan: IndustryDirectionPlan,
    ) -> ActiveKnowledgeSchema:
        candidate_industries = self.schema_registry.rank_industries(
            query,
            competitors,
        )
        selected_industry = industry_direction_plan.get("industry") or candidate_industries[0]
        candidate_industries = self._merge_candidate_industries(
            selected_industry,
            candidate_industries,
        )
        industry_extensions = self.schema_registry.get_extensions(
            selected_industry["industry_id"],
        )
        industry_extensions = self._dedupe_extensions(
            industry_extensions
            + self._direction_schema_extensions(industry_direction_plan)
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
                " IndustryDirectionSkill runs first to turn the selected industry "
                "and any user-confirmed additions into collection dimensions."
            ),
        }

    def _industry_direction_plan(
        self,
        task: dict[str, Any],
        planning_query: str,
        competitors: list[Competitor],
    ) -> IndustryDirectionPlan:
        provided = task.get("industry_direction_plan")
        if isinstance(provided, dict) and provided.get("final_directions"):
            return provided

        return self.industry_direction_skill.build_plan(
            query=planning_query,
            competitors=competitors,
            user_directions=task.get("custom_analysis_directions", []),
            user_confirmed=bool(task.get("industry_directions_confirmed", False)),
        )

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

    def _direction_schema_extensions(
        self,
        industry_direction_plan: IndustryDirectionPlan,
    ) -> list[SchemaExtension]:
        extensions = []
        for direction in industry_direction_plan.get("final_directions", []):
            direction_id = direction.get("direction_id", "")
            if not direction_id:
                continue
            extensions.append(
                {
                    "id": f"direction_{self._slug(direction_id)}",
                    "name": direction.get("name", direction_id),
                    "description": " ".join(
                        part
                        for part in [
                            direction.get("description", ""),
                            direction.get("search_focus", ""),
                        ]
                        if part
                    )[:500],
                    "origin": (
                        "user_requested"
                        if direction.get("origin") == "user_requested"
                        else "schema_registry"
                    ),
                    "evidence_ids": [],
                    "confidence": 0.82 if direction.get("required", True) else 0.6,
                    "approved": True,
                }
            )
        return extensions

    def _merge_candidate_industries(
        self,
        selected_industry: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = [selected_industry]
        selected_id = selected_industry.get("industry_id")
        merged.extend(
            candidate
            for candidate in candidates
            if candidate.get("industry_id") != selected_id
        )
        return merged

    def _dedupe_extensions(
        self,
        extensions: list[SchemaExtension],
    ) -> list[SchemaExtension]:
        deduped: dict[str, SchemaExtension] = {}
        for extension in extensions:
            extension_id = extension.get("id", "")
            if extension_id:
                deduped[extension_id] = extension
        return list(deduped.values())

    def _slug(self, value: str) -> str:
        return (
            "".join(
                character.lower() if character.isalnum() else "_"
                for character in value
            ).strip("_")
            or "unknown"
        )
