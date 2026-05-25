"""Evidence collection agent for competitor analysis."""

import asyncio
from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.research import ResearchToolkit
from rivalens.schema import CompetitorAnalysisState


class CollectionAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        schema_message = latest_message_for(
            state,
            receiver="collection",
            message_type="schema_selection",
            sender="planner",
        )
        schema_payload = schema_message.get("payload", {}) if schema_message else {}
        active_schema = state.get("active_knowledge_schema") or schema_payload.get("active_schema", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []
        deep = bool(task.get("deep_research", True))
        verbose = bool(task.get("verbose", True))

        evidence_items = list(state.get("evidence_items", []))
        research_artifacts = list(state.get("research_artifacts", []))
        contexts: list[dict[str, Any]] = []
        failed_tasks: list[dict[str, Any]] = []
        collection_tasks = self._build_collection_tasks(query, competitors, active_schema)

        results = await asyncio.gather(
            *[
                self._run_collection_task(collection_task, deep=deep, verbose=verbose)
                for collection_task in collection_tasks
            ],
            return_exceptions=True,
        )

        for collection_task, result in zip(collection_tasks, results, strict=True):
            if isinstance(result, Exception):
                failed_tasks.append(
                    {
                        "collection_task_id": collection_task["id"],
                        "dimension_id": collection_task["dimension_id"],
                        "competitor": collection_task["competitor"],
                        "error": str(result),
                    }
                )
                continue

            sources = self._assign_evidence_ids(result["sources"], len(evidence_items), collection_task)
            evidence_items.extend(sources)
            contexts.append(result)
            research_artifacts.append(
                {
                    "id": f"artifact_collection_{len(research_artifacts) + 1}",
                    "agent": "collection",
                    "mode": result["mode"],
                    "query": result["query"],
                    "competitor": collection_task["competitor"],
                    "dimension_id": collection_task["dimension_id"],
                    "dimension_name": collection_task["dimension_name"],
                    "collection_task_id": collection_task["id"],
                    "context": result["context"],
                    "evidence_ids": [source.get("id", "") for source in sources],
                    "costs": result["costs"],
                }
            )

        evidence_ids = [item.get("id", "") for item in evidence_items]
        research_pool_summary = self.research_toolkit.summarize_research_pool()
        message = create_agent_message(
            sender="collection",
            receiver="knowledge_structuring",
            message_type="evidence",
            payload={
                "evidence_count": len(evidence_items),
                "research_runs": len(contexts),
                "collection_task_count": len(collection_tasks),
                "failed_task_count": len(failed_tasks),
                "dimensions": sorted({collection_task["dimension_id"] for collection_task in collection_tasks}),
            },
            artifact_ids=[artifact.get("id", "") for artifact in research_artifacts if artifact.get("agent") == "collection"],
            evidence_ids=evidence_ids,
        )

        return {
            "evidence_items": evidence_items,
            "research_artifacts": research_artifacts,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "collection",
                    "action": "collect_public_evidence",
                    "input": {
                        "query": query,
                        "competitors": competitors,
                        "message_id": schema_message.get("id") if schema_message else None,
                        "active_schema_id": active_schema.get("id"),
                        "collection_task_count": len(collection_tasks),
                        "dimensions": sorted({collection_task["dimension_id"] for collection_task in collection_tasks}),
                    },
                    "output": {
                        "evidence_count": len(evidence_items),
                        "research_runs": len(contexts),
                        "failed_task_count": len(failed_tasks),
                        "research_pool": research_pool_summary,
                    },
                }
            ],
        }

    async def _run_collection_task(
        self,
        collection_task: dict[str, str],
        deep: bool,
        verbose: bool,
    ) -> dict[str, Any]:
        return await self.research_toolkit.collect_schema_evidence(
            collection_task=collection_task,
            deep=deep,
            verbose=verbose,
        )

    def _build_collection_tasks(
        self,
        query: str,
        competitors: list[Any],
        active_schema: dict[str, Any],
    ) -> list[dict[str, str]]:
        normalized_competitors = self._normalize_competitors(competitors)
        dimensions = self._schema_dimensions(active_schema)
        collection_tasks = []

        for competitor in normalized_competitors:
            for dimension in dimensions:
                collection_tasks.append(
                    {
                        "id": self._task_id(competitor, dimension["id"]),
                        "competitor": competitor,
                        "dimension_id": dimension["id"],
                        "dimension_name": dimension["name"],
                        "dimension_type": dimension["type"],
                        "query": self._schema_aware_query(query, competitor, dimension, active_schema),
                    }
                )

        return collection_tasks

    def _normalize_competitors(self, competitors: list[Any]) -> list[str]:
        if not competitors:
            return [""]

        normalized = []
        for competitor in competitors:
            name = competitor.get("name", "") if isinstance(competitor, dict) else str(competitor)
            normalized.append(name)
        return [name for name in normalized if name] or [""]

    def _schema_dimensions(self, active_schema: dict[str, Any]) -> list[dict[str, str]]:
        core_descriptions = {
            "feature_tree": "product capabilities, feature availability, feature maturity, and product packaging",
            "pricing_model": "pricing pages, plans, billing units, packaging, enterprise pricing, and free tiers",
            "user_personas": "target users, buyer personas, use cases, jobs to be done, and customer segments",
        }
        dimensions = []

        for field in active_schema.get("core_fields", []) or ["feature_tree", "pricing_model", "user_personas"]:
            dimensions.append(
                {
                    "id": field,
                    "name": field.replace("_", " ").title(),
                    "type": "core",
                    "description": core_descriptions.get(field, field.replace("_", " ")),
                }
            )

        for extension in active_schema.get("industry_extensions", []):
            extension_id = extension.get("id", "")
            if not extension_id:
                continue
            dimensions.append(
                {
                    "id": extension_id,
                    "name": extension.get("name", extension_id.replace("_", " ").title()),
                    "type": "industry_extension",
                    "description": extension.get("description", extension_id.replace("_", " ")),
                }
            )

        deduped: dict[str, dict[str, str]] = {}
        for dimension in dimensions:
            deduped[dimension["id"]] = dimension
        return list(deduped.values())

    def _schema_aware_query(
        self,
        query: str,
        competitor: str,
        dimension: dict[str, str],
        active_schema: dict[str, Any],
    ) -> str:
        selected_industry = active_schema.get("selected_industry", {}).get("name", "unknown industry")
        competitor_line = f"Competitor: {competitor}" if competitor else "Competitor: infer from the user query"
        return "\n".join(
            [
                query,
                competitor_line,
                f"Selected industry: {selected_industry}",
                f"Research focus: {dimension['name']} ({dimension['type']})",
                f"Focus definition: {dimension['description']}",
                "Collect public, source-backed evidence only. Prefer official pages, pricing pages, docs, reviews, news, and marketplace listings when relevant.",
            ]
        )

    def _task_id(self, competitor: str, dimension_id: str) -> str:
        competitor_slug = self._slug(competitor or "query")
        return f"collect_{competitor_slug}_{self._slug(dimension_id)}"

    def _slug(self, value: str) -> str:
        return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_") or "unknown"

    def _assign_evidence_ids(
        self,
        sources: list[dict[str, Any]],
        offset: int,
        collection_task: dict[str, str],
    ) -> list[dict[str, Any]]:
        assigned = []
        for index, source in enumerate(sources, start=offset + 1):
            item = dict(source)
            item["id"] = f"ev_{index}"
            item["competitor"] = item.get("competitor") or collection_task["competitor"]
            item["collection_task_id"] = collection_task["id"]
            item["dimension_id"] = collection_task["dimension_id"]
            item["dimension_name"] = collection_task["dimension_name"]
            assigned.append(item)
        return assigned
