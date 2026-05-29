import asyncio
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from rivalens.agents.messages import create_agent_message
from rivalens.agents.publishing import PublisherAgent
from rivalens.report_export import generate_report_files


class ReportExportTest(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path("outputs/test_report_export")
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_generate_report_files_exports_markdown_html_and_named_artifacts(self):
        async def fake_pdf(path, report, css_path=None):
            path.write_text("pdf", encoding="utf-8")
            return path.as_posix()

        async def fake_docx(path, report):
            path.write_text("docx", encoding="utf-8")
            return path.as_posix()

        with (
            patch("rivalens.report_export._write_pdf", fake_pdf),
            patch("rivalens.report_export._write_docx", fake_docx),
        ):
            artifacts = asyncio.run(
                generate_report_files(
                    "# Rivalens\n\nA traceable report.",
                    "demo report",
                    output_dir=self.output_dir,
                    include_legacy_md_key=True,
                )
            )

        self.assertEqual(
            set(artifacts),
            {"markdown", "pdf", "docx", "html", "md"},
        )
        self.assertEqual(artifacts["md"], artifacts["markdown"])
        self.assertTrue(Path(artifacts["markdown"]).exists())
        self.assertTrue(Path(artifacts["html"]).exists())
        self.assertIn("<html", Path(artifacts["html"]).read_text(encoding="utf-8"))

    def test_publisher_uses_shared_export_and_publishes_all_artifacts(self):
        async def fake_generate_report_files(report, filename, **kwargs):
            return {
                "markdown": "outputs/rivalens/competitor_analysis.md",
                "pdf": "outputs/rivalens/competitor_analysis.pdf",
                "docx": "outputs/rivalens/competitor_analysis.docx",
                "html": "outputs/rivalens/competitor_analysis.html",
            }

        with patch(
            "rivalens.agents.publishing.generate_report_files",
            fake_generate_report_files,
        ):
            result = asyncio.run(
                PublisherAgent(output_dir=str(self.output_dir)).run(
                    {"report": "# Full Rivalens report", "messages": []}
                )
            )

        self.assertEqual(
            result["published_artifacts"]["markdown"],
            "outputs/rivalens/competitor_analysis.md",
        )
        self.assertIn("pdf", result["published_artifacts"])
        self.assertIn("docx", result["published_artifacts"])
        self.assertIn("html", result["published_artifacts"])
        self.assertEqual(
            result["messages"][-1]["payload"],
            result["published_artifacts"],
        )

    def test_publish_payload_accepts_pdf_docx_and_html(self):
        message = create_agent_message(
            sender="publisher",
            receiver="end",
            message_type="publish",
            payload={
                "markdown": "report.md",
                "pdf": "report.pdf",
                "docx": "report.docx",
                "html": "report.html",
            },
        )

        self.assertEqual(message["payload"]["pdf"], "report.pdf")
        self.assertEqual(message["payload"]["docx"], "report.docx")
        self.assertEqual(message["payload"]["html"], "report.html")


if __name__ == "__main__":
    unittest.main()
