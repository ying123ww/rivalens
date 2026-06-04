import unittest
from unittest.mock import patch

from backend.server import app as app_module
from backend.server import websocket_manager
from rivalens.research.utils.enum import Tone


class RivalensStructuredResponseTest(unittest.IsolatedAsyncioTestCase):
    def _state(self):
        return {
            "task": {"run_id": "rid", "query": "Compare Alpha and Beta"},
            "report": "Structured report",
            "published_artifacts": {"markdown": "outputs/rivalens/competitor_analysis.md"},
            "evidence_items": [
                {"id": "ev_1", "url": "https://example.com", "excerpt": "Evidence"}
            ],
            "coverage_assessments": [{"id": "cov_1", "confidence": 0.8}],
            "evidence_reviews": [{"id": "er_1", "accepted": True}],
            "claim_support_reviews": [{"id": "csr_1", "support_status": "supported"}],
            "analysis_claims": [{"id": "claim_1", "evidence_ids": ["ev_1"]}],
            "competitor_knowledge": [{"id": "knowledge_1", "evidence_ids": ["ev_1"]}],
            "research_branches": [{"id": "branch_1"}],
            "research_tasks": [{"id": "task_1"}],
            "agent_events": [
                {"agent": "planner", "action": "plan"},
                {"agent": "writer", "action": "write"},
            ],
        }

    def test_build_rivalens_structured_response_preserves_state_and_indexes(self):
        response = websocket_manager.build_rivalens_structured_response(self._state())

        self.assertEqual(response["run_id"], "rid")
        self.assertEqual(response["report"], "Structured report")
        self.assertEqual(response["report_artifacts"], {"markdown": "outputs/rivalens/competitor_analysis.md"})
        self.assertEqual(response["evidence_index"][0]["id"], "ev_1")
        self.assertEqual(response["assessments"]["coverage"][0]["id"], "cov_1")
        self.assertEqual(response["assessments"]["claim_support_reviews"][0]["id"], "csr_1")
        self.assertEqual(response["trace_summary"]["event_count"], 2)
        self.assertEqual(response["trace_summary"]["evidence_count"], 1)
        self.assertEqual(response["state"], self._state())

    async def test_run_agent_rivalens_returns_structured_response(self):
        async def fake_run_rivalens_task(**kwargs):
            self.assertEqual(kwargs["user_id"], "user-id")
            state = self._state()
            state["task"]["run_id"] = kwargs["run_id"]
            return state

        with patch.object(websocket_manager, "run_rivalens_task", fake_run_rivalens_task):
            response = await websocket_manager.run_agent(
                task="Compare Alpha and Beta",
                report_type="rivalens",
                report_source="web",
                source_urls=[],
                document_urls=[],
                tone=Tone.Objective,
                websocket=None,
                stream_output=None,
                run_id="rid",
                user_id="user-id",
            )

        self.assertIsInstance(response, dict)
        self.assertEqual(response["run_id"], "rid")
        self.assertEqual(response["report"], "Structured report")
        self.assertEqual(response["evidence_index"][0]["id"], "ev_1")

    async def test_write_report_rivalens_includes_structured_fields_and_generated_artifacts(self):
        request = app_module.ResearchRequest(
            task="Compare Alpha and Beta",
            report_type="rivalens",
            report_source="web",
            tone="Objective",
            repo_name="repo",
            branch_name="main",
        )

        async def fake_run_agent(**kwargs):
            response = websocket_manager.build_rivalens_structured_response(self._state())
            response["run_id"] = kwargs["run_id"]
            return response

        async def fake_generate_report_files(report, filename, **kwargs):
            return {
                "markdown": f"outputs/{filename}.md",
                "html": f"outputs/{filename}.html",
                "pdf": f"outputs/{filename}.pdf",
                "docx": f"outputs/{filename}.docx",
            }

        with (
            patch.object(app_module, "run_agent", fake_run_agent),
            patch.object(app_module, "generate_report_files", fake_generate_report_files),
        ):
            response = await app_module.write_report(request, "rid")

        self.assertEqual(response["run_id"], "rid")
        self.assertEqual(response["report"], "Structured report")
        self.assertEqual(response["evidence_index"][0]["id"], "ev_1")
        self.assertEqual(response["assessments"]["coverage"][0]["id"], "cov_1")
        self.assertEqual(response["trace_summary"]["claim_count"], 1)
        self.assertEqual(response["report_artifacts"]["markdown"], "outputs/rid.md")
        self.assertEqual(response["state"]["task"]["run_id"], "rid")


if __name__ == "__main__":
    unittest.main()
