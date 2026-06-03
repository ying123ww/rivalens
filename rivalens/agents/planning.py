"""Planning agent for competitor-analysis tasks."""

from datetime import datetime, timezone
from typing import Any

from langsmith import traceable, utils as langsmith_utils

from rivalens.agents.industry_direction import IndustryDirectionSkill
from rivalens.agents.messages import create_agent_message
from rivalens.file_context import (
    build_file_context,
    file_context_summary,
    get_task_file_references,
)
from rivalens.schema import (
    ActiveKnowledgeSchema,
    AnalysisDimension,
    Competitor,
    CompetitorAnalysisState,
    IndustryDirectionPlan,
    SchemaExtension,
)
from rivalens.report_sections import report_targets_for_dimension
from rivalens.schema_registry import CORE_SCHEMA_FIELDS, SchemaRegistry


def _competitor_names(competitors: Any) -> list[str]:
    if competitors in (None, ""):
        return []
    if not isinstance(competitors, list):
        competitors = [competitors]

    names = []
    for competitor in competitors:
        if isinstance(competitor, dict):
            name = competitor.get("name", "")
        else:
            name = str(competitor)
        if name:
            names.append(name)
    return names


def _direction_ids(directions: list[dict[str, Any]]) -> list[str]:
    return [
        direction.get("direction_id", "")
        for direction in directions
        if direction.get("direction_id")
    ]


def _planning_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    state = inputs.get("state") or {}
    task = state.get("task", {}) if isinstance(state, dict) else {}
    competitors = state.get("competitors") or task.get("competitors") or []
    file_context = state.get("file_context") or {}

    return {
        "query": task.get("query", ""),
        "competitors": _competitor_names(competitors),
        "competitor_count": len(_competitor_names(competitors)),
        "file_source_count": len(file_context.get("sources", [])),
        "file_chunk_count": len(file_context.get("chunks", [])),
        "custom_analysis_direction_count": len(
            task.get("custom_analysis_directions") or []
        ),
        "industry_directions_confirmed": bool(
            task.get("industry_directions_confirmed"),
        ),
        "provided_industry_direction_plan": bool(task.get("industry_direction_plan")),
    }


def _planning_trace_outputs(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"output_type": type(output).__name__}

    active_schema = output.get("active_knowledge_schema") or {}
    analysis_dimensions = output.get("analysis_dimensions") or []
    selected_industry = active_schema.get("selected_industry") or {}
    industry_direction_plan = output.get("industry_direction_plan") or {}
    final_analysis_plan = industry_direction_plan.get("final_analysis_plan") or {}
    messages = output.get("messages") or []

    return {
        "competitors": _competitor_names(output.get("competitors") or []),
        "selected_industry": selected_industry.get("industry_id", ""),
        "selected_industry_name": selected_industry.get("name", ""),
        "active_schema_id": active_schema.get("id", ""),
        "candidate_industry_count": len(active_schema.get("candidate_industries", [])),
        "industry_extension_count": len(active_schema.get("industry_extensions", [])),
        "analysis_dimension_count": len(analysis_dimensions),
        "detected_competitors": list(
            industry_direction_plan.get("detected_competitors") or []
        ),
        "default_direction_ids": _direction_ids(
            industry_direction_plan.get("default_directions") or []
        ),
        "planner_added_direction_ids": _direction_ids(
            industry_direction_plan.get("planner_added_directions") or []
        ),
        "user_added_direction_ids": _direction_ids(
            industry_direction_plan.get("user_added_directions") or []
        ),
        "final_direction_ids": _direction_ids(
            industry_direction_plan.get("final_directions") or []
        ),
        "scope_limited_by_query": bool(final_analysis_plan.get("scope_limited_by_query")),
        "planner_supplement_skipped": bool(
            final_analysis_plan.get("planner_supplement_skipped"),
        ),
        "industry_selection_method": industry_direction_plan.get(
            "selection_method",
            "",
        ),
        "message_type": messages[-1].get("type", "") if messages else "",
        "research_artifact_count": len(output.get("research_artifacts") or []),
        "agent_event_count": len(output.get("agent_events") or []),
    }


def _planning_trace_extra(state: CompetitorAnalysisState) -> dict[str, Any]:
    task = state.get("task", {})
    competitors = state.get("competitors") or task.get("competitors") or []
    return {
        "metadata": {
            "rivalens_operation": "scope_planner",
            "rivalens_query_length": len(task.get("query", "")),
            "rivalens_competitor_count": len(_competitor_names(competitors)),
            "rivalens_custom_analysis_direction_count": len(
                task.get("custom_analysis_directions") or []
            ),
            "rivalens_industry_directions_confirmed": bool(
                task.get("industry_directions_confirmed"),
            ),
            "rivalens_provided_industry_direction_plan": bool(
                task.get("industry_direction_plan"),
            ),
        },
        "tags": ["rivalens", "planner", "scope"],
    }


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

    async def run(
        self,
        state: CompetitorAnalysisState,
        config: Any | None = None,
    ) -> CompetitorAnalysisState:
        if langsmith_utils.tracing_is_enabled() is not True:
            return await self._run_scope_planner.__wrapped__(self, state)

        return await self._run_scope_planner(
            state,
            config=config,
            langsmith_extra=_planning_trace_extra(state),
        )

    @traceable(
        name="rivalens_scope_planner",
        run_type="chain",
        tags=["rivalens", "planner", "scope"],
        process_inputs=_planning_trace_inputs,
        process_outputs=_planning_trace_outputs,
    )
    async def _run_scope_planner(
        self,
        state: CompetitorAnalysisState,
    ) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []

        file_context = state.get("file_context") or build_file_context(
            get_task_file_references(task)
        )
        planning_query = self._planning_query(query, file_context)
        normalized = self._normalize_competitors(competitors)
        industry_direction_plan = await self._industry_direction_plan(
            task,
            planning_query,
            normalized,
        )
        if not normalized:
            normalized = [
                {"name": competitor}
                for competitor in industry_direction_plan.get(
                    "detected_competitors",
                    [],
                )
            ]
        active_schema = self._select_active_schema(
            planning_query,
            normalized,
            file_context,
            industry_direction_plan,
        )
        analysis_dimensions = self._analysis_dimensions(industry_direction_plan)
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
                    "analysis_dimensions": analysis_dimensions,
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
                "analysis_dimensions": analysis_dimensions,
            },
        )

        return {
            "competitors": normalized,
            "active_knowledge_schema": active_schema,
            "industry_direction_plan": industry_direction_plan,
            "analysis_dimensions": analysis_dimensions,
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
                        "planner_added_direction_count": len(
                            industry_direction_plan.get(
                                "planner_added_directions",
                                [],
                            ),
                        ),
                        "user_added_direction_count": len(
                            industry_direction_plan.get("user_added_directions", []),
                        ),
                        "final_direction_count": len(
                            industry_direction_plan.get("final_directions", []),
                        ),
                        "scope_limited_by_query": bool(
                            (
                                industry_direction_plan.get(
                                    "final_analysis_plan",
                                )
                                or {}
                            ).get("scope_limited_by_query"),
                        ),
                        "registry_extensions_skipped": bool(
                            (
                                industry_direction_plan.get(
                                    "final_analysis_plan",
                                )
                                or {}
                            ).get("scope_limited_by_query"),
                        ),
                        "confidence": active_schema.get("selected_industry", {}).get(
                            "confidence",
                        ),
                        "industry_selection_method": industry_direction_plan.get(
                            "selection_method",
                            "",
                        ),
                        "industry_fallback_reason": industry_direction_plan.get(
                            "fallback_reason",
                            "",
                        ),
                        "extension_count": len(industry_extensions),
                        "analysis_dimension_count": len(analysis_dimensions),
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
        selection_method = industry_direction_plan.get("selection_method", "rule_template")
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
                (
                    "Selected by LLM fallback because deterministic industry rules "
                    "were below the confidence threshold."
                    if selection_method == "llm_fallback"
                    else "Selected from the schema registry during planning using query, competitor, "
                    "alias, example-query, known-competitor, and local file-context signals."
                )
                + " IndustryDirectionSkill runs first to turn the selected industry "
                "and any user-confirmed additions into collection dimensions."
            ),
        }

    async def _industry_direction_plan(
        self,
        task: dict[str, Any],
        planning_query: str,
        competitors: list[Competitor],
    ) -> IndustryDirectionPlan:
        provided = task.get("industry_direction_plan")
        if isinstance(provided, dict) and provided.get("final_directions"):
            return provided

        return await self.industry_direction_skill.build_plan_with_fallback(
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
                    "source_hints": list(direction.get("source_hints", [])),
                    "confidence": 0.82 if direction.get("required", True) else 0.6,
                    "approved": True,
                }
            )
        return extensions

    def _analysis_dimensions(
        self,
        industry_direction_plan: IndustryDirectionPlan,
    ) -> list[AnalysisDimension]:
        dimensions: list[AnalysisDimension] = []
        for index, direction in enumerate(
            industry_direction_plan.get("final_directions", []),
            start=1,
        ):
            direction_id = direction.get("direction_id", "")
            if not direction_id:
                continue
            dimension_id = self._slug(direction_id)
            schema_field_id = f"direction_{dimension_id}"
            description = " ".join(
                part
                for part in [
                    direction.get("description", ""),
                    direction.get("search_focus", ""),
                    direction.get("reason", ""),
                ]
                if part
            )[:500]
            source_hints = list(direction.get("source_hints", []))
            name = direction.get("name", direction_id)
            dimensions.append(
                {
                    "id": dimension_id,
                    "name": name,
                    "description": description,
                    "objective": direction.get("search_focus", "") or description,
                    "priority": "P1" if direction.get("required", True) else "P2",
                    "source_hints": source_hints,
                    "success_criteria": [],
                    "guiding_questions": [],
                    "search_intent": direction.get("search_focus", ""),
                    "minimum_coverage": [
                        "At least two source-backed public evidence items.",
                    ],
                    "risk_level": "medium",
                    "expected_claim_types": ["industry_specific_signal"],
                    "origin": direction.get("origin", ""),
                    "required": direction.get("required", True),
                    "direction_id": direction_id,
                    "schema_field_ids": [schema_field_id],
                    "report_targets": report_targets_for_dimension(
                        dimension_id,
                        name=name,
                        description=description,
                        source_hints=source_hints,
                    ),
                    "report_order": index,
                    "rank": index,
                }
            )
        return dimensions

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
