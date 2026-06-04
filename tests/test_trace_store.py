import unittest
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from backend.server.trace_store import (
    TraceStore,
    analysis_claims,
    analysis_runs,
    claim_evidence,
    evidence_items,
    langsmith_trace_id_for_run,
    metadata,
    report_section_claims,
    workflow_step_executions,
    workflow_transitions,
)
from rivalens.workflows.competitive_analysis import _workflow_run_config


class TraceStoreTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.store = TraceStore(engine=self.engine)
        self.store.initialize()

    def _state(self):
        return {
            "task": {
                "run_id": "rid",
                "query": "Compare Alpha and Beta",
                "langsmith_trace_id": langsmith_trace_id_for_run("rid"),
                "langsmith_thread_id": "rid",
                "langsmith_project": "rivalens-test",
            },
            "analysis_dimensions": [
                {
                    "id": "dimension_1",
                    "name": "Pricing",
                    "objective": "Compare pricing",
                    "report_targets": [
                        {"section_id": "section_1", "role": "primary"}
                    ],
                }
            ],
            "research_branches": [
                {
                    "id": "branch_1",
                    "analysis_dimension_id": "dimension_1",
                    "competitor": "Alpha",
                }
            ],
            "research_tasks": [
                {
                    "id": "task_1",
                    "branch_id": "branch_1",
                    "analysis_dimension_id": "dimension_1",
                    "query": "Alpha pricing",
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "branch_id": "branch_1",
                    "research_task_id": "task_1",
                    "analysis_dimension_id": "dimension_1",
                    "report_section_id": "section_1",
                    "title": "Alpha pricing",
                    "url": "https://example.com/pricing",
                    "excerpt": "Alpha costs 10 dollars.",
                    "retrieved_at": "2026-06-04T01:00:00+00:00",
                    "confidence": 0.9,
                }
            ],
            "evidence_reviews": [
                {
                    "id": "review_1",
                    "branch_id": "branch_1",
                    "accepted": True,
                    "accepted_evidence_ids": ["ev_1"],
                }
            ],
            "coverage_assessments": [
                {
                    "id": "coverage_1",
                    "branch_id": "branch_1",
                    "next_action": "ready_for_analysis",
                    "confidence": 0.9,
                }
            ],
            "knowledge_facts": [
                {
                    "id": "fact_1",
                    "analysis_dimension_id": "dimension_1",
                    "report_section_id": "section_1",
                    "statement": "Alpha costs 10 dollars.",
                    "evidence_ids": ["ev_1"],
                    "confidence": 0.9,
                }
            ],
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "analysis_dimension_id": "dimension_1",
                    "report_section_id": "section_1",
                    "claim": "Alpha is cheaper.",
                    "knowledge_fact_ids": ["fact_1"],
                    "evidence_ids": ["ev_1", "missing_evidence"],
                    "confidence": 0.8,
                }
            ],
            "claim_support_reviews": [
                {
                    "id": "claim_review_1",
                    "claim_id": "claim_1",
                    "report_section_id": "section_1",
                    "support_status": "supported",
                    "evidence_ids": ["ev_1"],
                    "confidence": 0.9,
                }
            ],
            "messages": [
                {
                    "id": "message_1",
                    "sender": "planner",
                    "receiver": "collection",
                    "type": "research_plan",
                    "payload": {"dimension_count": 1},
                    "created_at": "2026-06-04T01:00:00+00:00",
                }
            ],
            "agent_events": [
                {
                    "agent": "planner",
                    "action": "plan",
                    "input": {"query": "Compare Alpha and Beta"},
                    "output": {"dimensions": ["Pricing"]},
                    "started_at": "2026-06-04T01:00:00+00:00",
                    "completed_at": "2026-06-04T01:00:01+00:00",
                    "cost": 0.01,
                }
            ],
            "report": "# Comparison",
            "published_artifacts": {"markdown": "outputs/rid.md"},
        }

    def test_metadata_contains_core_traceability_tables(self):
        self.assertTrue(
            {
                "analysis_runs",
                "workflow_step_executions",
                "workflow_transitions",
                "evidence_items",
                "knowledge_facts",
                "analysis_claims",
                "claim_evidence",
                "report_sections",
                "report_section_claims",
                "artifacts",
            }.issubset(metadata.tables)
        )

    def test_persist_state_creates_queryable_provenance_and_is_idempotent(self):
        first = self.store.persist_state(self._state())
        second = self.store.persist_state(self._state())

        self.assertEqual(first.run_id, "rid")
        self.assertEqual(second.claim_evidence_count, 1)
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(analysis_runs)),
                1,
            )
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(evidence_items)),
                1,
            )
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(analysis_claims)),
                1,
            )
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(claim_evidence)),
                1,
            )
            self.assertEqual(
                connection.scalar(
                    select(func.count()).select_from(report_section_claims)
                ),
                1,
            )

        trace = self.store.get_run_trace("rid")
        self.assertIsNotNone(trace)
        self.assertEqual(trace["run"]["status"], "completed")
        self.assertEqual(trace["run"]["langsmith_thread_id"], "rid")
        self.assertEqual(trace["workflow"]["steps"][0]["agent"], "planner")
        self.assertEqual(
            trace["workflow"]["transitions"][0]["to_agent"],
            "collection",
        )
        self.assertEqual(
            trace["provenance"]["claim_evidence"][0],
            {"run_id": "rid", "claim_id": "claim_1", "evidence_id": "ev_1"},
        )
        self.assertEqual(
            len(trace["provenance"]["evidence_items"][0]["content_sha256"]),
            64,
        )

    def test_mark_failed_run_keeps_failure_auditable(self):
        self.store.start_run(
            run_id="failed_run",
            query="Compare failed products",
            langsmith_trace_id=langsmith_trace_id_for_run("failed_run"),
            langsmith_thread_id="failed_run",
        )
        self.store.mark_failed_run(
            run_id="failed_run",
            query="Compare failed products",
            error="collection failed",
            langsmith_trace_id=langsmith_trace_id_for_run("failed_run"),
            langsmith_thread_id="failed_run",
        )

        trace = self.store.get_run_trace("failed_run")

        self.assertEqual(trace["run"]["status"], "failed")
        self.assertEqual(trace["run"]["error"], "collection failed")
        self.assertLessEqual(trace["run"]["started_at"], trace["run"]["completed_at"])

    def test_workflow_config_uses_known_langsmith_root_trace(self):
        trace_id = langsmith_trace_id_for_run("rid")
        task = {
            "run_id": "rid",
            "langsmith_trace_id": trace_id,
            "langsmith_thread_id": "rid",
            "query": "Compare Alpha and Beta",
            "competitors": [],
        }

        config = _workflow_run_config(task, {})

        self.assertEqual(config["run_id"], UUID(trace_id))
        self.assertEqual(config["metadata"]["business_run_id"], "rid")
        self.assertEqual(config["metadata"]["thread_id"], "rid")


if __name__ == "__main__":
    unittest.main()
