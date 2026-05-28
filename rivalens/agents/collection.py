"""Evidence collection agent for competitor analysis."""

import asyncio
from typing import Any

from rivalens.agents.branch_review import BranchReviewAgent
from rivalens.agents.evidence_review import EvidenceQualityReviewer
from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.file_context import format_rag_context
from rivalens.research import ResearchEngineEvidenceCollector
from rivalens.schema import (
    BranchReviewDecision,
    CompetitorAnalysisState,
    EvidenceCollectionResult,
    EvidenceCollectionTask,
    ResearchBranch,
)


class CollectionAgent:
    def __init__(
        self,
        evidence_collector: ResearchEngineEvidenceCollector | None = None,
        branch_reviewer: BranchReviewAgent | None = None,
        evidence_reviewer: EvidenceQualityReviewer | None = None,
        max_branch_depth: int = 1,
        max_expansion_branches: int = 24,
        max_root_branch_hard_limit: int = 80,
    ):
        self.evidence_collector = evidence_collector or ResearchEngineEvidenceCollector()
        self.branch_reviewer = branch_reviewer or BranchReviewAgent(max_depth=max_branch_depth)
        self.evidence_reviewer = evidence_reviewer or EvidenceQualityReviewer()
        self.max_branch_depth = max_branch_depth
        self.max_expansion_branches = max_expansion_branches
        self.max_root_branch_hard_limit = max_root_branch_hard_limit

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        schema_message = latest_message_for(
            state,
            receiver="collection",
            message_type="schema_selection",
            sender="planner",
        )
        schema_payload = schema_message.get("payload", {}) if schema_message else {}
        active_schema = state.get("active_knowledge_schema") or schema_payload.get(
            "active_schema",
            {},
        )
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []
        verbose = bool(task.get("verbose", True))

        evidence_items = list(state.get("evidence_items", []))
        research_artifacts = list(state.get("research_artifacts", []))
        research_branches = list(state.get("research_branches", []))
        branch_review_decisions = list(state.get("branch_review_decisions", []))
        evidence_reviews = list(state.get("evidence_reviews", []))
        contexts: list[dict[str, Any]] = []
        failed_tasks: list[dict[str, Any]] = []
        root_branches = self._build_root_branches(
            query,
            competitors,
            active_schema,
            state.get("analysis_dimensions", []),
        )
        root_branch_limit_exceeded = len(root_branches) > self.max_root_branch_hard_limit
        if root_branch_limit_exceeded:
            root_branches = root_branches[: self.max_root_branch_hard_limit]
        frontier = root_branches
        research_branches.extend(root_branches)
        processed_branch_count = 0
        expansion_branch_count = 0
        file_context = state.get("file_context", {})

        while frontier:
            active_frontier = frontier
            processed_branch_count += len(active_frontier)
            collection_tasks = [
                self._branch_to_collection_task(branch)
                for branch in active_frontier
            ]
            for collection_task in collection_tasks:
                collection_task["query"] = self._with_file_rag(
                    collection_task["query"],
                    file_context,
                )

            results = await asyncio.gather(
                *[
                    self._run_collection_task(collection_task, verbose=verbose)
                    for collection_task in collection_tasks
                ],
                return_exceptions=True,
            )

            next_frontier: list[ResearchBranch] = []
            for branch, collection_task, result in zip(
                active_frontier,
                collection_tasks,
                results,
                strict=True,
            ):
                if isinstance(result, Exception):
                    branch["status"] = "stopped"
                    failed_tasks.append(
                        {
                            "collection_task_id": collection_task["id"],
                            "branch_id": branch["id"],
                            "dimension_id": collection_task["dimension_id"],
                            "competitor": collection_task["competitor"],
                            "error": str(result),
                        }
                    )
                    continue

                sources = self._assign_evidence_ids(
                    result["evidence_items"],
                    len(evidence_items),
                    collection_task,
                )
                branch["evidence_ids"] = [source.get("id", "") for source in sources]
                evidence_items.extend(sources)
                evidence_review = self.evidence_reviewer.review(branch, sources)
                evidence_reviews.append(evidence_review)
                contexts.append(result)
                research_artifacts.append(
                    {
                        "id": f"artifact_collection_{len(research_artifacts) + 1}",
                        "agent": "collection",
                        "mode": result["mode"],
                        "query": result["query"],
                        "competitor": collection_task["competitor"],
                        "branch_id": branch["id"],
                        "dimension_id": collection_task["dimension_id"],
                        "dimension_name": collection_task["dimension_name"],
                        "collection_task_id": collection_task["id"],
                        "context": result["context"],
                        "evidence_ids": [source.get("id", "") for source in sources],
                        "costs": result["costs"],
                    }
                )

                decision = self.branch_reviewer.review(
                    branch=branch,
                    evidence_items=sources,
                    active_schema=active_schema,
                    root_query=query,
                    evidence_review=evidence_review,
                )
                branch_review_decisions.append(decision)
                branch["review_decision"] = decision["decision"]
                if decision["decision"] in {"expand", "retry"}:
                    branch["status"] = "expanded"
                    remaining_branch_slots = self.max_expansion_branches - expansion_branch_count
                    if remaining_branch_slots <= 0:
                        branch["status"] = "stopped"
                        branch["review_decision"] = "stop"
                        decision["decision"] = "stop"
                        decision["reasons"] = decision.get("reasons", []) + [
                            "Expansion branch budget exhausted."
                        ]
                        continue
                    children = self._build_child_branches(branch, decision)[
                        :remaining_branch_slots
                    ]
                    expansion_branch_count += len(children)
                    next_frontier.extend(children)
                    research_branches.extend(children)
                else:
                    branch["status"] = "stopped"

            frontier = [
                branch
                for branch in next_frontier
                if branch.get("depth", 0) <= self.max_branch_depth
            ]

        accepted_evidence_ids = self._accepted_evidence_ids(evidence_reviews)
        rejected_evidence_ids = self._rejected_evidence_ids(evidence_reviews)
        collection_coverage = self._summarize_collection_coverage(evidence_items)
        evidence_payload = {
            "evidence_count": len(evidence_items),
            "accepted_evidence_count": len(accepted_evidence_ids),
            "rejected_evidence_count": len(rejected_evidence_ids),
            "evidence_review_count": len(evidence_reviews),
            "research_runs": len(contexts),
            "collection_task_count": processed_branch_count,
            "failed_task_count": len(failed_tasks),
            "dimensions": sorted(
                {branch["dimension_id"] for branch in research_branches}
            ),
        }
        message = create_agent_message(
            sender="collection",
            receiver="knowledge_structuring",
            message_type="evidence",
            payload=evidence_payload,
            artifact_ids=[
                artifact.get("id", "")
                for artifact in research_artifacts
                if artifact.get("agent") == "collection"
            ],
            evidence_ids=accepted_evidence_ids,
        )
        analysis_message = create_agent_message(
            sender="collection",
            receiver="analysis",
            message_type="evidence",
            payload=evidence_payload,
            artifact_ids=message["artifact_ids"],
            evidence_ids=accepted_evidence_ids,
        )

        return {
            "evidence_items": evidence_items,
            "evidence_reviews": evidence_reviews,
            "research_branches": research_branches,
            "branch_review_decisions": branch_review_decisions,
            "research_artifacts": research_artifacts,
            "messages": state.get("messages", []) + [message, analysis_message],
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
                        "root_branch_count": len(root_branches),
                        "max_branch_depth": self.max_branch_depth,
                        "root_branch_limit_exceeded": root_branch_limit_exceeded,
                        "max_expansion_branches": self.max_expansion_branches,
                        "max_root_branch_hard_limit": self.max_root_branch_hard_limit,
                        "dimensions": sorted(
                            {branch["dimension_id"] for branch in research_branches}
                        ),
                    },
                    "output": {
                        "evidence_count": len(evidence_items),
                        "research_runs": len(contexts),
                        "failed_task_count": len(failed_tasks),
                        "branch_count": len(research_branches),
                        "expanded_branch_count": expansion_branch_count,
                        "evidence_review_count": len(evidence_reviews),
                        "accepted_evidence_count": len(accepted_evidence_ids),
                        "rejected_evidence_count": len(rejected_evidence_ids),
                        "coverage": collection_coverage,
                    },
                }
            ],
        }

    async def _run_collection_task(
        self,
        collection_task: EvidenceCollectionTask,
        verbose: bool,
    ) -> EvidenceCollectionResult:
        return await self.evidence_collector.collect(
            collection_task=collection_task,
            deep=False,
            verbose=verbose,
        )

    def _build_root_branches(
        self,
        query: str,
        competitors: list[Any],
        active_schema: dict[str, Any],
        analysis_dimensions: list[dict[str, Any]] | None = None,
    ) -> list[ResearchBranch]:
        normalized_competitors = self._normalize_competitors(competitors)
        dimensions = self._collection_dimensions(active_schema, analysis_dimensions or [])
        branches = []

        for competitor in normalized_competitors:
            for dimension in dimensions:
                branch_id = self._task_id(competitor, dimension["id"])
                branches.append(
                    {
                        "id": branch_id,
                        "parent_id": None,
                        "depth": 0,
                        "path": [dimension["id"]],
                        "competitor": competitor,
                        "dimension_id": dimension["id"],
                        "dimension_name": dimension["name"],
                        "dimension_type": dimension["type"],
                        "topic": dimension["name"],
                        "query": self._schema_aware_query(
                            query,
                            competitor,
                            dimension,
                            active_schema,
                        ),
                        "evidence_ids": [],
                        "status": "active",
                        "expansion_reason": (
                            "Root branch generated from confirmed analysis dimension."
                            if dimension["type"] == "analysis_dimension"
                            else "Root branch generated from active schema dimension."
                        ),
                        "review_decision": None,
                    }
                )

        return branches

    def _branch_to_collection_task(self, branch: ResearchBranch) -> EvidenceCollectionTask:
        return {
            "id": branch["id"],
            "branch_id": branch["id"],
            "parent_branch_id": branch.get("parent_id"),
            "depth": branch.get("depth", 0),
            "topic": branch.get("topic", ""),
            "expansion_reason": branch.get("expansion_reason", ""),
            "competitor": branch.get("competitor", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "dimension_type": branch.get("dimension_type", ""),
            "query": branch.get("query", ""),
        }

    def _build_child_branches(
        self,
        parent: ResearchBranch,
        decision: BranchReviewDecision,
    ) -> list[ResearchBranch]:
        children = []
        next_topics = decision.get("next_topics", [])
        for index, query in enumerate(decision.get("next_queries", []), start=1):
            topic = (
                next_topics[index - 1]
                if index <= len(next_topics)
                else f"{parent['topic']} follow-up {index}"
            )
            child_id = f"{parent['id']}_d{parent.get('depth', 0) + 1}_{index}"
            children.append(
                {
                    "id": child_id,
                    "parent_id": parent["id"],
                    "depth": parent.get("depth", 0) + 1,
                    "path": list(parent.get("path", [])) + [topic],
                    "competitor": parent.get("competitor", ""),
                    "dimension_id": parent.get("dimension_id", ""),
                    "dimension_name": parent.get("dimension_name", ""),
                    "dimension_type": parent.get("dimension_type", ""),
                    "topic": topic,
                    "query": query,
                    "evidence_ids": [],
                    "status": "active",
                    "expansion_reason": (
                        "; ".join(decision.get("evidence_gaps", []))
                        or "Branch reviewer requested expansion."
                    ),
                    "review_decision": None,
                }
            )
        return children

    def _normalize_competitors(self, competitors: list[Any]) -> list[str]:
        if not competitors:
            return [""]

        normalized = []
        for competitor in competitors:
            name = (
                competitor.get("name", "")
                if isinstance(competitor, dict)
                else str(competitor)
            )
            normalized.append(name)
        return [name for name in normalized if name] or [""]

    def _collection_dimensions(
        self,
        active_schema: dict[str, Any],
        analysis_dimensions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if analysis_dimensions:
            return [
                {
                    "id": dimension.get("id", ""),
                    "name": dimension.get("name", dimension.get("id", "")),
                    "type": "analysis_dimension",
                    "description": dimension.get("description", ""),
                    "guiding_questions": dimension.get("guiding_questions", []),
                    "search_intent": dimension.get("search_intent", ""),
                    "priority": dimension.get("priority", "P1"),
                }
                for dimension in analysis_dimensions
                if dimension.get("id")
            ]
        return self._schema_dimensions(active_schema)

    def _schema_dimensions(self, active_schema: dict[str, Any]) -> list[dict[str, str]]:
        core_descriptions = {
            "feature_tree": (
                "product capabilities, feature availability, feature maturity, "
                "and product packaging"
            ),
            "pricing_model": (
                "pricing pages, plans, billing units, packaging, enterprise "
                "pricing, and free tiers"
            ),
            "user_personas": (
                "target users, buyer personas, use cases, jobs to be done, "
                "and customer segments"
            ),
        }
        dimensions = []

        for field in active_schema.get("core_fields", []) or [
            "feature_tree",
            "pricing_model",
            "user_personas",
        ]:
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
                    "name": extension.get(
                        "name",
                        extension_id.replace("_", " ").title(),
                    ),
                    "type": "industry_extension",
                    "description": extension.get(
                        "description",
                        extension_id.replace("_", " "),
                    ),
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
        dimension: dict[str, Any],
        active_schema: dict[str, Any],
    ) -> str:
        selected_industry = active_schema.get("selected_industry", {}).get(
            "name",
            "unknown industry",
        )
        competitor_line = (
            f"Competitor: {competitor}"
            if competitor
            else "Competitor: infer from the user query"
        )
        return "\n".join(
            [
                query,
                competitor_line,
                f"Selected industry: {selected_industry}",
                f"Research focus: {dimension['name']} ({dimension['type']})",
                f"Focus definition: {dimension['description']}",
                self._guiding_questions_line(dimension),
                dimension.get("search_intent", ""),
                "Collect public, source-backed evidence only. Prefer official "
                "pages, pricing pages, docs, reviews, news, and marketplace "
                "listings when relevant.",
            ]
        )

    def _guiding_questions_line(self, dimension: dict[str, Any]) -> str:
        guiding_questions = dimension.get("guiding_questions", [])
        if not guiding_questions:
            return ""
        return "Guiding questions: " + " | ".join(str(question) for question in guiding_questions)

    def _with_file_rag(
        self,
        query: str,
        file_context: dict[str, Any],
    ) -> str:
        rag_context = format_rag_context(file_context, query, limit=4)
        if not rag_context:
            return query
        return "\n".join([query, "", rag_context])

    def _task_id(self, competitor: str, dimension_id: str) -> str:
        competitor_slug = self._slug(competitor or "query")
        return f"collect_{competitor_slug}_{self._slug(dimension_id)}"

    def _slug(self, value: str) -> str:
        return (
            "".join(
                character.lower() if character.isalnum() else "_"
                for character in value
            ).strip("_")
            or "unknown"
        )

    def _assign_evidence_ids(
        self,
        sources: list[dict[str, Any]],
        offset: int,
        collection_task: EvidenceCollectionTask,
    ) -> list[dict[str, Any]]:
        assigned = []
        for index, source in enumerate(sources, start=offset + 1):
            item = dict(source)
            item["id"] = f"ev_{index}"
            item["competitor"] = item.get("competitor") or collection_task["competitor"]
            item["branch_id"] = item.get("branch_id") or collection_task.get(
                "branch_id",
                collection_task["id"],
            )
            item["parent_branch_id"] = item.get(
                "parent_branch_id",
                collection_task.get("parent_branch_id"),
            )
            item["collection_task_id"] = collection_task["id"]
            item["dimension_id"] = collection_task["dimension_id"]
            item["dimension_name"] = collection_task["dimension_name"]
            assigned.append(item)
        return assigned

    def _summarize_collection_coverage(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "source_count": len(evidence_items),
            "by_competitor": self._count_by(evidence_items, "competitor"),
            "by_dimension": self._count_by(evidence_items, "dimension_id"),
        }

    def _count_by(self, evidence_items: list[dict[str, Any]], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in evidence_items:
            key = item.get(field) or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _accepted_evidence_ids(self, evidence_reviews: list[dict[str, Any]]) -> list[str]:
        accepted: list[str] = []
        for review in evidence_reviews:
            accepted.extend(review.get("accepted_evidence_ids", []))
        return list(dict.fromkeys(accepted))

    def _rejected_evidence_ids(self, evidence_reviews: list[dict[str, Any]]) -> list[str]:
        rejected: list[str] = []
        for review in evidence_reviews:
            rejected.extend(review.get("rejected_evidence_ids", []))
        return list(dict.fromkeys(rejected))
