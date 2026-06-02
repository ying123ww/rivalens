from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from rivalens.research.actions.query_processing import _normalize_sub_queries_response
from rivalens.research.skills.researcher import ResearchConductor


class UniFuncsDeepSearch:
    pass


class TavilySearch:
    pass


class OtherSearch:
    pass


class MCPRetriever:
    pass


class InitialPlanningSearchTest(unittest.IsolatedAsyncioTestCase):
    def _conductor(self, retrievers, max_results=2):
        researcher = SimpleNamespace(
            retrievers=retrievers,
            websocket=None,
            role="researcher",
            cfg=SimpleNamespace(max_search_results_per_query=max_results),
            parent_query="",
            report_type="research_report",
            add_costs=lambda *args, **kwargs: None,
            kwargs={},
            rivalens_search_queries=[],
            rivalens_trace_context={},
        )
        return ResearchConductor(researcher)

    def test_normalizes_text_block_subquery_response(self):
        response = [
            {
                "type": "text",
                "text": (
                    "[\"截至2026年6月 Perplexity AI 官方正版网站 "
                    "全系列已公开上线产品 官方合规登记备案信息\"]"
                ),
            }
        ]

        self.assertEqual(
            _normalize_sub_queries_response(response),
            [
                "截至2026年6月 Perplexity AI 官方正版网站 "
                "全系列已公开上线产品 官方合规登记备案信息"
            ],
        )

    def test_normalizes_structured_query_objects(self):
        response = {
            "queries": [
                {
                    "query": "Acme pricing official plans",
                    "researchGoal": "Verify official pricing and plan packaging.",
                },
                {
                    "query": "Acme docs billing limits",
                    "researchGoal": "Find documented billing limits.",
                },
            ]
        }

        self.assertEqual(
            _normalize_sub_queries_response(response),
            ["Acme pricing official plans", "Acme docs billing limits"],
        )

    async def test_plan_research_uses_rivalens_preplanned_search_queries_without_llm_rewrite(self):
        conductor = self._conductor([UniFuncsDeepSearch], max_results=2)
        conductor.researcher.rivalens_search_queries = [
            "Perplexity 官网 产品 公开登记",
            "Perplexity official site product public registry",
            "Perplexity 官网 产品 公开登记",
        ]
        conductor.researcher.rivalens_trace_context = {
            "branch_id": "collect_perplexity_competitor_profile",
        }
        outline = AsyncMock(return_value=["rewritten query"])

        with (
            patch(
                "rivalens.research.skills.researcher.get_search_results",
                new_callable=AsyncMock,
            ) as get_search_results,
            patch(
                "rivalens.research.skills.researcher.plan_research_outline",
                outline,
            ),
        ):
            result = await conductor.plan_research("Perplexity 官网 产品 公开登记")

        self.assertEqual(
            result,
            [
                "Perplexity 官网 产品 公开登记",
                "Perplexity official site product public registry",
            ],
        )
        get_search_results.assert_not_called()
        outline.assert_not_called()

    async def test_plan_research_merges_non_mcp_retrievers_in_config_order(self):
        conductor = self._conductor([UniFuncsDeepSearch, TavilySearch], max_results=2)
        outline = AsyncMock(return_value=["pricing query"])

        async def fake_get_search_results(query, retriever, query_domains=None, researcher=None):
            if retriever is UniFuncsDeepSearch:
                return [
                    {"href": "https://a.example/pricing", "title": "A"},
                    {"href": "https://shared.example/pricing", "title": "Shared from unifuncs"},
                ]
            if retriever is TavilySearch:
                return [
                    {"href": "https://shared.example/pricing", "title": "Shared from tavily"},
                    {"href": "https://b.example/pricing", "title": "B"},
                ]
            return []

        with (
            patch(
                "rivalens.research.skills.researcher.get_search_results",
                side_effect=fake_get_search_results,
            ) as get_search_results,
            patch(
                "rivalens.research.skills.researcher.plan_research_outline",
                outline,
            ),
        ):
            result = await conductor.plan_research(
                "AcmeAI pricing",
                query_domains=["example.com"],
            )

        self.assertEqual(result, ["pricing query"])
        self.assertEqual(
            [call.args[1] for call in get_search_results.call_args_list],
            [UniFuncsDeepSearch, TavilySearch],
        )
        merged_results = outline.call_args.kwargs["search_results"]
        self.assertEqual(
            [result["href"] for result in merged_results],
            [
                "https://a.example/pricing",
                "https://shared.example/pricing",
                "https://b.example/pricing",
            ],
        )

    async def test_plan_research_keeps_results_when_one_retriever_fails(self):
        conductor = self._conductor([UniFuncsDeepSearch, TavilySearch], max_results=2)
        outline = AsyncMock(return_value=["fallback query"])

        async def fake_get_search_results(query, retriever, query_domains=None, researcher=None):
            if retriever is UniFuncsDeepSearch:
                raise RuntimeError("upstream unavailable")
            return [{"href": "https://b.example/pricing", "title": "B"}]

        with (
            patch(
                "rivalens.research.skills.researcher.get_search_results",
                side_effect=fake_get_search_results,
            ),
            patch(
                "rivalens.research.skills.researcher.plan_research_outline",
                outline,
            ),
        ):
            await conductor.plan_research("AcmeAI pricing")

        merged_results = outline.call_args.kwargs["search_results"]
        self.assertEqual(
            [result["href"] for result in merged_results],
            ["https://b.example/pricing"],
        )

    async def test_plan_research_caps_merged_results(self):
        conductor = self._conductor(
            [UniFuncsDeepSearch, TavilySearch, OtherSearch],
            max_results=2,
        )
        outline = AsyncMock(return_value=["capped query"])

        async def fake_get_search_results(query, retriever, query_domains=None, researcher=None):
            prefix = retriever.__name__.lower()
            return [
                {"href": f"https://{prefix}.example/1", "title": "1"},
                {"href": f"https://{prefix}.example/2", "title": "2"},
                {"href": f"https://{prefix}.example/3", "title": "3"},
            ]

        with (
            patch(
                "rivalens.research.skills.researcher.get_search_results",
                side_effect=fake_get_search_results,
            ),
            patch(
                "rivalens.research.skills.researcher.plan_research_outline",
                outline,
            ),
        ):
            await conductor.plan_research("AcmeAI pricing")

        merged_results = outline.call_args.kwargs["search_results"]
        self.assertEqual(len(merged_results), 4)
        self.assertEqual(
            [result["href"] for result in merged_results],
            [
                "https://unifuncsdeepsearch.example/1",
                "https://unifuncsdeepsearch.example/2",
                "https://tavilysearch.example/1",
                "https://tavilysearch.example/2",
            ],
        )

    async def test_plan_research_falls_back_to_current_behavior_for_mcp_only(self):
        conductor = self._conductor([MCPRetriever], max_results=2)
        outline = AsyncMock(return_value=["mcp query"])

        async def fake_get_search_results(query, retriever, query_domains=None, researcher=None):
            return [{"href": "mcp://result", "title": "MCP result"}]

        with (
            patch(
                "rivalens.research.skills.researcher.get_search_results",
                side_effect=fake_get_search_results,
            ) as get_search_results,
            patch(
                "rivalens.research.skills.researcher.plan_research_outline",
                outline,
            ),
        ):
            result = await conductor.plan_research("AcmeAI pricing")

        self.assertEqual(result, ["mcp query"])
        self.assertEqual(get_search_results.call_args.args[1], MCPRetriever)
        merged_results = outline.call_args.kwargs["search_results"]
        self.assertEqual(merged_results, [{"href": "mcp://result", "title": "MCP result"}])
