"""Evidence collection agent for competitor analysis."""

import asyncio
import os
from typing import Any

from rivalens.agents.coverage_state import BranchCoverageStateBuilder
from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.evidence_review import EvidenceQualityReviewer
from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.agents.search_query_builder import SearchQueryBuilder
from rivalens.agents.success_criteria import normalize_success_criteria
from rivalens.file_context import format_rag_context
from rivalens.report_routing import primary_report_section_id
from rivalens.research import ResearchEngineEvidenceCollector, ResearchMode
from rivalens.research.evidence_collector import _trace_collection_task
from rivalens.research.trace_context import langsmith_extra_for_trace_context
from rivalens.schema import (
    CompetitorAnalysisState,
    EvidenceCollectionResult,
    EvidenceCollectionTask,
    ResearchBrief,
    ResearchBranch,
    ResearchTask,
    SOURCE_TYPE_PRIORITY,
)


class CollectionAgent:
    def __init__(
        self,
        evidence_collector: ResearchEngineEvidenceCollector | None = None,
        evidence_reviewer: EvidenceQualityReviewer | None = None,
        coverage_reviewer: CoverageReviewer | None = None,
        search_query_builder: SearchQueryBuilder | None = None,
        max_branch_depth: int = 1,
        max_expansion_branches: int = 10,
        max_root_branch_hard_limit: int | None = None,
        max_concurrent_collections: int | None = None,
    ):
        self.evidence_collector = evidence_collector or ResearchEngineEvidenceCollector()
        self.evidence_reviewer = evidence_reviewer or EvidenceQualityReviewer()
        self.coverage_reviewer = coverage_reviewer or CoverageReviewer()
        self.coverage_state_builder = BranchCoverageStateBuilder(self.coverage_reviewer)
        self.search_query_builder = search_query_builder or SearchQueryBuilder()
        self.max_branch_depth = max_branch_depth
        self.max_expansion_branches = max_expansion_branches
        self.max_root_branch_hard_limit = _int_env(
            max_root_branch_hard_limit,
            "RIVALENS_MAX_ROOT_BRANCHES",
            20,
            minimum=1,
        )
        self.max_concurrent_collections = _int_env(
            max_concurrent_collections,
            "RIVALENS_MAX_CONCURRENT_COLLECTIONS",
            3,
            minimum=1,
        )

    async def run(
        self,
        state: CompetitorAnalysisState,
        config: Any | None = None,
    ) -> CompetitorAnalysisState:
        task = state.get("task", {})
        plan_message = latest_message_for(
            state,
            receiver="collection",
            message_type="research_plan",
            sender="planner",
        )
        plan_payload = plan_message.get("payload", {}) if plan_message else {}
        industry_direction_plan = state.get("industry_direction_plan") or plan_payload.get(
            "industry_direction_plan",
            {},
        )
        analysis_dimensions = state.get("analysis_dimensions") or plan_payload.get(
            "analysis_dimensions",
            [],
        )
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []
        verbose = bool(task.get("verbose", True))

        evidence_items = list(state.get("evidence_items", []))
        research_artifacts = list(state.get("research_artifacts", []))
        research_branches = list(state.get("research_branches", []))
        research_briefs = list(state.get("research_briefs", []))
        research_tasks = list(state.get("research_tasks", []))
        coverage_assessments = list(state.get("coverage_assessments", []))
        evidence_reviews = list(state.get("evidence_reviews", []))
        contexts: list[dict[str, Any]] = []
        failed_tasks: list[dict[str, Any]] = []
        root_branches = self._build_root_branches(
            query,
            competitors,
            industry_direction_plan,
            analysis_dimensions,
        )
        root_branches, root_branch_limit_exceeded = (
            self._limit_root_branches_per_competitor(root_branches)
        )
        frontier = root_branches
        research_branches.extend(root_branches)
        new_briefs = self._build_research_briefs(root_branches)
        research_briefs.extend(new_briefs)
        brief_by_branch = {brief["branch_id"]: brief for brief in new_briefs}
        processed_branch_count = 0
        expansion_branch_count = 0
        selected_follow_up_count = 0
        depth_blocked_follow_up_count = 0
        budget_blocked_follow_up_count = 0
        file_context = state.get("file_context", {})

        while frontier:
            active_frontier = frontier
            processed_branch_count += len(active_frontier)
            planned_tasks = [
                self._branch_to_research_task(branch, brief_by_branch)
                for branch in active_frontier
            ]
            research_tasks.extend(planned_tasks)
            collection_tasks = [
                self._branch_to_collection_task(branch, research_task)
                for branch, research_task in zip(active_frontier, planned_tasks, strict=True)
            ]
            for collection_task in collection_tasks:
                file_rag_context = self._file_rag_context(
                    collection_task["query"],
                    file_context,
                )
                if file_rag_context:
                    collection_task["file_rag_context"] = file_rag_context

            collection_semaphore = asyncio.Semaphore(self.max_concurrent_collections)
            results = await asyncio.gather(
                *[
                    self._run_collection_task_with_limit(
                        collection_semaphore,
                        collection_task,
                        verbose=verbose,
                        trace_config=config,
                    )
                    for collection_task in collection_tasks
                ],
                return_exceptions=True,
            )

            next_frontier: list[ResearchBranch] = []
            for result_index in self._fair_branch_result_indexes(active_frontier):
                branch = active_frontier[result_index]
                research_task = planned_tasks[result_index]
                collection_task = collection_tasks[result_index]
                result = results[result_index]
                if isinstance(result, Exception):
                    branch["status"] = "stopped"
                    failed_tasks.append(
                        {
                            "collection_task_id": collection_task["id"],
                            "branch_id": branch["id"],
                            "analysis_dimension_id": collection_task.get(
                                "analysis_dimension_id",
                                collection_task["dimension_id"],
                            ),
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
                branch["evidence_ids"] = list(
                    dict.fromkeys(
                        branch.get("evidence_ids", [])
                        + [source.get("id", "") for source in sources]
                    )
                )
                evidence_items.extend(sources)
                evidence_review = self.evidence_reviewer.review(branch, sources)
                coverage_assessment = await self.coverage_reviewer.review(
                    branch=branch,
                    evidence_items=sources,
                    evidence_review=evidence_review,
                    research_task_ids=[research_task["id"]],
                )
                evidence_review["coverage_assessment_id"] = coverage_assessment["id"]
                evidence_reviews.append(evidence_review)
                coverage_assessments.append(coverage_assessment)
                contexts.append(result)
                research_artifacts.append(
                    {
                        "id": f"artifact_collection_{len(research_artifacts) + 1}",
                        "agent": "collection",
                        "mode": result["mode"],
                        "query": result["query"],
                        "competitor": collection_task["competitor"],
                        "branch_id": branch["id"],
                        "research_brief_id": collection_task.get("research_brief_id", ""),
                        "research_task_id": collection_task.get("research_task_id", ""),
                        "search_stage": collection_task.get("search_stage", ""),
                        "generated_from_gap": collection_task.get("generated_from_gap", ""),
                        "analysis_dimension_id": collection_task.get(
                            "analysis_dimension_id",
                            collection_task["dimension_id"],
                        ),
                        "dimension_id": collection_task["dimension_id"],
                        "dimension_name": collection_task["dimension_name"],
                        "report_section_id": collection_task.get("report_section_id", ""),
                        "collection_task_id": collection_task["id"],
                        "context": result["context"],
                        "evidence_ids": [source.get("id", "") for source in sources],
                        "costs": result["costs"],
                    }
                )

                follow_up_specs = coverage_assessment.get("selected_follow_up_specs", [])
                focused_decision = coverage_assessment.get("decision", {})
                if follow_up_specs:
                    selected_follow_up_count += len(follow_up_specs)
                if (
                    focused_decision.get("action") != "stop"
                    and follow_up_specs
                    and branch.get("depth", 0) < self.max_branch_depth
                ):
                    branch["status"] = "expanded"
                    remaining_branch_slots = self.max_expansion_branches - expansion_branch_count
                    if remaining_branch_slots <= 0:
                        budget_blocked_follow_up_count += len(follow_up_specs)
                        branch["status"] = "stopped"
                        continue
                    children = self._build_child_branches(
                        branch,
                        follow_up_specs,
                        parent_task_id=research_task["id"],
                    )[:remaining_branch_slots]
                    expansion_branch_count += len(children)
                    next_frontier.extend(children)
                    research_branches.extend(children)
                else:
                    if (
                        focused_decision.get("action") != "stop"
                        and follow_up_specs
                        and branch.get("depth", 0) >= self.max_branch_depth
                    ):
                        depth_blocked_follow_up_count += len(follow_up_specs)
                    branch["status"] = "stopped"

            frontier = [
                branch
                for branch in next_frontier
                if branch.get("depth", 0) <= self.max_branch_depth
            ]

        accepted_evidence_ids = self._accepted_evidence_ids(evidence_reviews)
        rejected_evidence_ids = self._rejected_evidence_ids(evidence_reviews)
        branch_coverage_states = self.coverage_state_builder.build(
            research_branches,
            evidence_reviews,
            evidence_items,
            coverage_assessments,
        )
        self.coverage_state_builder.attach_to_root_branches(
            research_branches,
            branch_coverage_states,
        )
        follow_up_branch_ids = {
            branch.get("id", "")
            for branch in research_branches
            if branch.get("generated_from_gap")
        }
        follow_up_accepted_evidence_ids = [
            evidence_id
            for review in evidence_reviews
            if review.get("branch_id", "") in follow_up_branch_ids
            for evidence_id in review.get("accepted_evidence_ids", [])
        ]
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
                {
                    branch.get("analysis_dimension_id") or branch["dimension_id"]
                    for branch in research_branches
                }
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
            "research_briefs": research_briefs,
            "research_tasks": research_tasks,
            "coverage_assessments": coverage_assessments,
            "branch_coverage_states": branch_coverage_states,
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
                        "message_id": plan_message.get("id") if plan_message else None,
                        "selected_industry": (
                            industry_direction_plan.get("industry") or {}
                        ).get("industry_id"),
                        "collection_phase": "initial_or_gap_collection",
                        "root_branch_count": len(root_branches),
                        "max_branch_depth": self.max_branch_depth,
                        "root_branch_limit_exceeded": root_branch_limit_exceeded,
                        "max_expansion_branches": self.max_expansion_branches,
                        "max_root_branches_per_competitor": self.max_root_branch_hard_limit,
                        "max_concurrent_collections": self.max_concurrent_collections,
                        "dimensions": sorted(
                            {
                                branch.get("analysis_dimension_id")
                                or branch["dimension_id"]
                                for branch in research_branches
                            }
                        ),
                    },
                    "output": {
                        "evidence_count": len(evidence_items),
                        "research_runs": len(contexts),
                        "failed_task_count": len(failed_tasks),
                        "branch_count": len(research_branches),
                        "research_brief_count": len(research_briefs),
                        "research_task_count": len(research_tasks),
                        "expanded_branch_count": expansion_branch_count,
                        "selected_follow_up_count": selected_follow_up_count,
                        "depth_blocked_follow_up_count": depth_blocked_follow_up_count,
                        "budget_blocked_follow_up_count": budget_blocked_follow_up_count,
                        "evidence_review_count": len(evidence_reviews),
                        "coverage_assessment_count": len(coverage_assessments),
                        "accepted_evidence_count": len(accepted_evidence_ids),
                        "accepted_follow_up_evidence_count": len(
                            dict.fromkeys(follow_up_accepted_evidence_ids),
                        ),
                        "rejected_evidence_count": len(rejected_evidence_ids),
                        "branch_coverage_state_count": len(branch_coverage_states),
                        "ready_branch_coverage_count": sum(
                            1
                            for state in branch_coverage_states
                            if state.get("status") == "ready_for_analysis"
                        ),
                        "blocked_branch_coverage_count": sum(
                            1
                            for state in branch_coverage_states
                            if state.get("status") == "blocked"
                        ),
                        "coverage": collection_coverage,
                    },
                }
            ],
        }

    async def _run_collection_task_with_limit(
        self,
        semaphore: asyncio.Semaphore,
        collection_task: EvidenceCollectionTask,
        verbose: bool,
        trace_config: Any | None = None,
    ) -> EvidenceCollectionResult:
        async with semaphore:
            return await self._run_collection_task(
                collection_task,
                verbose=verbose,
                trace_config=trace_config,
            )

    async def _run_collection_task(
        self,
        collection_task: EvidenceCollectionTask,
        verbose: bool,
        trace_config: Any | None = None,
    ) -> EvidenceCollectionResult:
        kwargs: dict[str, Any] = {}
        collect = self.evidence_collector.collect
        if getattr(collect, "__langsmith_traceable__", False):
            trace_context = _trace_collection_task(collection_task)
            kwargs["config"] = trace_config
            kwargs["langsmith_extra"] = langsmith_extra_for_trace_context(
                trace_context,
                operation="collect_evidence",
            )

        return await collect(
            collection_task=collection_task,
            mode=self._research_mode_for_task(collection_task),
            source_urls=collection_task.get("target_urls", []),
            verbose=verbose,
            **kwargs,
        )

    def _research_mode_for_task(
        self,
        collection_task: EvidenceCollectionTask,
    ) -> ResearchMode:
        return ResearchMode.STANDARD_EVIDENCE

    def _fair_branch_result_indexes(
        self,
        branches: list[ResearchBranch],
    ) -> list[int]:
        indexes_by_competitor: dict[str, list[int]] = {}
        competitor_order: list[str] = []
        for index, branch in enumerate(branches):
            competitor = branch.get("competitor", "") or "unknown"
            if competitor not in indexes_by_competitor:
                indexes_by_competitor[competitor] = []
                competitor_order.append(competitor)
            indexes_by_competitor[competitor].append(index)

        ordered_indexes: list[int] = []
        while any(indexes_by_competitor.values()):
            for competitor in competitor_order:
                indexes = indexes_by_competitor[competitor]
                if indexes:
                    ordered_indexes.append(indexes.pop(0))
        return ordered_indexes

    def _build_root_branches(
        self,
        query: str,
        competitors: list[Any],
        industry_direction_plan: dict[str, Any],
        analysis_dimensions: list[dict[str, Any]] | None = None,
    ) -> list[ResearchBranch]:
        normalized_competitors = self._normalize_competitors(competitors)
        dimensions = self._collection_dimensions(analysis_dimensions or [])
        branches = []

        for competitor in normalized_competitors:
            for dimension in [self._competitor_profile_dimension(), *dimensions]:
                analysis_dimension_id = dimension.get("analysis_dimension_id", dimension["id"])
                report_section_id = dimension.get("report_section_id", "")
                branch_id = self._task_id(competitor, analysis_dimension_id)
                query_plan = self.search_query_builder.build(
                    original_query=query,
                    competitor=competitor,
                    dimension=dimension,
                    industry_direction_plan=industry_direction_plan,
                )
                research_goal = self._research_goal(query, competitor, dimension)
                success_criteria = self._success_criteria(query, competitor, dimension)
                branches.append(
                    {
                        "id": branch_id,
                        "research_brief_id": f"brief_{branch_id}",
                        "parent_id": None,
                        "depth": 0,
                        "path": [analysis_dimension_id],
                        "competitor": competitor,
                        "analysis_dimension_id": analysis_dimension_id,
                        "schema_field_ids": list(dimension.get("schema_field_ids", [])),
                        "report_section_id": report_section_id,
                        "dimension_id": analysis_dimension_id,
                        "dimension_name": dimension["name"],
                        "dimension_type": dimension["type"],
                        "parent_dimension_id": dimension.get("parent_dimension_id", ""),
                        "topic": dimension["name"],
                        "query": query_plan.primary_query,
                        "research_goal": research_goal,
                        "search_queries": query_plan.search_queries,
                        "success_criteria": success_criteria,
                        "task_context": self._schema_aware_task_context(
                            query,
                            competitor,
                            dimension,
                            industry_direction_plan,
                        ),
                        "target_urls": [],
                        "search_stage": self._initial_search_stage_from_dimension(dimension),
                        "generated_from_gap": "",
                        "source_hints": dimension.get("source_hints", []),
                        "minimum_coverage": dimension.get("minimum_coverage", []),
                        "expected_claim_types": list(
                            dimension.get("expected_claim_types", []),
                        ),
                        "guiding_questions": dimension.get("guiding_questions", []),
                        "evidence_ids": [],
                        "status": "active",
                        "expansion_reason": "Root branch generated from planned analysis dimension.",
                    }
                )

        return branches

    def _limit_root_branches_per_competitor(
        self,
        root_branches: list[ResearchBranch],
    ) -> tuple[list[ResearchBranch], bool]:
        branch_count_by_competitor: dict[str, int] = {}
        limited_branches: list[ResearchBranch] = []
        limit_exceeded = False

        for branch in root_branches:
            competitor = branch.get("competitor", "")
            branch_count = branch_count_by_competitor.get(competitor, 0)
            if branch_count >= self.max_root_branch_hard_limit:
                limit_exceeded = True
                continue
            branch_count_by_competitor[competitor] = branch_count + 1
            limited_branches.append(branch)

        return limited_branches, limit_exceeded

    def _competitor_profile_dimension(self) -> dict[str, Any]:
        return {
            "id": "competitor_profile",
            "analysis_dimension_id": "competitor_profile",
            "name": "竞品基础信息",
            "type": "profile",
            "description": (
                "Identify the competitor's official website, product or brand "
                "identity, category, and concise public positioning."
            ),
            "source_hints": self._ranked_source_hints(
                ["official_site", "public_registry", "marketplace", "news"],
            ),
            "guiding_questions": [
                "What is the competitor's official website or canonical public page?",
                "What product, brand, or platform identity does the competitor use publicly?",
                "How is the competitor categorized or positioned in public sources?",
            ],
            "search_intent": (
                "Collect profile evidence for the report competitor information card. "
                "Prefer official or registry pages over commentary."
            ),
            "minimum_coverage": [
                "At least one source-backed public evidence item for the competitor profile.",
            ],
            "success_criteria": [
                {
                    "id": "official_profile_source",
                    "description": (
                        "Identify the competitor's official website or canonical "
                        "public source."
                    ),
                    "kind": "guiding_question",
                }
            ],
            "expected_claim_types": ["competitor_profile"],
            "schema_field_ids": [],
            "report_section_id": "",
        }

    def _build_research_briefs(
        self,
        branches: list[ResearchBranch],
    ) -> list[ResearchBrief]:
        briefs = []
        for branch in branches:
            dimension_name = branch.get("dimension_name", branch.get("dimension_id", ""))
            competitor = branch.get("competitor", "")
            briefs.append(
                {
                    "id": branch.get("research_brief_id", f"brief_{branch['id']}"),
                    "branch_id": branch["id"],
                    "competitor": competitor,
                    "analysis_dimension_id": branch.get(
                        "analysis_dimension_id",
                        branch.get("dimension_id", ""),
                    ),
                    "schema_field_ids": list(branch.get("schema_field_ids", [])),
                    "report_section_id": branch.get("report_section_id", ""),
                    "dimension_id": branch.get("dimension_id", ""),
                    "dimension_name": dimension_name,
                    "objective": (
                        branch.get("research_goal")
                        or f"Collect source-backed public evidence about {competitor} "
                        f"for the {dimension_name} dimension."
                    ),
                    "success_criteria": branch.get("success_criteria", []),
                    "guiding_questions": branch.get("guiding_questions", []),
                    "source_hints": branch.get("source_hints", []),
                    "minimum_coverage": branch.get("minimum_coverage", []),
                    "expected_claim_types": list(
                        branch.get("expected_claim_types", []),
                    ),
                    "effort_level": self._effort_level(branch),
                    "source_policy": (
                        "Prefer public sources with stable URLs. Match the confirmed "
                        "competitor and analysis dimension before accepting evidence."
                    ),
                    "stop_condition": (
                        "Stop when expected source types and guiding questions have "
                        "enough accepted evidence, or when branch budget is exhausted."
                    ),
                    "rationale": "Generated from a confirmed competitor x analysis dimension.",
                }
            )
        return briefs

    def _branch_to_research_task(
        self,
        branch: ResearchBranch,
        brief_by_branch: dict[str, ResearchBrief],
    ) -> ResearchTask:
        brief = brief_by_branch.get(branch["id"], {})
        search_stage = branch.get("search_stage") or self._initial_search_stage(branch)
        generated_from_gap = branch.get("generated_from_gap", "")
        reason = (
            f"Follow-up collection for gap: {generated_from_gap}."
            if generated_from_gap
            else f"Initial {search_stage} collection for confirmed {branch.get('dimension_name', branch.get('dimension_id', 'research'))} dimension."
        )
        return {
            "id": f"task_{branch['id']}",
            "brief_id": branch.get("research_brief_id", brief.get("id", "")),
            "parent_task_id": branch.get("parent_task_id"),
            "branch_id": branch["id"],
            "competitor": branch.get("competitor", ""),
            "analysis_dimension_id": branch.get(
                "analysis_dimension_id",
                branch.get("dimension_id", ""),
            ),
            "schema_field_ids": list(branch.get("schema_field_ids", [])),
            "report_section_id": branch.get("report_section_id", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "search_stage": search_stage,
            "objective": brief.get("objective", branch.get("topic", "")),
            "query": branch.get("query", ""),
            "research_goal": branch.get("research_goal", brief.get("objective", "")),
            "target_urls": branch.get("target_urls", []),
            "source_hints": branch.get("source_hints", []),
            "target_source_types": branch.get("target_source_types", []),
            "expected_claim_types": list(branch.get("expected_claim_types", [])),
            "generated_from_gap": generated_from_gap,
            "decision_action": branch.get("decision_action", ""),
            "decision_subtype": branch.get("decision_subtype", ""),
            "search_queries": branch.get("search_queries", [branch.get("query", "")]),
            "success_criteria": branch.get("success_criteria", []),
            "task_context": branch.get("task_context", ""),
            "reason": reason,
            "drift_risk": "low" if not generated_from_gap else "medium",
        }

    def _branch_to_collection_task(
        self,
        branch: ResearchBranch,
        research_task: ResearchTask | None = None,
    ) -> EvidenceCollectionTask:
        research_task = research_task or self._branch_to_research_task(branch, {})
        return {
            "id": branch["id"],
            "research_task_id": research_task.get("id", ""),
            "research_brief_id": research_task.get("brief_id", branch.get("research_brief_id", "")),
            "branch_id": branch["id"],
            "parent_branch_id": branch.get("parent_id"),
            "depth": branch.get("depth", 0),
            "search_stage": research_task.get("search_stage", branch.get("search_stage", "")),
            "generated_from_gap": research_task.get("generated_from_gap", branch.get("generated_from_gap", "")),
            "decision_action": research_task.get("decision_action", branch.get("decision_action", "")),
            "decision_subtype": research_task.get("decision_subtype", branch.get("decision_subtype", "")),
            "source_hints": research_task.get("source_hints", branch.get("source_hints", [])),
            "target_source_types": research_task.get(
                "target_source_types",
                branch.get("target_source_types", []),
            ),
            "expected_claim_types": list(
                research_task.get(
                    "expected_claim_types",
                    branch.get("expected_claim_types", []),
                )
            ),
            "topic": branch.get("topic", ""),
            "expansion_reason": branch.get("expansion_reason", ""),
            "competitor": branch.get("competitor", ""),
            "analysis_dimension_id": branch.get(
                "analysis_dimension_id",
                branch.get("dimension_id", ""),
            ),
            "schema_field_ids": list(branch.get("schema_field_ids", [])),
            "report_section_id": branch.get("report_section_id", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "dimension_type": branch.get("dimension_type", ""),
            "parent_dimension_id": branch.get("parent_dimension_id", ""),
            "query": branch.get("query", ""),
            "research_goal": research_task.get("research_goal", branch.get("research_goal", "")),
            "search_queries": branch.get("search_queries", [branch.get("query", "")]),
            "success_criteria": research_task.get(
                "success_criteria",
                branch.get("success_criteria", []),
            ),
            "task_context": branch.get("task_context", ""),
            "target_urls": branch.get("target_urls", []),
        }

    def _build_child_branches(
        self,
        parent: ResearchBranch,
        follow_up_specs: list[dict[str, Any]],
        parent_task_id: str | None = None,
    ) -> list[ResearchBranch]:
        children = []
        for index, follow_up_spec in enumerate(follow_up_specs, start=1):
            query = follow_up_spec.get("query", "")
            if not query:
                continue
            topic = follow_up_spec.get("objective") or f"{parent['topic']} follow-up {index}"
            dimension_id = (
                follow_up_spec.get("analysis_dimension_id")
                or follow_up_spec.get("dimension_id")
                or parent.get("analysis_dimension_id")
                or parent.get("dimension_id", "")
            )
            dimension_name = follow_up_spec.get("dimension_name", parent.get("dimension_name", ""))
            dimension_type = follow_up_spec.get("dimension_type", parent.get("dimension_type", ""))
            schema_field_ids = list(
                follow_up_spec.get("schema_field_ids")
                or parent.get("schema_field_ids", [])
            )
            report_section_id = follow_up_spec.get(
                "report_section_id",
                parent.get("report_section_id", ""),
            )
            child_id = f"{parent['id']}_d{parent.get('depth', 0) + 1}_{index}"
            success_criteria = follow_up_spec.get(
                "success_criteria",
                parent.get("success_criteria", []),
            )
            guiding_questions = follow_up_spec.get("guiding_questions")
            if guiding_questions is None:
                guiding_questions = [
                    criterion.get("description", "")
                    for criterion in success_criteria
                    if criterion.get("kind") == "guiding_question"
                ] or parent.get("guiding_questions", [])
            children.append(
                {
                    "id": child_id,
                    "research_brief_id": parent.get("research_brief_id", f"brief_{parent['id']}"),
                    "parent_id": parent["id"],
                    "depth": parent.get("depth", 0) + 1,
                    "path": list(parent.get("path", [])) + [topic],
                    "competitor": parent.get("competitor", ""),
                    "analysis_dimension_id": dimension_id,
                    "schema_field_ids": schema_field_ids,
                    "report_section_id": report_section_id,
                    "dimension_id": dimension_id,
                    "dimension_name": dimension_name,
                    "dimension_type": dimension_type,
                    "parent_dimension_id": follow_up_spec.get(
                        "parent_dimension_id",
                        parent.get("parent_dimension_id", ""),
                    ),
                    "topic": topic,
                    "query": query,
                    "research_goal": topic,
                    "search_queries": follow_up_spec.get("search_queries", [query]),
                    "success_criteria": success_criteria,
                    "target_urls": follow_up_spec.get("target_urls", []),
                    "search_stage": follow_up_spec.get("search_stage", "focused"),
                    "generated_from_gap": follow_up_spec.get(
                        "generated_from_gap",
                        "",
                    ),
                    "decision_action": follow_up_spec.get("decision_action", ""),
                    "decision_subtype": follow_up_spec.get("decision_subtype", ""),
                    "source_hints": parent.get("source_hints", []),
                    "target_source_types": list(
                        follow_up_spec.get("target_source_types", []),
                    ),
                    "minimum_coverage": parent.get("minimum_coverage", []),
                    "expected_claim_types": list(
                        follow_up_spec.get(
                            "expected_claim_types",
                            parent.get("expected_claim_types", []),
                        )
                    ),
                    "guiding_questions": guiding_questions,
                    "evidence_ids": [],
                    "parent_task_id": parent_task_id,
                    "status": "active",
                    "expansion_reason": (
                        follow_up_spec.get("reason")
                        or "Coverage reviewer requested follow-up collection."
                    ),
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
        analysis_dimensions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        dimensions = []
        for dimension in analysis_dimensions:
            dimension_id = dimension.get("id", "")
            if not dimension_id:
                continue
            normalized = {
                **dimension,
                "id": dimension_id,
                "analysis_dimension_id": dimension_id,
                "name": dimension.get("name", dimension_id.replace("_", " ").title()),
                "type": "analysis_dimension",
                "description": dimension.get(
                    "description",
                    dimension_id.replace("_", " "),
                ),
                "source_hints": self._ranked_source_hints(
                    list(dimension.get("source_hints", [])),
                ),
                "guiding_questions": list(dimension.get("guiding_questions", [])),
                "success_criteria": list(dimension.get("success_criteria", [])),
                "search_intent": dimension.get("search_intent", ""),
                "minimum_coverage": list(
                    dimension.get("minimum_coverage")
                    or ["At least two source-backed public evidence items."]
                ),
                "expected_claim_types": list(
                    dimension.get("expected_claim_types")
                    or ["industry_specific_signal"],
                ),
                "schema_field_ids": list(dimension.get("schema_field_ids", [])),
            }
            normalized["report_section_id"] = primary_report_section_id(normalized)
            dimensions.append(normalized)
        return dimensions

    def _schema_aware_task_context(
        self,
        query: str,
        competitor: str,
        dimension: dict[str, Any],
        industry_direction_plan: dict[str, Any],
    ) -> str:
        selected_industry = (industry_direction_plan.get("industry") or {}).get(
            "name",
            "unknown industry",
        )
        competitor_line = (
            f"Competitor: {competitor}"
            if competitor
            else "Competitor: infer from the user query"
        )
        lines = [
            query,
            competitor_line,
            f"Selected industry: {selected_industry}",
            f"Research focus: {dimension['name']} ({dimension['type']})",
            f"Focus definition: {dimension['description']}",
            self._success_criteria_line(
                self._success_criteria(query, competitor, dimension),
            ),
            self._guiding_questions_line(dimension),
            dimension.get("search_intent", ""),
        ]
        source_hints = dimension.get("source_hints", [])
        if source_hints:
            lines.append(
                "Preferred evidence sources, in priority order: "
                + ", ".join(source_hints)
                + ".",
            )
        lines.append(
            "Collect public, source-backed evidence only. Prefer official "
            "pages, pricing pages, docs, reviews, news, and marketplace "
            "listings when relevant.",
        )
        return "\n".join(line for line in lines if line)

    def _research_goal(
        self,
        query: str,
        competitor: str,
        dimension: dict[str, Any],
    ) -> str:
        return (
            f"Collect source-backed public evidence about {competitor or 'the requested competitor'} "
            f"for {dimension['name']} while staying aligned with the original request: {query}"
        )

    def _success_criteria(
        self,
        query: str,
        competitor: str,
        dimension: dict[str, Any],
    ) -> list[dict[str, Any]]:
        explicit_criteria = normalize_success_criteria(
            dimension.get("success_criteria", []),
        )
        if explicit_criteria:
            return explicit_criteria

        criteria = []
        for index, question in enumerate(dimension.get("guiding_questions", []), start=1):
            criteria.append(
                {
                    "id": f"guiding_question_{index}",
                    "description": str(question),
                    "kind": "guiding_question",
                }
            )
        return normalize_success_criteria(criteria)

    def _success_criteria_line(self, success_criteria: list[dict[str, Any]]) -> str:
        if not success_criteria:
            return ""
        descriptions = [
            f"{criterion.get('id')}: {criterion.get('description')}"
            for criterion in success_criteria
        ]
        return "Success criteria: " + " | ".join(descriptions)

    def _guiding_questions_line(self, dimension: dict[str, Any]) -> str:
        guiding_questions = dimension.get("guiding_questions", [])
        if not guiding_questions:
            return ""
        return "Guiding questions: " + " | ".join(str(question) for question in guiding_questions)

    def _initial_search_stage_from_dimension(self, dimension: dict[str, Any]) -> str:
        return "focused"

    def _initial_search_stage(self, branch: ResearchBranch) -> str:
        return "focused"

    def _effort_level(self, branch: ResearchBranch) -> str:
        if branch.get("dimension_id") in {
            "pricing_business_model",
            "business_model_pricing",
            "technology_integrations",
            "compliance_risk",
            "competitive_moat",
        }:
            return "high"
        if branch.get("dimension_id") in {"market_growth", "customer_proof"}:
            return "medium"
        return "low"

    def _ranked_source_hints(self, source_hints: list[str]) -> list[str]:
        return sorted(
            dict.fromkeys(source_hints),
            key=lambda source_type: SOURCE_TYPE_PRIORITY.get(source_type, 99),
        )

    def _file_rag_context(
        self,
        query: str,
        file_context: dict[str, Any],
    ) -> str:
        return format_rag_context(file_context, query, limit=4)

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
            item["research_task_id"] = item.get(
                "research_task_id",
                collection_task.get("research_task_id", ""),
            )
            item["analysis_dimension_id"] = collection_task.get(
                "analysis_dimension_id",
                collection_task["dimension_id"],
            )
            item["schema_field_ids"] = list(collection_task.get("schema_field_ids", []))
            item["report_section_id"] = collection_task.get("report_section_id", "")
            item["dimension_id"] = item["analysis_dimension_id"]
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


def _int_env(
    value: int | None,
    env_name: str,
    default: int,
    minimum: int = 0,
) -> int:
    raw_value = value if value is not None else os.getenv(env_name)
    if raw_value in (None, ""):
        return default
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)
