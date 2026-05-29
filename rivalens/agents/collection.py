"""Evidence collection agent for competitor analysis."""

import asyncio
from typing import Any

from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.evidence_review import EvidenceQualityReviewer
from rivalens.agents.landscape_review import LandscapeReviewer
from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.file_context import format_rag_context
from rivalens.research import ResearchEngineEvidenceCollector, ResearchMode
from rivalens.schema import (
    CompetitorAnalysisState,
    EvidenceCollectionResult,
    EvidenceCollectionTask,
    ResearchBrief,
    ResearchBranch,
    ResearchTask,
)


class CollectionAgent:
    def __init__(
        self,
        evidence_collector: ResearchEngineEvidenceCollector | None = None,
        evidence_reviewer: EvidenceQualityReviewer | None = None,
        coverage_reviewer: CoverageReviewer | None = None,
        landscape_reviewer: LandscapeReviewer | None = None,
        max_branch_depth: int = 1,
        max_expansion_branches: int = 24,
        max_root_branch_hard_limit: int = 80,
    ):
        self.evidence_collector = evidence_collector or ResearchEngineEvidenceCollector()
        self.evidence_reviewer = evidence_reviewer or EvidenceQualityReviewer()
        self.coverage_reviewer = coverage_reviewer or CoverageReviewer()
        self.landscape_reviewer = landscape_reviewer or LandscapeReviewer()
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
        research_briefs = list(state.get("research_briefs", []))
        research_tasks = list(state.get("research_tasks", []))
        landscape_assessments = list(state.get("landscape_assessments", []))
        coverage_assessments = list(state.get("coverage_assessments", []))
        evidence_reviews = list(state.get("evidence_reviews", []))
        contexts: list[dict[str, Any]] = []
        failed_tasks: list[dict[str, Any]] = []
        verification_queue = list(state.get("verification_task_queue", []))
        verification_pass = bool(verification_queue)
        if verification_pass:
            root_branches = self._build_verification_branches(
                verification_queue,
                state,
            )
            root_branch_limit_exceeded = False
        else:
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
        new_briefs = self._build_research_briefs(root_branches)
        research_briefs.extend(new_briefs)
        brief_by_branch = {brief["branch_id"]: brief for brief in new_briefs}
        processed_branch_count = 0
        expansion_branch_count = 0
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
            for branch, research_task, collection_task, result in zip(
                active_frontier,
                planned_tasks,
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

                if research_task.get("search_stage") == "landscape":
                    landscape_assessment = self.landscape_reviewer.review(
                        branch=branch,
                        research_task=research_task,
                        sources=result.get("evidence_items", []),
                    )
                    follow_up_specs = self._landscape_follow_up_specs(
                        landscape_assessment,
                    )
                    should_expand = self._landscape_should_expand(landscape_assessment)
                    if should_expand and not follow_up_specs:
                        self._mark_landscape_stop(
                            landscape_assessment,
                            subtype="no_viable_followup",
                            rationale="Landscape decision requested expansion but produced no executable follow-up task.",
                        )
                    elif should_expand and branch.get("depth", 0) >= self.max_branch_depth:
                        self._mark_landscape_stop(
                            landscape_assessment,
                            subtype="budget_stop",
                            rationale="Landscape follow-up was blocked by the configured branch depth budget.",
                        )
                    elif should_expand and expansion_branch_count >= self.max_expansion_branches:
                        self._mark_landscape_stop(
                            landscape_assessment,
                            subtype="budget_stop",
                            rationale="Landscape follow-up was blocked by the configured expansion branch budget.",
                        )
                    selected_follow_up_specs = self._selected_landscape_follow_up_specs(
                        landscape_assessment,
                        follow_up_specs,
                        expansion_branch_count,
                    )
                    landscape_assessment["selected_follow_up_specs"] = selected_follow_up_specs

                    landscape_assessments.append(landscape_assessment)
                    contexts.append(result)
                    research_artifacts.append(
                        {
                            "id": f"artifact_collection_{len(research_artifacts) + 1}",
                            "agent": "collection",
                            "mode": "landscape",
                            "query": result["query"],
                            "competitor": collection_task["competitor"],
                            "branch_id": branch["id"],
                            "research_brief_id": collection_task.get("research_brief_id", ""),
                            "research_task_id": collection_task.get("research_task_id", ""),
                            "search_stage": "landscape",
                            "generated_from_gap": collection_task.get("generated_from_gap", ""),
                            "dimension_id": collection_task["dimension_id"],
                            "dimension_name": collection_task["dimension_name"],
                            "collection_task_id": collection_task["id"],
                            "context": self._landscape_artifact_context(
                                landscape_assessment,
                            ),
                            "evidence_ids": [],
                            "costs": result["costs"],
                        }
                    )
                    if (
                        self._landscape_should_expand(landscape_assessment)
                        and selected_follow_up_specs
                        and branch.get("depth", 0) < self.max_branch_depth
                    ):
                        branch["status"] = "expanded"
                        children = self._build_child_branches(
                            branch,
                            selected_follow_up_specs,
                            parent_task_id=research_task["id"],
                        )
                        expansion_branch_count += len(children)
                        next_frontier.extend(children)
                        research_branches.extend(children)
                    else:
                        branch["status"] = "stopped"
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
                coverage_assessment = self.coverage_reviewer.review(
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
                        "dimension_id": collection_task["dimension_id"],
                        "dimension_name": collection_task["dimension_name"],
                        "collection_task_id": collection_task["id"],
                        "context": result["context"],
                        "evidence_ids": [source.get("id", "") for source in sources],
                        "costs": result["costs"],
                    }
                )

                follow_up_specs = coverage_assessment.get("follow_up_task_specs", [])
                if (
                    coverage_assessment.get("next_action")
                    in {"collect_more", "refine_query"}
                    and follow_up_specs
                    and branch.get("depth", 0) < self.max_branch_depth
                ):
                    branch["status"] = "expanded"
                    remaining_branch_slots = self.max_expansion_branches - expansion_branch_count
                    if remaining_branch_slots <= 0:
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
            "research_briefs": research_briefs,
            "research_tasks": research_tasks,
            "landscape_assessments": landscape_assessments,
            "coverage_assessments": coverage_assessments,
            "research_artifacts": research_artifacts,
            "verification_task_queue": [],
            "verification_rounds": int(state.get("verification_rounds", 0) or 0)
            + (1 if verification_pass else 0),
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
                        "collection_phase": "verification" if verification_pass else "initial_or_gap_collection",
                        "verification_task_count": len(verification_queue),
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
                        "research_brief_count": len(research_briefs),
                        "research_task_count": len(research_tasks),
                        "landscape_assessment_count": len(landscape_assessments),
                        "expanded_branch_count": expansion_branch_count,
                        "evidence_review_count": len(evidence_reviews),
                        "coverage_assessment_count": len(coverage_assessments),
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
            mode=self._research_mode_for_task(collection_task),
            source_urls=collection_task.get("target_urls", []),
            verbose=verbose,
        )

    def _research_mode_for_task(
        self,
        collection_task: EvidenceCollectionTask,
    ) -> ResearchMode:
        if collection_task.get("search_stage") == "landscape":
            return ResearchMode.SOURCE_DISCOVERY
        return ResearchMode.STANDARD_EVIDENCE

    def _landscape_follow_up_specs(
        self,
        landscape_assessment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        decision = landscape_assessment.get("decision", {})
        if (
            decision.get("action") == "scope_refinement"
            and decision.get("subtype") == "dimension_decomposition"
        ):
            return list(landscape_assessment.get("split_task_specs", []))
        return list(landscape_assessment.get("focused_task_specs", []))

    def _landscape_should_expand(self, landscape_assessment: dict[str, Any]) -> bool:
        decision = landscape_assessment.get("decision", {})
        action = decision.get("action")
        return bool(action and action != "stop")

    def _selected_landscape_follow_up_specs(
        self,
        landscape_assessment: dict[str, Any],
        follow_up_specs: list[dict[str, Any]],
        expansion_branch_count: int,
    ) -> list[dict[str, Any]]:
        if not self._landscape_should_expand(landscape_assessment):
            return []
        remaining_branch_slots = self.max_expansion_branches - expansion_branch_count
        if remaining_branch_slots <= 0:
            return []
        return list(follow_up_specs)[:remaining_branch_slots]

    def _landscape_artifact_context(
        self,
        landscape_assessment: dict[str, Any],
    ) -> dict[str, Any]:
        decision = landscape_assessment.get("decision", {})
        candidate_sources = landscape_assessment.get("candidate_sources", [])
        selected_follow_up_specs = landscape_assessment.get("selected_follow_up_specs", [])
        return {
            "observation": {
                "landscape_assessment_id": landscape_assessment.get("id", ""),
                "candidate_source_count": len(candidate_sources),
                "candidate_source_urls": [
                    source.get("url", "")
                    for source in candidate_sources[:5]
                    if source.get("url")
                ],
                "discovered_source_types": landscape_assessment.get(
                    "discovered_source_types",
                    [],
                ),
                "missing_source_types": landscape_assessment.get(
                    "missing_source_types",
                    [],
                ),
                "source_universe_confidence": landscape_assessment.get(
                    "source_universe_confidence",
                    0.0,
                ),
                "competitor_disambiguation_status": landscape_assessment.get(
                    "competitor_disambiguation",
                    {},
                ).get("status", "unknown"),
                "dimension_split_suggestions": landscape_assessment.get(
                    "dimension_split_suggestions",
                    [],
                ),
            },
            "routing": {
                "decision": decision,
                "focused_task_count": len(
                    landscape_assessment.get("focused_task_specs", []),
                ),
                "split_task_count": len(
                    landscape_assessment.get("split_task_specs", []),
                ),
                "selected_follow_up_task_count": len(selected_follow_up_specs),
                "selected_follow_up_specs": selected_follow_up_specs,
                "blocked_by_budget": decision.get("subtype") == "budget_stop",
            },
            "replay_ref": {
                "landscape_assessment_id": landscape_assessment.get("id", ""),
                "full_state_collection": "landscape_assessments",
                "full_state_path": (
                    "landscape_assessments"
                    f"[id={landscape_assessment.get('id', '')}]"
                ),
            },
        }

    def _mark_landscape_stop(
        self,
        landscape_assessment: dict[str, Any],
        subtype: str,
        rationale: str,
    ) -> None:
        landscape_assessment["decision"] = {
            "action": "stop",
            "subtype": subtype,
            "rationale": rationale,
        }

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
                        "research_brief_id": f"brief_{branch_id}",
                        "parent_id": None,
                        "depth": 0,
                        "path": [dimension["id"]],
                        "competitor": competitor,
                        "dimension_id": dimension["id"],
                        "dimension_name": dimension["name"],
                        "dimension_type": dimension["type"],
                        "parent_dimension_id": dimension.get("parent_dimension_id", ""),
                        "topic": dimension["name"],
                        "query": self._schema_aware_query(
                            query,
                            competitor,
                            dimension,
                            active_schema,
                        ),
                        "target_urls": [],
                        "search_stage": self._initial_search_stage_from_dimension(dimension),
                        "generated_from_gap": "",
                        "expected_source_types": dimension.get("expected_source_types", []),
                        "minimum_coverage": dimension.get("minimum_coverage", []),
                        "guiding_questions": dimension.get("guiding_questions", []),
                        "evidence_ids": [],
                        "status": "active",
                        "expansion_reason": (
                            "Root branch generated from confirmed analysis dimension."
                            if dimension["type"] == "analysis_dimension"
                            else "Root branch generated from active schema dimension."
                        ),
                    }
                )

        return branches

    def _build_verification_branches(
        self,
        verification_tasks: list[dict[str, Any]],
        state: CompetitorAnalysisState,
    ) -> list[ResearchBranch]:
        dimensions_by_id = {
            dimension.get("id", ""): dimension
            for dimension in state.get("analysis_dimensions", [])
            if dimension.get("id")
        }
        branches: list[ResearchBranch] = []
        for index, task_spec in enumerate(verification_tasks, start=1):
            query = task_spec.get("query", "")
            if not query:
                continue
            dimension_id = task_spec.get("dimension_id") or "source_evidence"
            dimension = dimensions_by_id.get(dimension_id, {})
            branch_id = f"verify_{self._slug(task_spec.get('generated_from_gap', str(index)))}_{index}"
            branches.append(
                {
                    "id": branch_id,
                    "research_brief_id": f"brief_{branch_id}",
                    "parent_id": task_spec.get("parent_branch_id"),
                    "depth": 0,
                    "path": [dimension_id, task_spec.get("generated_from_gap", "verification")],
                    "competitor": task_spec.get("competitor", ""),
                    "dimension_id": dimension_id,
                    "dimension_name": dimension.get("name", dimension_id.replace("_", " ")),
                    "dimension_type": "claim_verification",
                    "parent_dimension_id": task_spec.get("parent_dimension_id", ""),
                    "topic": task_spec.get("objective", "Claim verification"),
                    "query": query,
                    "target_urls": task_spec.get("target_urls", []),
                    "search_stage": "verification",
                    "generated_from_gap": task_spec.get("generated_from_gap", "claim_support"),
                    "decision_action": task_spec.get("decision_action", "claim_verification"),
                    "decision_subtype": task_spec.get("decision_subtype", "evidence_check"),
                    "expected_source_types": task_spec.get(
                        "target_source_types",
                        dimension.get("expected_source_types", []),
                    ),
                    "minimum_coverage": ["Direct public evidence for or against the target claim."],
                    "guiding_questions": [task_spec.get("objective", "Verify the target claim.")],
                    "evidence_ids": [],
                    "status": "active",
                    "expansion_reason": task_spec.get(
                        "reason",
                        "Claim support review requested verification collection.",
                    ),
                }
            )
        return branches

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
                    "dimension_id": branch.get("dimension_id", ""),
                    "dimension_name": dimension_name,
                    "objective": (
                        f"Collect source-backed public evidence about {competitor} "
                        f"for the {dimension_name} dimension."
                    ),
                    "guiding_questions": branch.get("guiding_questions", []),
                    "expected_source_types": branch.get("expected_source_types", []),
                    "minimum_coverage": branch.get("minimum_coverage", []),
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
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "search_stage": search_stage,
            "objective": brief.get("objective", branch.get("topic", "")),
            "query": branch.get("query", ""),
            "target_urls": branch.get("target_urls", []),
            "expected_source_types": branch.get("expected_source_types", []),
            "generated_from_gap": generated_from_gap,
            "decision_action": branch.get("decision_action", ""),
            "decision_subtype": branch.get("decision_subtype", ""),
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
            "expected_source_types": research_task.get("expected_source_types", branch.get("expected_source_types", [])),
            "topic": branch.get("topic", ""),
            "expansion_reason": branch.get("expansion_reason", ""),
            "competitor": branch.get("competitor", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "dimension_type": branch.get("dimension_type", ""),
            "parent_dimension_id": branch.get("parent_dimension_id", ""),
            "query": branch.get("query", ""),
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
            dimension_id = follow_up_spec.get("dimension_id", parent.get("dimension_id", ""))
            dimension_name = follow_up_spec.get("dimension_name", parent.get("dimension_name", ""))
            dimension_type = follow_up_spec.get("dimension_type", parent.get("dimension_type", ""))
            child_id = f"{parent['id']}_d{parent.get('depth', 0) + 1}_{index}"
            children.append(
                {
                    "id": child_id,
                    "research_brief_id": parent.get("research_brief_id", f"brief_{parent['id']}"),
                    "parent_id": parent["id"],
                    "depth": parent.get("depth", 0) + 1,
                    "path": list(parent.get("path", [])) + [topic],
                    "competitor": parent.get("competitor", ""),
                    "dimension_id": dimension_id,
                    "dimension_name": dimension_name,
                    "dimension_type": dimension_type,
                    "parent_dimension_id": follow_up_spec.get(
                        "parent_dimension_id",
                        parent.get("parent_dimension_id", ""),
                    ),
                    "topic": topic,
                    "query": query,
                    "target_urls": follow_up_spec.get("target_urls", []),
                    "search_stage": follow_up_spec.get("search_stage", "focused"),
                    "generated_from_gap": follow_up_spec.get(
                        "generated_from_gap",
                        "",
                    ),
                    "decision_action": follow_up_spec.get("decision_action", ""),
                    "decision_subtype": follow_up_spec.get("decision_subtype", ""),
                    "expected_source_types": follow_up_spec.get(
                        "target_source_types",
                        parent.get("expected_source_types", []),
                    ),
                    "minimum_coverage": parent.get("minimum_coverage", []),
                    "guiding_questions": parent.get("guiding_questions", []),
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
                    "expected_source_types": dimension.get("expected_source_types", []),
                    "minimum_coverage": dimension.get("minimum_coverage", []),
                    "risk_level": dimension.get("risk_level", "medium"),
                    "expected_claim_types": dimension.get("expected_claim_types", []),
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
                    "expected_source_types": self._fallback_expected_source_types(field),
                    "minimum_coverage": ["At least two source-backed public evidence items."],
                    "risk_level": "medium",
                    "expected_claim_types": ["evidence_backed_signal"],
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
                    "expected_source_types": ["official_site", "news", "other"],
                    "minimum_coverage": ["At least two source-backed public evidence items."],
                    "risk_level": "medium",
                    "expected_claim_types": ["industry_specific_signal"],
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
                self._expected_sources_line(dimension),
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

    def _expected_sources_line(self, dimension: dict[str, Any]) -> str:
        expected_source_types = dimension.get("expected_source_types", [])
        if not expected_source_types:
            return ""
        return "Expected source types: " + ", ".join(str(source) for source in expected_source_types)

    def _initial_search_stage_from_dimension(self, dimension: dict[str, Any]) -> str:
        if dimension.get("id") in {"market_growth", "competitive_moat"}:
            return "landscape"
        expected_source_types = set(dimension.get("expected_source_types", []))
        if {"pricing_page", "docs", "review", "marketplace"} & expected_source_types:
            return "focused"
        if dimension.get("risk_level") == "high":
            return "landscape"
        return "focused"

    def _initial_search_stage(self, branch: ResearchBranch) -> str:
        expected_source_types = set(branch.get("expected_source_types", []))
        if {"pricing_page", "docs", "review", "marketplace"} & expected_source_types:
            return "focused"
        if branch.get("dimension_id") in {"market_growth", "competitive_moat"}:
            return "landscape"
        return "focused"

    def _effort_level(self, branch: ResearchBranch) -> str:
        if branch.get("dimension_id") in {
            "pricing_business_model",
            "technology_integrations",
            "compliance_risk",
            "competitive_moat",
        }:
            return "high"
        if branch.get("dimension_id") in {"market_growth", "customer_proof"}:
            return "medium"
        return "low"

    def _fallback_expected_source_types(self, field: str) -> list[str]:
        if field == "pricing_model":
            return ["pricing_page", "official_site", "docs"]
        if field == "user_personas":
            return ["review", "official_site", "marketplace"]
        return ["official_site", "docs", "other"]

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
            item["research_task_id"] = item.get(
                "research_task_id",
                collection_task.get("research_task_id", ""),
            )
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
