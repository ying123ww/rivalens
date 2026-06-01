import unittest
from unittest.mock import patch

from backend.server import app as app_module


class FakeReportStore:
    def __init__(self):
        self.records = {}

    async def get_report(self, report_id):
        return self.records.get(report_id)

    async def upsert_report(self, report_id, report):
        self.records[report_id] = report


class ReportGenerationPersistenceTest(unittest.IsolatedAsyncioTestCase):
    def _request(self):
        return app_module.ResearchRequest(
            task="Compare Alpha and Beta",
            report_type="rivalens",
            report_source="web",
            tone="Objective",
            repo_name="repo",
            branch_name="main",
        )

    async def test_completed_background_report_is_written_to_report_store(self):
        store = FakeReportStore()
        request = self._request()
        response = {
            "research_id": "rid",
            "report": "Finished report",
            "markdown_path": "outputs/rid.md",
            "html_path": "outputs/rid.html",
            "pdf_path": "outputs/rid.pdf",
            "docx_path": "outputs/rid.docx",
            "artifacts": {"markdown": "outputs/rid.md"},
            "run_id": "rid",
            "report_artifacts": {"markdown": "outputs/rid.md"},
            "trace_summary": {"evidence_count": 1},
            "assessments": {"claim_support_reviews": []},
            "evidence_index": [{"id": "ev_1"}],
        }

        async def fake_write_report(research_request, research_id):
            return response

        with (
            patch.object(app_module, "report_store", store),
            patch.object(app_module, "write_report", fake_write_report),
        ):
            result = await app_module.write_report_and_store(request, "rid")

        self.assertEqual(result, response)
        self.assertIn("rid", store.records)

        record = store.records["rid"]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["question"], "Compare Alpha and Beta")
        self.assertEqual(record["answer"], "Finished report")
        self.assertEqual(record["artifacts"], {"markdown": "outputs/rid.md"})
        self.assertEqual(record["run_id"], "rid")
        self.assertEqual(record["report_artifacts"], {"markdown": "outputs/rid.md"})
        self.assertEqual(record["trace_summary"], {"evidence_count": 1})
        self.assertEqual(record["assessments"], {"claim_support_reviews": []})
        self.assertEqual(record["evidence_index"], [{"id": "ev_1"}])
        self.assertEqual(
            record["orderedData"],
            [
                {"type": "question", "content": "Compare Alpha and Beta"},
                {"type": "basic", "content": "Finished report"},
            ],
        )

    async def test_failed_background_report_writes_failed_status(self):
        store = FakeReportStore()
        request = self._request()

        async def fake_write_report(research_request, research_id):
            raise RuntimeError("generation failed")

        with (
            patch.object(app_module, "report_store", store),
            patch.object(app_module, "write_report", fake_write_report),
        ):
            with self.assertRaises(RuntimeError):
                await app_module.write_report_and_store(request, "rid")

        record = store.records["rid"]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["question"], "Compare Alpha and Beta")
        self.assertEqual(record["error"], "generation failed")

    async def test_status_endpoint_reads_report_store_status(self):
        store = FakeReportStore()
        store.records["rid"] = {
            "id": "rid",
            "status": "completed",
            "timestamp": 123,
            "artifacts": {"html": "outputs/rid.html"},
        }

        with patch.object(app_module, "report_store", store):
            response = await app_module.get_report_status("rid")

        self.assertEqual(
            response,
            {
                "research_id": "rid",
                "status": "completed",
                "timestamp": 123,
                "error": None,
                "artifacts": {"html": "outputs/rid.html"},
                "report_artifacts": None,
                "trace_summary": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
