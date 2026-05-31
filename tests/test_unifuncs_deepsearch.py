import os
import sys
import types
import unittest
from importlib import util
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = util.spec_from_file_location(name, path)
    module = util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class UniFuncsDeepSearchTest(unittest.TestCase):
    def test_retriever_factory_resolves_unifuncs_deepsearch(self):
        retriever_module = load_module(
            "retriever_factory",
            REPO_ROOT / "rivalens" / "research" / "actions" / "retriever.py",
        )
        fake_retrievers = types.ModuleType("rivalens.research.retrievers")

        class UniFuncsDeepSearch:
            pass

        fake_retrievers.UniFuncsDeepSearch = UniFuncsDeepSearch

        with patch.dict(sys.modules, {"rivalens.research.retrievers": fake_retrievers}):
            retriever_class = retriever_module.get_retriever("unifuncs_deepsearch")

        self.assertIsNotNone(retriever_class)
        self.assertEqual(retriever_class.__name__, "UniFuncsDeepSearch")

    def test_search_extracts_urls_without_marking_summary_as_raw_content(self):
        fake_requests = types.ModuleType("requests")
        fake_requests.post = Mock()
        with patch.dict(sys.modules, {"requests": fake_requests}):
            unifuncs_module = load_module(
                "unifuncs_deepsearch_module",
                REPO_ROOT
                / "rivalens"
                / "research"
                / "retrievers"
                / "unifuncs_deepsearch"
                / "unifuncs_deepsearch.py",
            )
        retriever_class = unifuncs_module.UniFuncsDeepSearch

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "1. [Notion pricing](https://www.notion.so/pricing) - "
                            "Official pricing page with plan details.\n"
                            "2. ClickUp docs: https://clickup.com/features - "
                            "Feature overview page."
                        )
                    }
                }
            ]
        }
        response.raise_for_status = Mock()

        with patch.dict(os.environ, {"UNIFUNCS_API_KEY": "sk-test"}, clear=False):
            with patch.object(unifuncs_module.requests, "post", return_value=response) as post:
                retriever = retriever_class(
                    "Compare Notion and ClickUp pricing",
                    query_domains=["notion.so", "clickup.com"],
                )
                results = retriever.search(max_results=5)

        self.assertEqual(
            [result["href"] for result in results],
            ["https://www.notion.so/pricing", "https://clickup.com/features"],
        )
        self.assertTrue(all(result["source_provider"] == "unifuncs_deepsearch" for result in results))
        self.assertTrue(all("raw_content" not in result for result in results))

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "s3")
        self.assertEqual(payload["domain_scope"], ["notion.so", "clickup.com"])
        self.assertEqual(payload["reference_style"], "link")

    def test_unifuncs_results_are_routed_to_scraper_queue(self):
        fake_requests = types.ModuleType("requests")
        fake_requests.post = Mock()
        with patch.dict(sys.modules, {"requests": fake_requests}):
            unifuncs_module = load_module(
                "unifuncs_deepsearch_module_scraper_queue",
                REPO_ROOT
                / "rivalens"
                / "research"
                / "retrievers"
                / "unifuncs_deepsearch"
                / "unifuncs_deepsearch.py",
            )
        retriever_class = unifuncs_module.UniFuncsDeepSearch

        response = Mock()
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "[Notion pricing](https://www.notion.so/pricing) - "
                            "Short search summary only."
                        )
                    }
                }
            ]
        }
        response.raise_for_status = Mock()

        with patch.dict(os.environ, {"UNIFUNCS_API_KEY": "sk-test"}, clear=False):
            with patch.object(unifuncs_module.requests, "post", return_value=response):
                results = retriever_class("Compare pricing").search(max_results=5)

        scrape_queue = []
        prefetched_content = []
        for result in results:
            url = result.get("href") or result.get("url")
            raw_content = result.get("raw_content")
            if result.get("content_is_full_text"):
                raw_content = raw_content or result.get("body")
            if url and raw_content and len(raw_content) > 100:
                prefetched_content.append({"url": url, "raw_content": raw_content})
            elif url:
                scrape_queue.append(url)

        self.assertEqual(scrape_queue, ["https://www.notion.so/pricing"])
        self.assertEqual(prefetched_content, [])


if __name__ == "__main__":
    unittest.main()
