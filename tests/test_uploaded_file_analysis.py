from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.server.server_utils import resolve_uploaded_file_paths
from backend.server.websocket_manager import run_agent
from rivalens.research.evidence_collector import ResearchEngineEvidenceCollector
from rivalens.research.utils.enum import Tone


class UploadedFilePathTests(unittest.TestCase):
    def test_accepts_files_inside_doc_path(self) -> None:
        doc_path = Path(__file__).parent / "fixtures" / "my-docs"
        uploaded_file = doc_path / "pricing.csv"

        resolved = resolve_uploaded_file_paths(
            [uploaded_file.name, str(uploaded_file)],
            str(doc_path),
        )

        self.assertEqual(resolved, [str(uploaded_file.resolve())])

    def test_rejects_files_outside_doc_path(self) -> None:
        doc_path = Path(__file__).parent / "fixtures" / "my-docs"
        outside_file = Path(__file__).resolve()

        with self.assertRaises(HTTPException) as context:
            resolve_uploaded_file_paths([str(outside_file)], str(doc_path))

        self.assertEqual(context.exception.status_code, 400)


class LocalEvidenceCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rivalens_runner_receives_uploaded_file_paths(self) -> None:
        run_task = AsyncMock(return_value={"report": "ok"})
        with (
            patch(
                "backend.server.websocket_manager.run_rivalens_task",
                run_task,
            ),
            patch(
                "backend.server.websocket_manager.build_rivalens_structured_response",
                side_effect=lambda state, fallback_run_id=None: state,
            ),
        ):
            await run_agent(
                task="Compare Acme and Beta",
                report_type="rivalens",
                report_source="local",
                source_urls=[],
                document_urls=[],
                tone=Tone.Objective,
                websocket=None,
                files=["E:/rivalens/my-docs/pricing.csv"],
            )

        self.assertEqual(
            run_task.await_args.kwargs["files"],
            ["E:/rivalens/my-docs/pricing.csv"],
        )
        self.assertEqual(run_task.await_args.kwargs["report_source"], "local")

    async def test_uses_uploaded_file_without_web_research(self) -> None:
        collector = ResearchEngineEvidenceCollector()
        collection_task = {
            "id": "collect_acme_pricing",
            "branch_id": "branch_acme_pricing",
            "research_task_id": "task_acme_pricing",
            "competitor": "Acme",
            "dimension_id": "pricing",
            "dimension_name": "Pricing",
            "query": "Acme Pro plan pricing",
            "file_rag_context": "Local file RAG context: Acme Pro costs $99.",
            "file_context_chunks": [
                {
                    "source_name": "pricing.csv",
                    "source_path": "my-docs/pricing.csv",
                    "title": "pricing.csv row 1",
                    "text": "competitor: Acme; plan: Pro; price: $99",
                }
            ],
        }

        result = await collector.collect(
            collection_task=collection_task,
            source="local",
        )

        self.assertEqual(result["costs"], 0.0)
        self.assertEqual(result["context"], collection_task["file_rag_context"])
        self.assertEqual(len(result["evidence_items"]), 1)
        evidence = result["evidence_items"][0]
        self.assertEqual(evidence["url"], "/files/pricing.csv")
        self.assertEqual(evidence["source_cache"]["origin"], "user_upload")
        self.assertIn("Acme", evidence["excerpt"])


if __name__ == "__main__":
    unittest.main()
