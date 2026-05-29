"""PostgreSQL persistence for the traceable Rivalens analysis chain."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


DEFAULT_DATABASE_URL = (
    "postgresql://rivalens:rivalens_password@postgres:5432/rivalens"
)
DEFAULT_REDIS_URL = "redis://redis:6379/0"
AUTO_CREATE_TABLES_ENV = "RIVALENS_AUTO_CREATE_TABLES"

metadata = MetaData()

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("run_id", String(80), primary_key=True),
    Column("query", Text, nullable=False),
    Column("report", Text, nullable=False, default=""),
    Column("published_artifacts", JSON, nullable=False, default=dict),
    Column("persisted_at", String(64), nullable=False),
)

competitors = Table(
    "competitors",
    metadata,
    Column("name", String(240), primary_key=True),
    Column("product", Text, nullable=False, default=""),
    Column("website", Text, nullable=False, default=""),
    Column("category", Text, nullable=False, default=""),
    Column("notes", Text, nullable=False, default=""),
)

run_competitors = Table(
    "run_competitors",
    metadata,
    Column(
        "run_id",
        String(80),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("name", String(240), primary_key=True),
    Column("product", Text, nullable=False, default=""),
    Column("website", Text, nullable=False, default=""),
    Column("category", Text, nullable=False, default=""),
    Column("notes", Text, nullable=False, default=""),
)

industry_direction_plans = Table(
    "industry_direction_plans",
    metadata,
    Column("id", String(160), primary_key=True),
    Column(
        "run_id",
        String(80),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("detected_industry", Text, nullable=False, default=""),
    Column("industry_id", Text, nullable=False, default=""),
    Column("industry_name", Text, nullable=False, default=""),
    Column("industry_confidence", Float, nullable=False, default=0.0),
    Column("industry_signals", JSON, nullable=False, default=list),
    Column("candidate_industries", JSON, nullable=False, default=list),
    Column("detected_competitors", JSON, nullable=False, default=list),
    Column("suggested_competitors", JSON, nullable=False, default=list),
    Column("final_analysis_plan", JSON, nullable=False, default=dict),
    Column("user_confirmed", Boolean, nullable=False, default=False),
    Column("created_at", String(64), nullable=False, default=""),
)

analysis_directions = Table(
    "analysis_directions",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("plan_id", String(160), ForeignKey("industry_direction_plans.id", ondelete="CASCADE"), nullable=False),
    Column("direction_group", String(40), primary_key=True),
    Column("direction_id", String(160), primary_key=True),
    Column("name", Text, nullable=False, default=""),
    Column("reason", Text, nullable=False, default=""),
    Column("description", Text, nullable=False, default=""),
    Column("search_focus", Text, nullable=False, default=""),
    Column("source_hints", JSON, nullable=False, default=list),
    Column("required", Boolean, nullable=False, default=True),
    Column("origin", String(40), nullable=False, default="industry_template"),
)

research_branches = Table(
    "research_branches",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(180), primary_key=True),
    Column("research_brief_id", Text, nullable=False, default=""),
    Column("parent_id", Text, nullable=True),
    Column("parent_task_id", Text, nullable=True),
    Column("parent_dimension_id", Text, nullable=False, default=""),
    Column("depth", Integer, nullable=False, default=0),
    Column("path", JSON, nullable=False, default=list),
    Column("competitor", Text, nullable=False, default=""),
    Column("dimension_id", Text, nullable=False, default=""),
    Column("dimension_name", Text, nullable=False, default=""),
    Column("dimension_type", Text, nullable=False, default=""),
    Column("topic", Text, nullable=False, default=""),
    Column("query", Text, nullable=False, default=""),
    Column("target_urls", JSON, nullable=False, default=list),
    Column("search_stage", String(40), nullable=False, default="focused"),
    Column("generated_from_gap", Text, nullable=False, default=""),
    Column("decision_action", String(40), nullable=False, default=""),
    Column("decision_subtype", String(60), nullable=False, default=""),
    Column("source_hints", JSON, nullable=False, default=list),
    Column("minimum_coverage", JSON, nullable=False, default=list),
    Column("guiding_questions", JSON, nullable=False, default=list),
    Column("evidence_ids", JSON, nullable=False, default=list),
    Column("status", String(40), nullable=False, default="active"),
    Column("expansion_reason", Text, nullable=False, default=""),
)

research_tasks = Table(
    "research_tasks",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(180), primary_key=True),
    Column("brief_id", Text, nullable=False, default=""),
    Column("parent_task_id", Text, nullable=True),
    Column("branch_id", Text, nullable=False, default=""),
    Column("competitor", Text, nullable=False, default=""),
    Column("dimension_id", Text, nullable=False, default=""),
    Column("dimension_name", Text, nullable=False, default=""),
    Column("search_stage", String(40), nullable=False, default="focused"),
    Column("objective", Text, nullable=False, default=""),
    Column("query", Text, nullable=False, default=""),
    Column("target_urls", JSON, nullable=False, default=list),
    Column("source_hints", JSON, nullable=False, default=list),
    Column("generated_from_gap", Text, nullable=False, default=""),
    Column("decision_action", String(40), nullable=False, default=""),
    Column("decision_subtype", String(60), nullable=False, default=""),
    Column("reason", Text, nullable=False, default=""),
    Column("drift_risk", String(40), nullable=False, default="low"),
)

evidence_items = Table(
    "evidence_items",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(160), primary_key=True),
    Column("competitor", Text, nullable=False, default=""),
    Column("branch_id", Text, nullable=False, default=""),
    Column("parent_branch_id", Text, nullable=True),
    Column("collection_task_id", Text, nullable=False, default=""),
    Column("research_task_id", Text, nullable=False, default=""),
    Column("dimension_id", Text, nullable=False, default=""),
    Column("dimension_name", Text, nullable=False, default=""),
    Column("title", Text, nullable=False, default=""),
    Column("url", Text, nullable=False, default=""),
    Column("source_type", String(40), nullable=False, default="other"),
    Column("published_at", String(64), nullable=True),
    Column("retrieved_at", String(64), nullable=False, default=""),
    Column("excerpt", Text, nullable=False, default=""),
    Column("source_priority", Integer, nullable=False, default=8),
    Column("is_primary_source", Boolean, nullable=False, default=False),
    Column("confidence", Float, nullable=False, default=0.0),
)

evidence_reviews = Table(
    "evidence_reviews",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(180), primary_key=True),
    Column("branch_id", Text, nullable=False, default=""),
    Column("collection_task_id", Text, nullable=False, default=""),
    Column("coverage_assessment_id", Text, nullable=False, default=""),
    Column("accepted", Boolean, nullable=False, default=False),
    Column("score", Float, nullable=False, default=0.0),
    Column("findings", JSON, nullable=False, default=list),
    Column("accepted_evidence_ids", JSON, nullable=False, default=list),
    Column("rejected_evidence_ids", JSON, nullable=False, default=list),
    Column("required_action", String(40), nullable=False, default="accept"),
)

coverage_assessments = Table(
    "coverage_assessments",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(180), primary_key=True),
    Column("stage_contract", JSON, nullable=False, default=dict),
    Column("branch_id", Text, nullable=False, default=""),
    Column("brief_id", Text, nullable=False, default=""),
    Column("research_task_ids", JSON, nullable=False, default=list),
    Column("accepted_evidence_ids", JSON, nullable=False, default=list),
    Column("rejected_evidence_ids", JSON, nullable=False, default=list),
    Column("found_source_types", JSON, nullable=False, default=list),
    Column("covered_questions", JSON, nullable=False, default=list),
    Column("missing_questions", JSON, nullable=False, default=list),
    Column("contradictions", JSON, nullable=False, default=list),
    Column("next_action", String(40), nullable=False, default="ready_for_analysis"),
    Column("follow_up_task_specs", JSON, nullable=False, default=list),
    Column("selected_follow_up_specs", JSON, nullable=False, default=list),
    Column("decision_candidates", JSON, nullable=False, default=list),
    Column("arbitration", JSON, nullable=False, default=dict),
    Column("decision", JSON, nullable=False, default=dict),
    Column("confidence", Float, nullable=False, default=0.0),
)

competitor_knowledge = Table(
    "competitor_knowledge",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(180), primary_key=True),
    Column("competitor", Text, nullable=False, default=""),
    Column("active_schema_id", Text, nullable=False, default=""),
    Column("feature_tree", JSON, nullable=False, default=list),
    Column("pricing_model", JSON, nullable=False, default=dict),
    Column("user_personas", JSON, nullable=False, default=list),
    Column("industry_extensions", JSON, nullable=False, default=dict),
    Column("evidence_ids", JSON, nullable=False, default=list),
    Column("confidence", Float, nullable=False, default=0.0),
)

analysis_claims = Table(
    "analysis_claims",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(160), primary_key=True),
    Column("dimension", Text, nullable=False, default=""),
    Column("branch_id", Text, nullable=True),
    Column("evidence_review_id", Text, nullable=True),
    Column("claim", Text, nullable=False, default=""),
    Column("competitors", JSON, nullable=False, default=list),
    Column("evidence_ids", JSON, nullable=False, default=list),
    Column("reasoning", Text, nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.0),
)

agent_events = Table(
    "agent_events",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("event_index", Integer, primary_key=True),
    Column("agent", Text, nullable=False, default=""),
    Column("action", Text, nullable=False, default=""),
    Column("input", JSON, nullable=False, default=dict),
    Column("output", JSON, nullable=False, default=dict),
    Column("started_at", String(64), nullable=False, default=""),
    Column("completed_at", String(64), nullable=False, default=""),
    Column("cost", Float, nullable=False, default=0.0),
)

claim_support_reviews = Table(
    "claim_support_reviews",
    metadata,
    Column("run_id", String(80), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("id", String(160), primary_key=True),
    Column("claim_id", String(160), nullable=False),
    Column("branch_id", Text, nullable=False, default=""),
    Column("dimension", Text, nullable=False, default=""),
    Column("support_status", String(40), nullable=False),
    Column("evidence_ids", JSON, nullable=False, default=list),
    Column("unsupported_phrases", JSON, nullable=False, default=list),
    Column("required_follow_up_tasks", JSON, nullable=False, default=list),
    Column("reviewer_notes", Text, nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.0),
)

Index("ix_industry_direction_plans_run_id", industry_direction_plans.c.run_id)
Index("ix_run_competitors_run_id", run_competitors.c.run_id)
Index("ix_analysis_directions_run_id", analysis_directions.c.run_id)
Index("ix_research_branches_run_dimension", research_branches.c.run_id, research_branches.c.dimension_id)
Index("ix_research_tasks_run_branch", research_tasks.c.run_id, research_tasks.c.branch_id)
Index("ix_evidence_items_run_dimension", evidence_items.c.run_id, evidence_items.c.dimension_id)
Index("ix_evidence_items_run_competitor", evidence_items.c.run_id, evidence_items.c.competitor)
Index("ix_evidence_reviews_run_branch", evidence_reviews.c.run_id, evidence_reviews.c.branch_id)
Index("ix_coverage_assessments_run_branch", coverage_assessments.c.run_id, coverage_assessments.c.branch_id)
Index("ix_competitor_knowledge_run_competitor", competitor_knowledge.c.run_id, competitor_knowledge.c.competitor)
Index("ix_analysis_claims_run_dimension", analysis_claims.c.run_id, analysis_claims.c.dimension)
Index("ix_agent_events_run_agent", agent_events.c.run_id, agent_events.c.agent)
Index("ix_claim_support_reviews_claim_id", claim_support_reviews.c.claim_id)


@dataclass(frozen=True)
class PersistenceConfig:
    database_url: str
    redis_url: str
    auto_create_tables: bool


@dataclass(frozen=True)
class PersistResult:
    run_id: str
    competitor_count: int
    direction_count: int
    research_branch_count: int
    research_task_count: int
    evidence_count: int
    evidence_review_count: int
    coverage_assessment_count: int
    competitor_knowledge_count: int
    claim_count: int
    agent_event_count: int
    claim_support_review_count: int


def get_persistence_config() -> PersistenceConfig:
    return PersistenceConfig(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        redis_url=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
        auto_create_tables=_env_flag(AUTO_CREATE_TABLES_ENV, default=False),
    )


def redact_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url

    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def create_database_engine(database_url: str | None = None) -> Engine:
    return create_engine(_sqlalchemy_database_url(database_url or get_persistence_config().database_url))


def initialize_database(engine: Engine | None = None) -> None:
    target_engine = engine or create_database_engine()
    metadata.create_all(target_engine)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def persist_competitive_analysis_state(
    state: dict[str, Any],
    *,
    engine: Engine | None = None,
    run_id: str | None = None,
) -> PersistResult:
    target_engine = engine or create_database_engine()
    target_run_id = run_id or _run_id_from_state(state)
    plan = state.get("industry_direction_plan", {}) or {}

    with target_engine.begin() as connection:
        for table in (
            claim_support_reviews,
            agent_events,
            analysis_claims,
            competitor_knowledge,
            coverage_assessments,
            evidence_reviews,
            evidence_items,
            research_tasks,
            research_branches,
            analysis_directions,
            industry_direction_plans,
            run_competitors,
            analysis_runs,
        ):
            connection.execute(delete(table).where(table.c.run_id == target_run_id))

        connection.execute(insert(analysis_runs), _run_row(state, target_run_id))
        competitor_rows = _competitor_rows(state, target_run_id)
        if competitor_rows:
            _upsert_competitors(connection, competitor_rows)
            connection.execute(insert(run_competitors), competitor_rows)

        if plan:
            connection.execute(insert(industry_direction_plans), _direction_plan_row(plan, target_run_id))
            direction_rows = _direction_rows(plan, target_run_id)
            if direction_rows:
                connection.execute(insert(analysis_directions), direction_rows)

        branch_rows = [_research_branch_row(branch, target_run_id) for branch in state.get("research_branches", [])]
        if branch_rows:
            connection.execute(insert(research_branches), branch_rows)

        task_rows = [_research_task_row(task, target_run_id) for task in state.get("research_tasks", [])]
        if task_rows:
            connection.execute(insert(research_tasks), task_rows)

        evidence_rows = [_evidence_row(item, target_run_id) for item in state.get("evidence_items", [])]
        if evidence_rows:
            connection.execute(insert(evidence_items), evidence_rows)

        evidence_review_rows = [
            _evidence_review_row(review, target_run_id)
            for review in state.get("evidence_reviews", [])
        ]
        if evidence_review_rows:
            connection.execute(insert(evidence_reviews), evidence_review_rows)

        coverage_rows = [
            _coverage_assessment_row(assessment, target_run_id)
            for assessment in state.get("coverage_assessments", [])
        ]
        if coverage_rows:
            connection.execute(insert(coverage_assessments), coverage_rows)

        knowledge_rows = [
            _competitor_knowledge_row(knowledge, target_run_id)
            for knowledge in state.get("competitor_knowledge", [])
        ]
        if knowledge_rows:
            connection.execute(insert(competitor_knowledge), knowledge_rows)

        claim_rows = [_claim_row(claim, target_run_id) for claim in state.get("analysis_claims", [])]
        if claim_rows:
            connection.execute(insert(analysis_claims), claim_rows)

        event_rows = [
            _agent_event_row(event, target_run_id, index)
            for index, event in enumerate(state.get("agent_events", []), start=1)
        ]
        if event_rows:
            connection.execute(insert(agent_events), event_rows)

        review_rows = [
            _claim_support_review_row(review, target_run_id)
            for review in state.get("claim_support_reviews", [])
        ]
        if review_rows:
            connection.execute(insert(claim_support_reviews), review_rows)

    return PersistResult(
        run_id=target_run_id,
        competitor_count=len(_competitor_rows(state, target_run_id)),
        direction_count=len(_direction_rows(plan, target_run_id)) if plan else 0,
        research_branch_count=len(state.get("research_branches", [])),
        research_task_count=len(state.get("research_tasks", [])),
        evidence_count=len(state.get("evidence_items", [])),
        evidence_review_count=len(state.get("evidence_reviews", [])),
        coverage_assessment_count=len(state.get("coverage_assessments", [])),
        competitor_knowledge_count=len(state.get("competitor_knowledge", [])),
        claim_count=len(state.get("analysis_claims", [])),
        agent_event_count=len(state.get("agent_events", [])),
        claim_support_review_count=len(state.get("claim_support_reviews", [])),
    )


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _run_id_from_state(state: dict[str, Any]) -> str:
    task = state.get("task", {}) or {}
    explicit_run_id = task.get("run_id")
    if explicit_run_id:
        return str(explicit_run_id)

    query = str(task.get("query", ""))
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"run_{timestamp}_{digest}"


def _run_row(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    task = state.get("task", {}) or {}
    return {
        "run_id": run_id,
        "query": str(task.get("query", "")),
        "report": str(state.get("report", "")),
        "published_artifacts": state.get("published_artifacts", {}) or {},
        "persisted_at": datetime.now(timezone.utc).isoformat(),
    }


def _competitor_rows(state: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    rows = []
    for competitor in state.get("competitors", []) or []:
        if isinstance(competitor, str):
            row = {
                "run_id": run_id,
                "name": competitor,
                "product": "",
                "website": "",
                "category": "",
                "notes": "",
            }
        else:
            row = {
                "run_id": run_id,
                "name": str(competitor.get("name", "")),
                "product": str(competitor.get("product", "")),
                "website": str(competitor.get("website", "")),
                "category": str(competitor.get("category", "")),
                "notes": str(competitor.get("notes", "")),
            }
        if row["name"]:
            rows.append(row)
    return _dedupe_rows(rows, "name")


def _upsert_competitors(connection: Any, competitor_rows: list[dict[str, Any]]) -> None:
    rows = [
        {
            "name": row["name"],
            "product": row["product"],
            "website": row["website"],
            "category": row["category"],
            "notes": row["notes"],
        }
        for row in competitor_rows
    ]
    if not rows:
        return

    dialect_name = connection.engine.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        statement = pg_insert(competitors).values(rows)
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[competitors.c.name],
                set_={
                    "product": statement.excluded.product,
                    "website": statement.excluded.website,
                    "category": statement.excluded.category,
                    "notes": statement.excluded.notes,
                },
            )
        )
        return

    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        statement = sqlite_insert(competitors).values(rows)
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[competitors.c.name],
                set_={
                    "product": statement.excluded.product,
                    "website": statement.excluded.website,
                    "category": statement.excluded.category,
                    "notes": statement.excluded.notes,
                },
            )
        )
        return

    for row in rows:
        try:
            connection.execute(insert(competitors), row)
        except IntegrityError:
            continue


def _direction_plan_row(plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    industry = plan.get("industry", {}) or {}
    return {
        "id": str(plan.get("id", f"direction_plan_{run_id}")),
        "run_id": run_id,
        "detected_industry": str(plan.get("detected_industry", "")),
        "industry_id": str(industry.get("industry_id", "")),
        "industry_name": str(industry.get("name", "")),
        "industry_confidence": float(industry.get("confidence", 0.0) or 0.0),
        "industry_signals": list(industry.get("signals", []) or []),
        "candidate_industries": list(plan.get("candidate_industries", []) or []),
        "detected_competitors": list(plan.get("detected_competitors", []) or []),
        "suggested_competitors": list(plan.get("suggested_competitors", []) or []),
        "final_analysis_plan": plan.get("final_analysis_plan", {}) or {},
        "user_confirmed": bool(plan.get("user_confirmed", False)),
        "created_at": str(plan.get("created_at", "")),
    }


def _direction_rows(plan: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    plan_id = str(plan.get("id", f"direction_plan_{run_id}"))
    rows = []
    for direction_group in (
        "default_directions",
        "planner_added_directions",
        "user_added_directions",
        "final_directions",
    ):
        for direction in plan.get(direction_group, []) or []:
            rows.append(_direction_row(direction, run_id, plan_id, direction_group))
    return rows


def _direction_row(
    direction: dict[str, Any],
    run_id: str,
    plan_id: str,
    direction_group: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "plan_id": plan_id,
        "direction_group": direction_group,
        "direction_id": str(direction.get("direction_id", "")),
        "name": str(direction.get("name", "")),
        "reason": str(direction.get("reason", "")),
        "description": str(direction.get("description", "")),
        "search_focus": str(direction.get("search_focus", "")),
        "source_hints": list(direction.get("source_hints", []) or []),
        "required": bool(direction.get("required", True)),
        "origin": str(direction.get("origin", "industry_template")),
    }


def _research_branch_row(branch: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(branch.get("id", "")),
        "research_brief_id": str(branch.get("research_brief_id", "")),
        "parent_id": branch.get("parent_id"),
        "parent_task_id": branch.get("parent_task_id"),
        "parent_dimension_id": str(branch.get("parent_dimension_id", "")),
        "depth": int(branch.get("depth", 0) or 0),
        "path": list(branch.get("path", []) or []),
        "competitor": str(branch.get("competitor", "")),
        "dimension_id": str(branch.get("dimension_id", "")),
        "dimension_name": str(branch.get("dimension_name", "")),
        "dimension_type": str(branch.get("dimension_type", "")),
        "topic": str(branch.get("topic", "")),
        "query": str(branch.get("query", "")),
        "target_urls": list(branch.get("target_urls", []) or []),
        "search_stage": str(branch.get("search_stage", "focused")),
        "generated_from_gap": str(branch.get("generated_from_gap", "")),
        "decision_action": str(branch.get("decision_action", "")),
        "decision_subtype": str(branch.get("decision_subtype", "")),
        "source_hints": list(branch.get("source_hints", []) or []),
        "minimum_coverage": list(branch.get("minimum_coverage", []) or []),
        "guiding_questions": list(branch.get("guiding_questions", []) or []),
        "evidence_ids": list(branch.get("evidence_ids", []) or []),
        "status": str(branch.get("status", "active")),
        "expansion_reason": str(branch.get("expansion_reason", "")),
    }


def _research_task_row(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(task.get("id", "")),
        "brief_id": str(task.get("brief_id", "")),
        "parent_task_id": task.get("parent_task_id"),
        "branch_id": str(task.get("branch_id", "")),
        "competitor": str(task.get("competitor", "")),
        "dimension_id": str(task.get("dimension_id", "")),
        "dimension_name": str(task.get("dimension_name", "")),
        "search_stage": str(task.get("search_stage", "focused")),
        "objective": str(task.get("objective", "")),
        "query": str(task.get("query", "")),
        "target_urls": list(task.get("target_urls", []) or []),
        "source_hints": list(task.get("source_hints", []) or []),
        "generated_from_gap": str(task.get("generated_from_gap", "")),
        "decision_action": str(task.get("decision_action", "")),
        "decision_subtype": str(task.get("decision_subtype", "")),
        "reason": str(task.get("reason", "")),
        "drift_risk": str(task.get("drift_risk", "low")),
    }


def _evidence_row(item: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(item.get("id", "")),
        "competitor": str(item.get("competitor", "")),
        "branch_id": str(item.get("branch_id", "")),
        "parent_branch_id": item.get("parent_branch_id"),
        "collection_task_id": str(item.get("collection_task_id", "")),
        "research_task_id": str(item.get("research_task_id", "")),
        "dimension_id": str(item.get("dimension_id", "")),
        "dimension_name": str(item.get("dimension_name", "")),
        "title": str(item.get("title", "")),
        "url": str(item.get("url", "")),
        "source_type": str(item.get("source_type", "other")),
        "published_at": item.get("published_at"),
        "retrieved_at": str(item.get("retrieved_at", "")),
        "excerpt": str(item.get("excerpt", "")),
        "source_priority": int(item.get("source_priority", 8) or 8),
        "is_primary_source": bool(item.get("is_primary_source", False)),
        "confidence": float(item.get("confidence", 0.0) or 0.0),
    }


def _evidence_review_row(review: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(review.get("id", "")),
        "branch_id": str(review.get("branch_id", "")),
        "collection_task_id": str(review.get("collection_task_id", "")),
        "coverage_assessment_id": str(review.get("coverage_assessment_id", "")),
        "accepted": bool(review.get("accepted", False)),
        "score": float(review.get("score", 0.0) or 0.0),
        "findings": list(review.get("findings", []) or []),
        "accepted_evidence_ids": list(review.get("accepted_evidence_ids", []) or []),
        "rejected_evidence_ids": list(review.get("rejected_evidence_ids", []) or []),
        "required_action": str(review.get("required_action", "accept")),
    }


def _coverage_assessment_row(
    assessment: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(assessment.get("id", "")),
        "stage_contract": assessment.get("stage_contract", {}) or {},
        "branch_id": str(assessment.get("branch_id", "")),
        "brief_id": str(assessment.get("brief_id", "")),
        "research_task_ids": list(assessment.get("research_task_ids", []) or []),
        "accepted_evidence_ids": list(assessment.get("accepted_evidence_ids", []) or []),
        "rejected_evidence_ids": list(assessment.get("rejected_evidence_ids", []) or []),
        "found_source_types": list(assessment.get("found_source_types", []) or []),
        "covered_questions": list(assessment.get("covered_questions", []) or []),
        "missing_questions": list(assessment.get("missing_questions", []) or []),
        "contradictions": list(assessment.get("contradictions", []) or []),
        "next_action": str(assessment.get("next_action", "ready_for_analysis")),
        "follow_up_task_specs": list(assessment.get("follow_up_task_specs", []) or []),
        "selected_follow_up_specs": list(
            assessment.get("selected_follow_up_specs", []) or []
        ),
        "decision_candidates": list(assessment.get("decision_candidates", []) or []),
        "arbitration": assessment.get("arbitration", {}) or {},
        "decision": assessment.get("decision", {}) or {},
        "confidence": float(assessment.get("confidence", 0.0) or 0.0),
    }


def _competitor_knowledge_row(
    knowledge: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(knowledge.get("id", "")),
        "competitor": str(knowledge.get("competitor", "")),
        "active_schema_id": str(knowledge.get("active_schema_id", "")),
        "feature_tree": list(knowledge.get("feature_tree", []) or []),
        "pricing_model": knowledge.get("pricing_model", {}) or {},
        "user_personas": list(knowledge.get("user_personas", []) or []),
        "industry_extensions": knowledge.get("industry_extensions", {}) or {},
        "evidence_ids": list(knowledge.get("evidence_ids", []) or []),
        "confidence": float(knowledge.get("confidence", 0.0) or 0.0),
    }


def _claim_row(claim: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(claim.get("id", "")),
        "dimension": str(claim.get("dimension", "")),
        "branch_id": claim.get("branch_id"),
        "evidence_review_id": claim.get("evidence_review_id"),
        "claim": str(claim.get("claim", "")),
        "competitors": list(claim.get("competitors", []) or []),
        "evidence_ids": list(claim.get("evidence_ids", []) or []),
        "reasoning": str(claim.get("reasoning", "")),
        "confidence": float(claim.get("confidence", 0.0) or 0.0),
    }


def _agent_event_row(
    event: dict[str, Any],
    run_id: str,
    event_index: int,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "event_index": event_index,
        "agent": str(event.get("agent", "")),
        "action": str(event.get("action", "")),
        "input": _compact_event_payload(event.get("input", {}) or {}),
        "output": _compact_event_payload(event.get("output", {}) or {}),
        "started_at": str(event.get("started_at", "")),
        "completed_at": str(event.get("completed_at", "")),
        "cost": float(event.get("cost", 0.0) or 0.0),
    }


def _claim_support_review_row(review: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "id": str(review.get("id", "")),
        "claim_id": str(review.get("claim_id", "")),
        "branch_id": str(review.get("branch_id", "")),
        "dimension": str(review.get("dimension", "")),
        "support_status": str(review.get("support_status", "")),
        "evidence_ids": list(review.get("evidence_ids", []) or []),
        "unsupported_phrases": list(review.get("unsupported_phrases", []) or []),
        "required_follow_up_tasks": list(review.get("required_follow_up_tasks", []) or []),
        "reviewer_notes": str(review.get("reviewer_notes", "")),
        "confidence": float(review.get("confidence", 0.0) or 0.0),
    }


def _compact_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value if not isinstance(value, str) else value[:500]
        elif isinstance(value, list):
            compact[key] = {
                "type": "list",
                "count": len(value),
                "sample": value[:5],
            }
        elif isinstance(value, dict):
            compact[key] = {
                "type": "dict",
                "keys": list(value.keys())[:20],
            }
        else:
            compact[key] = str(value)[:200]
    return compact


def _dedupe_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_key = str(row.get(key, "")).lower()
        if row_key:
            deduped[row_key] = row
    return list(deduped.values())
