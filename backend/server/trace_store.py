from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine

from .user_store import DEFAULT_DATABASE_URL, users


TRACE_PERSISTENCE_ENABLED_ENV = "RIVALENS_TRACE_PERSISTENCE_ENABLED"
JSON_DATA = JSON().with_variant(JSONB, "postgresql")

metadata = MetaData()
users.to_metadata(metadata)

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("run_id", String(160), primary_key=True),
    Column(
        "user_id",
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("query", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("report", Text, nullable=False, default=""),
    Column("langsmith_trace_id", String(64), nullable=True),
    Column("langsmith_thread_id", String(160), nullable=True),
    Column("langsmith_project", String(160), nullable=True),
    Column("langsmith_trace_url", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("total_cost", Float, nullable=False, default=0.0),
    Column("error", Text, nullable=True),
    Column("task_payload", JSON_DATA, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('running', 'completed', 'failed', 'cancelled')",
        name="ck_analysis_runs_status",
    ),
)

workflow_step_executions = Table(
    "workflow_step_executions",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("sequence", Integer, primary_key=True),
    Column("agent", String(120), nullable=False),
    Column("action", String(240), nullable=False),
    Column("status", String(32), nullable=False),
    Column("input_payload", JSON_DATA, nullable=False, default=dict),
    Column("output_payload", JSON_DATA, nullable=False, default=dict),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("cost", Float, nullable=False, default=0.0),
    Column("langsmith_run_id", String(64), nullable=True),
)

workflow_transitions = Table(
    "workflow_transitions",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("sequence", Integer, primary_key=True),
    Column("from_agent", String(120), nullable=False),
    Column("to_agent", String(120), nullable=False),
    Column("edge_type", String(80), nullable=False),
    Column("source_message_id", String(160), nullable=True),
    Column("decision_payload", JSON_DATA, nullable=False, default=dict),
)

agent_messages = Table(
    "agent_messages",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(160), primary_key=True),
    Column("sequence", Integer, nullable=False),
    Column("sender", String(120), nullable=False),
    Column("receiver", String(120), nullable=False),
    Column("message_type", String(80), nullable=False),
    Column("payload", JSON_DATA, nullable=False, default=dict),
    Column("evidence_ids", JSON_DATA, nullable=False, default=list),
    Column("artifact_ids", JSON_DATA, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True), nullable=True),
)

analysis_dimensions = Table(
    "analysis_dimensions",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("name", Text, nullable=False),
    Column("objective", Text, nullable=False, default=""),
    Column("priority", String(40), nullable=False, default="P1"),
    Column("required", Boolean, nullable=False, default=True),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

research_branches = Table(
    "research_branches",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("parent_id", String(180), nullable=True),
    Column("parent_task_id", String(180), nullable=True),
    Column("analysis_dimension_id", String(180), nullable=True),
    Column("competitor", Text, nullable=False, default=""),
    Column("depth", Integer, nullable=False, default=0),
    Column("status", String(40), nullable=False, default="active"),
    Column("decision_action", String(80), nullable=False, default=""),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

research_tasks = Table(
    "research_tasks",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("branch_id", String(180), nullable=True),
    Column("parent_task_id", String(180), nullable=True),
    Column("analysis_dimension_id", String(180), nullable=True),
    Column("competitor", Text, nullable=False, default=""),
    Column("search_stage", String(40), nullable=False, default="focused"),
    Column("objective", Text, nullable=False, default=""),
    Column("query", Text, nullable=False, default=""),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

evidence_items = Table(
    "evidence_items",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("branch_id", String(180), nullable=True),
    Column("research_task_id", String(180), nullable=True),
    Column("collection_task_id", String(180), nullable=True),
    Column("analysis_dimension_id", String(180), nullable=True),
    Column("report_section_id", String(180), nullable=True),
    Column("competitor", Text, nullable=False, default=""),
    Column("title", Text, nullable=False, default=""),
    Column("url", Text, nullable=False),
    Column("source_type", String(80), nullable=False, default="other"),
    Column("published_at", String(80), nullable=True),
    Column("retrieved_at", DateTime(timezone=True), nullable=True),
    Column("excerpt", Text, nullable=False, default=""),
    Column("is_primary_source", Boolean, nullable=False, default=False),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("content_sha256", String(64), nullable=False),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

evidence_reviews = Table(
    "evidence_reviews",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("branch_id", String(180), nullable=True),
    Column("accepted", Boolean, nullable=False, default=False),
    Column("score", Float, nullable=False, default=0.0),
    Column("required_action", String(80), nullable=False, default=""),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

coverage_assessments = Table(
    "coverage_assessments",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("branch_id", String(180), nullable=True),
    Column("next_action", String(80), nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

competitor_knowledge = Table(
    "competitor_knowledge",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("competitor", Text, nullable=False),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

knowledge_facts = Table(
    "knowledge_facts",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("competitor", Text, nullable=False, default=""),
    Column("analysis_dimension_id", String(180), nullable=True),
    Column("schema_field_id", String(180), nullable=True),
    Column("report_section_id", String(180), nullable=True),
    Column("statement", Text, nullable=False),
    Column("value", JSON_DATA, nullable=False, default=dict),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

analysis_claims = Table(
    "analysis_claims",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("analysis_dimension_id", String(180), nullable=True),
    Column("report_section_id", String(180), nullable=True),
    Column("branch_id", String(180), nullable=True),
    Column("evidence_review_id", String(180), nullable=True),
    Column("claim_source", String(120), nullable=False, default=""),
    Column("claim", Text, nullable=False),
    Column("reasoning", Text, nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

claim_support_reviews = Table(
    "claim_support_reviews",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("claim_id", String(180), nullable=False),
    Column("support_status", String(40), nullable=False),
    Column("confidence", Float, nullable=False, default=0.0),
    Column("reviewer_notes", Text, nullable=False, default=""),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

report_sections = Table(
    "report_sections",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(180), primary_key=True),
    Column("title", Text, nullable=False, default=""),
    Column("content", Text, nullable=False, default=""),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("id", String(240), primary_key=True),
    Column("artifact_type", String(80), nullable=False),
    Column("uri", Text, nullable=False, default=""),
    Column("agent", String(120), nullable=True),
    Column("branch_id", String(180), nullable=True),
    Column("cost", Float, nullable=False, default=0.0),
    Column("payload", JSON_DATA, nullable=False, default=dict),
)

knowledge_fact_evidence = Table(
    "knowledge_fact_evidence",
    metadata,
    Column("run_id", String(160), primary_key=True),
    Column("knowledge_fact_id", String(180), primary_key=True),
    Column("evidence_id", String(180), primary_key=True),
    ForeignKeyConstraint(
        ["run_id", "knowledge_fact_id"],
        ["knowledge_facts.run_id", "knowledge_facts.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["run_id", "evidence_id"],
        ["evidence_items.run_id", "evidence_items.id"],
        ondelete="CASCADE",
    ),
)

claim_evidence = Table(
    "claim_evidence",
    metadata,
    Column("run_id", String(160), primary_key=True),
    Column("claim_id", String(180), primary_key=True),
    Column("evidence_id", String(180), primary_key=True),
    ForeignKeyConstraint(
        ["run_id", "claim_id"],
        ["analysis_claims.run_id", "analysis_claims.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["run_id", "evidence_id"],
        ["evidence_items.run_id", "evidence_items.id"],
        ondelete="CASCADE",
    ),
)

claim_knowledge_facts = Table(
    "claim_knowledge_facts",
    metadata,
    Column("run_id", String(160), primary_key=True),
    Column("claim_id", String(180), primary_key=True),
    Column("knowledge_fact_id", String(180), primary_key=True),
    ForeignKeyConstraint(
        ["run_id", "claim_id"],
        ["analysis_claims.run_id", "analysis_claims.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["run_id", "knowledge_fact_id"],
        ["knowledge_facts.run_id", "knowledge_facts.id"],
        ondelete="CASCADE",
    ),
)

report_section_claims = Table(
    "report_section_claims",
    metadata,
    Column("run_id", String(160), primary_key=True),
    Column("report_section_id", String(180), primary_key=True),
    Column("claim_id", String(180), primary_key=True),
    ForeignKeyConstraint(
        ["run_id", "report_section_id"],
        ["report_sections.run_id", "report_sections.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["run_id", "claim_id"],
        ["analysis_claims.run_id", "analysis_claims.id"],
        ondelete="CASCADE",
    ),
)

Index("ix_analysis_runs_user_created", analysis_runs.c.user_id, analysis_runs.c.created_at)
Index("ix_analysis_runs_status", analysis_runs.c.status)
Index("ix_workflow_steps_run_agent", workflow_step_executions.c.run_id, workflow_step_executions.c.agent)
Index("ix_workflow_transitions_run_agents", workflow_transitions.c.run_id, workflow_transitions.c.from_agent, workflow_transitions.c.to_agent)
Index("ix_agent_messages_run_sequence", agent_messages.c.run_id, agent_messages.c.sequence)
Index("ix_research_branches_run_dimension", research_branches.c.run_id, research_branches.c.analysis_dimension_id)
Index("ix_research_tasks_run_branch", research_tasks.c.run_id, research_tasks.c.branch_id)
Index("ix_evidence_items_run_dimension", evidence_items.c.run_id, evidence_items.c.analysis_dimension_id)
Index("ix_evidence_items_run_competitor", evidence_items.c.run_id, evidence_items.c.competitor)
Index("ix_knowledge_facts_run_dimension", knowledge_facts.c.run_id, knowledge_facts.c.analysis_dimension_id)
Index("ix_analysis_claims_run_dimension", analysis_claims.c.run_id, analysis_claims.c.analysis_dimension_id)
Index("ix_analysis_claims_run_report_section", analysis_claims.c.run_id, analysis_claims.c.report_section_id)
Index("ix_claim_evidence_evidence", claim_evidence.c.run_id, claim_evidence.c.evidence_id)


TRACE_CHILD_TABLES = (
    report_section_claims,
    claim_knowledge_facts,
    claim_evidence,
    knowledge_fact_evidence,
    artifacts,
    report_sections,
    claim_support_reviews,
    analysis_claims,
    knowledge_facts,
    competitor_knowledge,
    coverage_assessments,
    evidence_reviews,
    evidence_items,
    research_tasks,
    research_branches,
    analysis_dimensions,
    agent_messages,
    workflow_transitions,
    workflow_step_executions,
)


@dataclass(frozen=True)
class TracePersistResult:
    run_id: str
    step_count: int
    transition_count: int
    evidence_count: int
    knowledge_fact_count: int
    claim_count: int
    claim_evidence_count: int
    artifact_count: int


class TraceStore:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._database_url = database_url
        self._engine = engine
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        return _env_flag(TRACE_PERSISTENCE_ENABLED_ENV, default=True)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            database_url = self._database_url or os.getenv(
                "DATABASE_URL",
                DEFAULT_DATABASE_URL,
            )
            self._engine = create_engine(
                _sqlalchemy_database_url(database_url),
                pool_pre_ping=True,
            )
        return self._engine

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def persist_state(
        self,
        state: dict[str, Any],
        *,
        run_id: str | None = None,
        user_id: str | UUID | None = None,
    ) -> TracePersistResult:
        target_run_id = run_id or _run_id_from_state(state)
        rows = _build_trace_rows(state, target_run_id, user_id=user_id)

        with self.engine.begin() as connection:
            for table in TRACE_CHILD_TABLES:
                connection.execute(delete(table).where(table.c.run_id == target_run_id))
            connection.execute(delete(analysis_runs).where(analysis_runs.c.run_id == target_run_id))

            connection.execute(insert(analysis_runs), rows["analysis_runs"])
            for table in TRACE_CHILD_TABLES[::-1]:
                table_rows = rows.get(table.name, [])
                if table_rows:
                    connection.execute(insert(table), table_rows)

        return TracePersistResult(
            run_id=target_run_id,
            step_count=len(rows[workflow_step_executions.name]),
            transition_count=len(rows[workflow_transitions.name]),
            evidence_count=len(rows[evidence_items.name]),
            knowledge_fact_count=len(rows[knowledge_facts.name]),
            claim_count=len(rows[analysis_claims.name]),
            claim_evidence_count=len(rows[claim_evidence.name]),
            artifact_count=len(rows[artifacts.name]),
        )

    def start_run(
        self,
        *,
        run_id: str,
        query: str,
        user_id: str | UUID | None = None,
        langsmith_trace_id: str | None = None,
        langsmith_thread_id: str | None = None,
    ) -> None:
        now = _utcnow()
        values = {
            "run_id": run_id,
            "user_id": _uuid_or_none(user_id),
            "query": query,
            "status": "running",
            "report": "",
            "langsmith_trace_id": langsmith_trace_id,
            "langsmith_thread_id": langsmith_thread_id,
            "langsmith_project": os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT"),
            "langsmith_trace_url": None,
            "started_at": now,
            "completed_at": None,
            "total_cost": 0.0,
            "error": None,
            "task_payload": {"run_id": run_id, "query": query},
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            for table in TRACE_CHILD_TABLES:
                connection.execute(delete(table).where(table.c.run_id == run_id))
            exists = connection.execute(
                select(analysis_runs.c.run_id).where(analysis_runs.c.run_id == run_id)
            ).first()
            if exists:
                connection.execute(
                    update(analysis_runs)
                    .where(analysis_runs.c.run_id == run_id)
                    .values(**{key: value for key, value in values.items() if key != "created_at"})
                )
            else:
                connection.execute(insert(analysis_runs), values)

    def mark_failed_run(
        self,
        *,
        run_id: str,
        query: str,
        error: str,
        user_id: str | UUID | None = None,
        langsmith_trace_id: str | None = None,
        langsmith_thread_id: str | None = None,
    ) -> None:
        now = _utcnow()
        values = {
            "user_id": _uuid_or_none(user_id),
            "query": query,
            "status": "failed",
            "report": "",
            "langsmith_trace_id": langsmith_trace_id,
            "langsmith_thread_id": langsmith_thread_id,
            "langsmith_project": os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT"),
            "langsmith_trace_url": None,
            "started_at": now,
            "completed_at": now,
            "total_cost": 0.0,
            "error": error,
            "task_payload": {"run_id": run_id, "query": query},
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(analysis_runs).where(analysis_runs.c.run_id == run_id)
            ).mappings().first()
            if existing:
                values["started_at"] = existing["started_at"]
                values["created_at"] = existing["created_at"]
                values["task_payload"] = existing["task_payload"]
                values["user_id"] = existing["user_id"] or values["user_id"]
            if existing:
                connection.execute(
                    update(analysis_runs)
                    .where(analysis_runs.c.run_id == run_id)
                    .values(**{key: value for key, value in values.items() if key != "created_at"})
                )
            else:
                connection.execute(
                    insert(analysis_runs),
                    {"run_id": run_id, "created_at": now, **values},
                )

    def get_run_trace(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            run = connection.execute(
                select(analysis_runs).where(analysis_runs.c.run_id == run_id)
            ).mappings().first()
            if run is None:
                return None

            return _json_safe(
                {
                    "run": dict(run),
                    "workflow": {
                        "steps": _select_run_rows(
                            connection,
                            workflow_step_executions,
                            run_id,
                            workflow_step_executions.c.sequence,
                        ),
                        "transitions": _select_run_rows(
                            connection,
                            workflow_transitions,
                            run_id,
                            workflow_transitions.c.sequence,
                        ),
                        "messages": _select_run_rows(
                            connection,
                            agent_messages,
                            run_id,
                            agent_messages.c.sequence,
                        ),
                    },
                    "provenance": {
                        "analysis_dimensions": _select_run_rows(connection, analysis_dimensions, run_id),
                        "research_branches": _select_run_rows(connection, research_branches, run_id),
                        "research_tasks": _select_run_rows(connection, research_tasks, run_id),
                        "evidence_items": _select_run_rows(connection, evidence_items, run_id),
                        "evidence_reviews": _select_run_rows(connection, evidence_reviews, run_id),
                        "coverage_assessments": _select_run_rows(connection, coverage_assessments, run_id),
                        "competitor_knowledge": _select_run_rows(connection, competitor_knowledge, run_id),
                        "knowledge_facts": _select_run_rows(connection, knowledge_facts, run_id),
                        "knowledge_fact_evidence": _select_run_rows(connection, knowledge_fact_evidence, run_id),
                        "analysis_claims": _select_run_rows(connection, analysis_claims, run_id),
                        "claim_evidence": _select_run_rows(connection, claim_evidence, run_id),
                        "claim_knowledge_facts": _select_run_rows(connection, claim_knowledge_facts, run_id),
                        "claim_support_reviews": _select_run_rows(connection, claim_support_reviews, run_id),
                        "report_sections": _select_run_rows(connection, report_sections, run_id),
                        "report_section_claims": _select_run_rows(connection, report_section_claims, run_id),
                        "artifacts": _select_run_rows(connection, artifacts, run_id),
                    },
                }
            )


def langsmith_trace_id_for_run(run_id: str) -> str:
    try:
        return str(UUID(str(run_id)))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"rivalens:{run_id}"))


def _build_trace_rows(
    state: dict[str, Any],
    run_id: str,
    *,
    user_id: str | UUID | None,
) -> dict[str, Any]:
    task = _dict_value(state.get("task"))
    events = _dict_items(state.get("agent_events"))
    messages = _dict_items(state.get("messages"))
    dimensions = _dict_items(state.get("analysis_dimensions"))
    branches = _dict_items(state.get("research_branches"))
    tasks = _dict_items(state.get("research_tasks"))
    evidence = _dict_items(state.get("evidence_items"))
    reviews = _dict_items(state.get("evidence_reviews"))
    assessments = _dict_items(state.get("coverage_assessments"))
    knowledge = _dict_items(state.get("competitor_knowledge"))
    facts = _dict_items(state.get("knowledge_facts"))
    claims = _dict_items(state.get("analysis_claims"))
    claim_reviews = _dict_items(state.get("claim_support_reviews"))

    evidence_ids = {_id(item) for item in evidence if _id(item)}
    fact_ids = {_id(item) for item in facts if _id(item)}
    claim_ids = {_id(item) for item in claims if _id(item)}

    step_rows = _workflow_step_rows(events, run_id)
    transition_rows = _workflow_transition_rows(messages, events, run_id)
    message_rows = _agent_message_rows(messages, run_id)
    dimension_rows = _analysis_dimension_rows(dimensions, run_id)
    branch_rows = _research_branch_rows(branches, run_id)
    task_rows = _research_task_rows(tasks, run_id)
    evidence_rows = _evidence_rows(evidence, run_id)
    review_rows = _evidence_review_rows(reviews, run_id)
    assessment_rows = _coverage_assessment_rows(assessments, run_id)
    knowledge_rows = _competitor_knowledge_rows(knowledge, run_id)
    fact_rows = _knowledge_fact_rows(facts, run_id)
    claim_rows = _analysis_claim_rows(claims, run_id)
    claim_review_rows = _claim_support_review_rows(claim_reviews, run_id)
    section_rows = _report_section_rows(dimensions, facts, claims, claim_reviews, run_id)
    section_ids = {row["id"] for row in section_rows}
    artifact_rows = _artifact_rows(state, run_id)

    return {
        analysis_runs.name: _analysis_run_row(state, run_id, user_id=user_id),
        workflow_step_executions.name: step_rows,
        workflow_transitions.name: transition_rows,
        agent_messages.name: message_rows,
        analysis_dimensions.name: dimension_rows,
        research_branches.name: branch_rows,
        research_tasks.name: task_rows,
        evidence_items.name: evidence_rows,
        evidence_reviews.name: review_rows,
        coverage_assessments.name: assessment_rows,
        competitor_knowledge.name: knowledge_rows,
        knowledge_facts.name: fact_rows,
        analysis_claims.name: claim_rows,
        claim_support_reviews.name: claim_review_rows,
        report_sections.name: section_rows,
        artifacts.name: artifact_rows,
        knowledge_fact_evidence.name: _knowledge_fact_evidence_rows(
            facts,
            run_id,
            evidence_ids=evidence_ids,
        ),
        claim_evidence.name: _claim_evidence_rows(
            claims,
            run_id,
            evidence_ids=evidence_ids,
        ),
        claim_knowledge_facts.name: _claim_knowledge_fact_rows(
            claims,
            run_id,
            fact_ids=fact_ids,
        ),
        report_section_claims.name: _report_section_claim_rows(
            claims,
            run_id,
            claim_ids=claim_ids,
            section_ids=section_ids,
        ),
    }


def _analysis_run_row(
    state: dict[str, Any],
    run_id: str,
    *,
    user_id: str | UUID | None,
) -> dict[str, Any]:
    task = _dict_value(state.get("task"))
    events = _dict_items(state.get("agent_events"))
    now = _utcnow()
    started_at = min(
        (_parse_datetime(event.get("started_at")) for event in events),
        default=None,
        key=lambda value: value or now,
    )
    completed_at = max(
        (_parse_datetime(event.get("completed_at")) for event in events),
        default=None,
        key=lambda value: value or datetime.min.replace(tzinfo=timezone.utc),
    )
    event_cost = sum(_float_value(event.get("cost")) for event in events)
    artifact_cost = sum(
        _float_value(artifact.get("costs"))
        for artifact in _dict_items(state.get("research_artifacts"))
    )
    task_user_id = task.get("user_id") or user_id
    trace_id = str(task.get("langsmith_trace_id") or langsmith_trace_id_for_run(run_id))

    return {
        "run_id": run_id,
        "user_id": _uuid_or_none(task_user_id),
        "query": str(task.get("query", "")),
        "status": "completed",
        "report": str(state.get("report", "")),
        "langsmith_trace_id": trace_id,
        "langsmith_thread_id": str(task.get("langsmith_thread_id") or run_id),
        "langsmith_project": str(
            task.get("langsmith_project")
            or os.getenv("LANGSMITH_PROJECT")
            or os.getenv("LANGCHAIN_PROJECT")
            or ""
        )
        or None,
        "langsmith_trace_url": str(task.get("langsmith_trace_url") or "") or None,
        "started_at": started_at or now,
        "completed_at": completed_at or now,
        "total_cost": event_cost if event_cost else artifact_cost,
        "error": None,
        "task_payload": _json_safe(task),
        "created_at": now,
        "updated_at": now,
    }


def _workflow_step_rows(events: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    rows = []
    for sequence, event in enumerate(events, start=1):
        completed_at = _parse_datetime(event.get("completed_at"))
        rows.append(
            {
                "run_id": run_id,
                "sequence": sequence,
                "agent": str(event.get("agent", "")),
                "action": str(event.get("action", "")),
                "status": "completed" if completed_at else "unknown",
                "input_payload": _compact_payload(_dict_value(event.get("input"))),
                "output_payload": _compact_payload(_dict_value(event.get("output"))),
                "started_at": _parse_datetime(event.get("started_at")),
                "completed_at": completed_at,
                "cost": _float_value(event.get("cost")),
                "langsmith_run_id": str(event.get("langsmith_run_id") or "") or None,
            }
        )
    return rows


def _workflow_transition_rows(
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    run_id: str,
) -> list[dict[str, Any]]:
    rows = []
    for sequence, message in enumerate(messages, start=1):
        rows.append(
            {
                "run_id": run_id,
                "sequence": sequence,
                "from_agent": str(message.get("sender", "")),
                "to_agent": str(message.get("receiver", "")),
                "edge_type": str(message.get("type", "message")),
                "source_message_id": str(message.get("id") or "") or None,
                "decision_payload": _compact_payload(_dict_value(message.get("payload"))),
            }
        )
    if rows:
        return rows

    for sequence, (source, target) in enumerate(zip(events, events[1:]), start=1):
        rows.append(
            {
                "run_id": run_id,
                "sequence": sequence,
                "from_agent": str(source.get("agent", "")),
                "to_agent": str(target.get("agent", "")),
                "edge_type": "derived_event_order",
                "source_message_id": None,
                "decision_payload": {},
            }
        )
    return rows


def _agent_message_rows(messages: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    rows = []
    for sequence, message in enumerate(messages, start=1):
        message_id = _id(message) or f"message_{sequence}"
        rows.append(
            {
                "run_id": run_id,
                "id": message_id,
                "sequence": sequence,
                "sender": str(message.get("sender", "")),
                "receiver": str(message.get("receiver", "")),
                "message_type": str(message.get("type", "")),
                "payload": _json_safe(_dict_value(message.get("payload"))),
                "evidence_ids": _string_list(message.get("evidence_ids")),
                "artifact_ids": _string_list(message.get("artifact_ids")),
                "created_at": _parse_datetime(message.get("created_at")),
            }
        )
    return _dedupe_rows(rows, "id")


def _analysis_dimension_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "name": str(item.get("name", "")),
                "objective": str(item.get("objective", "")),
                "priority": str(item.get("priority", "P1")),
                "required": bool(item.get("required", True)),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _research_branch_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "parent_id": _optional_string(item.get("parent_id")),
                "parent_task_id": _optional_string(item.get("parent_task_id")),
                "analysis_dimension_id": _optional_string(
                    item.get("analysis_dimension_id") or item.get("dimension_id")
                ),
                "competitor": str(item.get("competitor", "")),
                "depth": _int_value(item.get("depth")),
                "status": str(item.get("status", "active")),
                "decision_action": str(item.get("decision_action", "")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _research_task_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "branch_id": _optional_string(item.get("branch_id")),
                "parent_task_id": _optional_string(item.get("parent_task_id")),
                "analysis_dimension_id": _optional_string(
                    item.get("analysis_dimension_id") or item.get("dimension_id")
                ),
                "competitor": str(item.get("competitor", "")),
                "search_stage": str(item.get("search_stage", "focused")),
                "objective": str(item.get("objective", "")),
                "query": str(item.get("query", "")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _evidence_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        item_id = _id(item)
        if not item_id:
            continue
        payload = _json_safe(item)
        rows.append(
            {
                "run_id": run_id,
                "id": item_id,
                "branch_id": _optional_string(item.get("branch_id")),
                "research_task_id": _optional_string(item.get("research_task_id")),
                "collection_task_id": _optional_string(item.get("collection_task_id")),
                "analysis_dimension_id": _optional_string(
                    item.get("analysis_dimension_id") or item.get("dimension_id")
                ),
                "report_section_id": _optional_string(item.get("report_section_id")),
                "competitor": str(item.get("competitor", "")),
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "source_type": str(item.get("source_type", "other")),
                "published_at": _optional_string(item.get("published_at")),
                "retrieved_at": _parse_datetime(item.get("retrieved_at")),
                "excerpt": str(item.get("excerpt", "")),
                "is_primary_source": bool(item.get("is_primary_source", False)),
                "confidence": _float_value(item.get("confidence")),
                "content_sha256": _evidence_content_sha256(item),
                "payload": payload,
            }
        )
    return _dedupe_rows(rows, "id")


def _evidence_review_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "branch_id": _optional_string(item.get("branch_id")),
                "accepted": bool(item.get("accepted", False)),
                "score": _float_value(item.get("score")),
                "required_action": str(item.get("required_action", "")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _coverage_assessment_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "branch_id": _optional_string(item.get("branch_id")),
                "next_action": str(item.get("next_action", "")),
                "confidence": _float_value(item.get("confidence")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _competitor_knowledge_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "competitor": str(item.get("competitor", "")),
                "confidence": _float_value(item.get("confidence")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _knowledge_fact_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "competitor": str(item.get("competitor", "")),
                "analysis_dimension_id": _optional_string(item.get("analysis_dimension_id")),
                "schema_field_id": _optional_string(item.get("schema_field_id")),
                "report_section_id": _optional_string(item.get("report_section_id")),
                "statement": str(item.get("statement", "")),
                "value": _json_safe(_dict_value(item.get("value"))),
                "confidence": _float_value(item.get("confidence")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _analysis_claim_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "analysis_dimension_id": _optional_string(item.get("analysis_dimension_id")),
                "report_section_id": _optional_string(item.get("report_section_id")),
                "branch_id": _optional_string(item.get("branch_id")),
                "evidence_review_id": _optional_string(item.get("evidence_review_id")),
                "claim_source": str(item.get("claim_source", "")),
                "claim": str(item.get("claim", "")),
                "reasoning": str(item.get("reasoning", "")),
                "confidence": _float_value(item.get("confidence")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item)
        ],
        "id",
    )


def _claim_support_review_rows(items: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            {
                "run_id": run_id,
                "id": _id(item),
                "claim_id": str(item.get("claim_id", "")),
                "support_status": str(item.get("support_status", "unverifiable")),
                "confidence": _float_value(item.get("confidence")),
                "reviewer_notes": str(item.get("reviewer_notes", "")),
                "payload": _json_safe(item),
            }
            for item in items
            if _id(item) and item.get("claim_id")
        ],
        "id",
    )


def _report_section_rows(
    dimensions: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    claim_reviews: list[dict[str, Any]],
    run_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        for target in _dict_items(dimension.get("report_targets")):
            section_id = str(target.get("section_id", ""))
            if section_id:
                rows.append(
                    {
                        "run_id": run_id,
                        "id": section_id,
                        "title": str(dimension.get("name", section_id)),
                        "content": "",
                        "payload": {
                            "source": "analysis_dimension",
                            "analysis_dimension_id": _id(dimension),
                            "target": _json_safe(target),
                        },
                    }
                )
    for source_name, items in (
        ("knowledge_fact", facts),
        ("analysis_claim", claims),
        ("claim_support_review", claim_reviews),
    ):
        for item in items:
            section_id = str(item.get("report_section_id", ""))
            if section_id:
                rows.append(
                    {
                        "run_id": run_id,
                        "id": section_id,
                        "title": section_id,
                        "content": "",
                        "payload": {"source": source_name},
                    }
                )
    return _dedupe_rows(rows, "id")


def _artifact_rows(state: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    rows = []
    for artifact_type, uri in _dict_value(state.get("published_artifacts")).items():
        rows.append(
            {
                "run_id": run_id,
                "id": f"published:{artifact_type}",
                "artifact_type": str(artifact_type),
                "uri": str(uri),
                "agent": "publisher",
                "branch_id": None,
                "cost": 0.0,
                "payload": {"source": "published_artifacts"},
            }
        )
    for sequence, artifact in enumerate(_dict_items(state.get("research_artifacts")), start=1):
        artifact_id = _id(artifact) or str(sequence)
        rows.append(
            {
                "run_id": run_id,
                "id": f"research:{artifact_id}",
                "artifact_type": "research",
                "uri": "",
                "agent": _optional_string(artifact.get("agent")),
                "branch_id": _optional_string(artifact.get("branch_id")),
                "cost": _float_value(artifact.get("costs")),
                "payload": {
                    "mode": str(artifact.get("mode", "")),
                    "query": str(artifact.get("query", "")),
                    "competitor": str(artifact.get("competitor", "")),
                    "evidence_ids": _string_list(artifact.get("evidence_ids")),
                    "report_preview": str(artifact.get("report", ""))[:2000],
                },
            }
        )
    return _dedupe_rows(rows, "id")


def _knowledge_fact_evidence_rows(
    facts: list[dict[str, Any]],
    run_id: str,
    *,
    evidence_ids: set[str],
) -> list[dict[str, Any]]:
    return _dedupe_link_rows(
        {
            (run_id, _id(fact), evidence_id)
            for fact in facts
            for evidence_id in _string_list(fact.get("evidence_ids"))
            if _id(fact) and evidence_id in evidence_ids
        },
        ("run_id", "knowledge_fact_id", "evidence_id"),
    )


def _claim_evidence_rows(
    claims: list[dict[str, Any]],
    run_id: str,
    *,
    evidence_ids: set[str],
) -> list[dict[str, Any]]:
    return _dedupe_link_rows(
        {
            (run_id, _id(claim), evidence_id)
            for claim in claims
            for evidence_id in _string_list(claim.get("evidence_ids"))
            if _id(claim) and evidence_id in evidence_ids
        },
        ("run_id", "claim_id", "evidence_id"),
    )


def _claim_knowledge_fact_rows(
    claims: list[dict[str, Any]],
    run_id: str,
    *,
    fact_ids: set[str],
) -> list[dict[str, Any]]:
    return _dedupe_link_rows(
        {
            (run_id, _id(claim), fact_id)
            for claim in claims
            for fact_id in _string_list(claim.get("knowledge_fact_ids"))
            if _id(claim) and fact_id in fact_ids
        },
        ("run_id", "claim_id", "knowledge_fact_id"),
    )


def _report_section_claim_rows(
    claims: list[dict[str, Any]],
    run_id: str,
    *,
    claim_ids: set[str],
    section_ids: set[str],
) -> list[dict[str, Any]]:
    return _dedupe_link_rows(
        {
            (run_id, str(claim.get("report_section_id", "")), _id(claim))
            for claim in claims
            if _id(claim) in claim_ids
            and str(claim.get("report_section_id", "")) in section_ids
        },
        ("run_id", "report_section_id", "claim_id"),
    )


def _select_run_rows(
    connection: Connection,
    table: Table,
    run_id: str,
    order_by: Any | None = None,
) -> list[dict[str, Any]]:
    statement = select(table).where(table.c.run_id == run_id)
    if order_by is not None:
        statement = statement.order_by(order_by)
    return [dict(row) for row in connection.execute(statement).mappings()]


def _run_id_from_state(state: dict[str, Any]) -> str:
    task = _dict_value(state.get("task"))
    return str(task.get("run_id") or uuid4())


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _uuid_or_none(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return None


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _id(item: dict[str, Any]) -> str:
    return str(item.get("id", ""))


def _optional_string(value: Any) -> str | None:
    normalized = str(value) if value not in (None, "") else ""
    return normalized or None


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _sha256(value: Any) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence_content_sha256(item: dict[str, Any]) -> str:
    return _sha256(
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "published_at": item.get("published_at"),
            "retrieved_at": item.get("retrieved_at"),
            "excerpt": item.get("excerpt"),
        }
    )


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            compact[key] = value[:1000]
        elif isinstance(value, (int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = {
                "type": "list",
                "count": len(value),
                "sample": _bounded_json(value[:5]),
            }
        elif isinstance(value, dict):
            compact[key] = {
                "type": "dict",
                "keys": [str(item) for item in list(value)[:30]],
            }
        else:
            compact[key] = str(value)[:500]
    return compact


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= 2:
        return str(type(value).__name__)
    if isinstance(value, list):
        return [_bounded_json(item, depth=depth + 1) for item in value[:5]]
    if isinstance(value, dict):
        return {
            str(key): _bounded_json(item, depth=depth + 1)
            for key, item in list(value.items())[:20]
        }
    return str(value)[:500]


def _dedupe_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key, ""))
        if value:
            deduped[value] = row
    return list(deduped.values())


def _dedupe_link_rows(
    values: set[tuple[str, str, str]],
    columns: tuple[str, str, str],
) -> list[dict[str, Any]]:
    return [
        dict(zip(columns, value))
        for value in sorted(values)
        if all(value)
    ]
