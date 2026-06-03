import asyncio
import unittest
from contextvars import Context, ContextVar
from types import SimpleNamespace
from unittest.mock import patch

from rivalens.agents.analysis import AnalysisAgent
from rivalens.agents.claim_support import ClaimSupportReviewer
from rivalens.agents.collection import CollectionAgent
from rivalens.agents.coverage_review import (
    CoverageReviewer,
    _coverage_review_trace_inputs,
    _coverage_review_trace_outputs,
)
from rivalens.agents.evidence_review import (
    EvidenceQualityReviewer,
    _evidence_review_trace_inputs,
    _evidence_review_trace_outputs,
)
from rivalens.agents.knowledge_structuring import KnowledgeStructuringAgent
from rivalens.agents.writing import (
    ANALYSIS_OVERVIEW_CONTEXT_CHAR_LIMIT,
    OPENING_CONTEXT_CHAR_LIMIT,
    SECTION_CONTEXT_CHAR_LIMIT,
    SUMMARY_CONTEXT_CHAR_LIMIT,
    ReportWriterAgent,
)
from rivalens.research.evidence_collector import (
    ResearchEngineEvidenceCollector,
    _collect_trace_inputs,
    _collect_trace_outputs,
)
from rivalens.research.actions.query_processing import _search_trace_inputs
from rivalens.research.agent import ResearchEngine
from rivalens.research.llm_provider.generic.base import GenericLLMProvider
from rivalens.research.scraper.scraper import _scrape_trace_inputs
from rivalens.research.skills.researcher import (
    ResearchConductor,
    _retriever_trace_inputs,
    _subquery_trace_inputs,
    _subquery_trace_outputs,
)
from rivalens.research.trace_context import (
    RIVALENS_SEARCH_QUERIES_KEY,
    RIVALENS_TRACE_CONTEXT_KEY,
    langsmith_extra_for_trace_context,
)
from rivalens.schema import SOURCE_TYPE_PRIORITY
from rivalens.workflows.competitive_analysis import _int_budget, _workflow_run_config


def pricing_branch():
    return {
        "id": "collect_acme_pricing_model",
        "depth": 0,
        "competitor": "Acme",
        "dimension_id": "pricing_model",
        "dimension_name": "Pricing Model",
        "topic": "Pricing Model",
    }


def _word_count(query: str) -> int:
    return len(query.split())


class CollectionReviewTest(unittest.TestCase):
    def test_collection_budget_reads_env_with_safe_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "RIVALENS_MAX_BRANCH_DEPTH": "0",
                "RIVALENS_MAX_EXPANSION_BRANCHES": "3",
                "RIVALENS_MAX_ROOT_BRANCHES": "2",
            },
        ):
            self.assertEqual(
                _int_budget(None, "RIVALENS_MAX_BRANCH_DEPTH", 1),
                0,
            )
            self.assertEqual(
                _int_budget(None, "RIVALENS_MAX_EXPANSION_BRANCHES", 24),
                3,
            )
            self.assertEqual(
                _int_budget(None, "RIVALENS_MAX_ROOT_BRANCHES", 20, minimum=1),
                2,
            )

        with patch.dict("os.environ", {"RIVALENS_MAX_EXPANSION_BRANCHES": "bad"}):
            self.assertEqual(
                _int_budget(None, "RIVALENS_MAX_EXPANSION_BRANCHES", 24),
                24,
            )
            self.assertEqual(
                _int_budget(5, "RIVALENS_MAX_EXPANSION_BRANCHES", 24),
                5,
            )

    def test_collection_agent_reads_root_branch_limit_from_env(self):
        with patch.dict("os.environ", {"RIVALENS_MAX_ROOT_BRANCHES": "2"}):
            self.assertEqual(CollectionAgent().max_root_branch_hard_limit, 2)
            self.assertEqual(
                CollectionAgent(max_root_branch_hard_limit=5).max_root_branch_hard_limit,
                5,
            )

        with patch.dict("os.environ", {"RIVALENS_MAX_ROOT_BRANCHES": "bad"}):
            self.assertEqual(CollectionAgent().max_root_branch_hard_limit, 20)

    def test_workflow_run_config_tags_collection_trace_metadata(self):
        task = {
            "query": "Compare Acme and Beta",
            "competitors": [{"name": "Acme"}, {"name": "Beta"}],
            "custom_analysis_directions": ["pricing", "security"],
            "industry_directions_confirmed": True,
            "deep_research": False,
        }

        with patch.dict(
            "os.environ",
            {
                "RETRIEVER": "unifuncs_deepsearch,tavily",
                "SCRAPER": "tavily_extract",
                "RIVALENS_MAX_BRANCH_DEPTH": "0",
                "RIVALENS_MAX_EXPANSION_BRANCHES": "3",
                "RIVALENS_MAX_ROOT_BRANCHES": "2",
            },
        ):
            config = _workflow_run_config(task, {})

        self.assertEqual(config["run_name"], "rivalens_competitive_analysis")
        self.assertIn("rivalens", config["tags"])
        self.assertIn("competitive-analysis", config["tags"])
        self.assertEqual(config["metadata"]["collector"], "CollectionAgent")
        self.assertEqual(config["metadata"]["competitor_count"], 2)
        self.assertEqual(config["metadata"]["competitors"], ["Acme", "Beta"])
        self.assertEqual(config["metadata"]["custom_analysis_direction_count"], 2)
        self.assertEqual(config["metadata"]["retriever"], "unifuncs_deepsearch,tavily")
        self.assertEqual(config["metadata"]["scraper"], "tavily_extract")
        self.assertEqual(config["metadata"]["max_branch_depth"], 0)
        self.assertEqual(config["metadata"]["max_expansion_branches"], 3)
        self.assertEqual(config["metadata"]["max_root_branch_hard_limit"], 2)

    def test_llm_provider_preserves_trace_context_in_executor(self):
        trace_token = ContextVar("rivalens_trace_token", default="missing")

        class ContextReadingLLM:
            def invoke(self, messages, **kwargs):
                return SimpleNamespace(content=trace_token.get())

        class ContextDroppingLoop:
            async def run_in_executor(self, executor, func):
                return Context().run(func)

        async def run_probe():
            provider = GenericLLMProvider(ContextReadingLLM())
            token = trace_token.set("parent-run")
            try:
                with patch("asyncio.get_running_loop", return_value=ContextDroppingLoop()):
                    return await provider.get_chat_response(
                        [{"role": "user", "content": "probe"}],
                        stream=False,
                    )
            finally:
                trace_token.reset(token)

        self.assertEqual(asyncio.run(run_probe()), "parent-run")

    def test_collection_trace_outputs_summarize_evidence_without_context_body(self):
        summary = _collect_trace_outputs(
            {
                "mode": "standard_evidence",
                "query": "Acme pricing",
                "context": "full page body " * 100,
                "costs": 0.12,
                "evidence_items": [
                    {
                        "id": "evidence_1",
                        "title": "Acme Pricing",
                        "url": "https://example.com/pricing",
                        "source_type": "pricing_page",
                        "confidence": 0.7,
                        "excerpt": "large source excerpt",
                    }
                ],
            }
        )

        self.assertEqual(summary["evidence_count"], 1)
        self.assertGreater(summary["context_length"], 0)
        self.assertNotIn("context", summary)
        self.assertNotIn("excerpt", summary["evidence"][0])
        self.assertEqual(summary["evidence"][0]["url"], "https://example.com/pricing")

    def test_branch_trace_context_reaches_collection_search_and_scrape_spans(self):
        class FakeRetriever:
            pass

        trace_context = {
            "id": "collect_acme_pricing",
            "branch_id": "collect_acme_pricing",
            "research_task_id": "task_collect_acme_pricing",
            "research_brief_id": "brief_collect_acme_pricing",
            "competitor": "Acme",
            "dimension_id": "pricing",
            "dimension_name": "Pricing",
            "search_stage": "focused",
            "query": "Acme pricing official",
            "search_queries": [
                "Acme pricing official",
                "Acme plans",
                "Acme pricing docs",
                "Acme official pricing page",
                "Acme enterprise pricing",
                "Acme billing",
                "Acme extra query",
            ],
            "source_hints": ["official_site", "pricing_page"],
            "target_url_count": 0,
        }
        researcher = SimpleNamespace(
            kwargs={RIVALENS_TRACE_CONTEXT_KEY: trace_context},
        )
        conductor = SimpleNamespace(researcher=researcher)

        collection_inputs = _collect_trace_inputs(
            {
                "collection_task": trace_context,
                "mode": "standard_evidence",
                "source_urls": [],
                "query_domains": ["example.com"],
            }
        )
        self.assertEqual(
            collection_inputs["collection_task"]["branch_id"],
            "collect_acme_pricing",
        )
        self.assertEqual(len(collection_inputs["collection_task"]["search_queries"]), 6)

        search_inputs = _search_trace_inputs(
            {
                "query": "Acme pricing 2026",
                "retriever": FakeRetriever,
                "query_domains": ["example.com"],
                "researcher": researcher,
            }
        )
        self.assertEqual(search_inputs["query"], "Acme pricing 2026")
        self.assertEqual(
            search_inputs["collection_task"]["branch_id"],
            "collect_acme_pricing",
        )

        retriever_inputs = _retriever_trace_inputs(
            {
                "self": conductor,
                "query": "Acme pricing 2026",
                "retriever_class": FakeRetriever,
                "query_domains": [],
                "max_results": 5,
            }
        )
        self.assertEqual(
            retriever_inputs["collection_task"]["dimension_id"],
            "pricing",
        )

        subquery_inputs = _subquery_trace_inputs(
            {
                "self": conductor,
                "sub_query": "Acme enterprise pricing",
                "scraped_data": [{"url": "https://example.com"}],
            }
        )
        self.assertEqual(subquery_inputs["scraped_data_size"], 1)
        self.assertEqual(
            subquery_inputs["collection_task"]["search_stage"],
            "focused",
        )
        self.assertEqual(
            _subquery_trace_outputs("context body")["context_chars"],
            len("context body"),
        )

        scrape_inputs = _scrape_trace_inputs(
            {
                "self": SimpleNamespace(trace_context=trace_context),
                "link": "https://example.com/pricing",
            }
        )
        self.assertEqual(scrape_inputs["url"], "https://example.com/pricing")
        self.assertEqual(
            scrape_inputs["collection_task"]["branch_id"],
            "collect_acme_pricing",
        )

        extra = langsmith_extra_for_trace_context(
            trace_context,
            operation="retriever_search",
            tags=["rivalens", "collection", "search"],
            metadata={"rivalens_actual_query": "Acme pricing 2026"},
        )
        self.assertIn("branch:collect_acme_pricing", extra["tags"])
        self.assertEqual(
            extra["metadata"]["rivalens_actual_query"],
            "Acme pricing 2026",
        )
        self.assertEqual(
            extra["metadata"]["rivalens_operation"],
            "retriever_search",
        )

    def test_review_trace_summaries_include_criteria_without_excerpt_body(self):
        branch = {
            **pricing_branch(),
            "research_brief_id": "brief_collect_acme_pricing_model",
            "research_goal": "Collect public pricing evidence.",
            "search_stage": "focused",
            "query": "Acme pricing official",
            "guiding_questions": ["What public starter pricing is available?"],
            "success_criteria": [
                {
                    "id": "public_pricing",
                    "description": "What public starter pricing is available?",
                    "target_source_types": ["pricing_page"],
                }
            ],
        }
        evidence = [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "dimension_id": "pricing_model",
                "title": "Acme pricing",
                "url": "https://acme.example/pricing",
                "source_type": "pricing_page",
                "excerpt": "Acme starter pricing is $10 per user. " * 20,
                "confidence": 0.9,
            }
        ]

        evidence_inputs = _evidence_review_trace_inputs(
            {"branch": branch, "evidence_items": evidence},
        )
        self.assertEqual(
            evidence_inputs["branch"]["success_criteria"][0]["id"],
            "public_pricing",
        )
        self.assertEqual(evidence_inputs["evidence"][0]["excerpt_chars"], 760)
        self.assertNotIn("excerpt", evidence_inputs["evidence"][0])

        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            evidence,
        )
        evidence_outputs = _evidence_review_trace_outputs(evidence_review)
        self.assertEqual(evidence_outputs["accepted_evidence_ids"], ["ev_1"])
        self.assertEqual(
            evidence_outputs["criterion_matches"][0]["criterion_ids"],
            ["public_pricing"],
        )

        coverage_inputs = _coverage_review_trace_inputs(
            {
                "branch": branch,
                "evidence_items": evidence,
                "evidence_review": evidence_review,
                "research_task_ids": ["task_collect_acme_pricing_model"],
            },
        )
        self.assertEqual(
            coverage_inputs["evidence_review"]["criterion_matches"],
            evidence_review["criterion_matches"],
        )
        self.assertNotIn("excerpt", coverage_inputs["evidence"][0])

        coverage = CoverageReviewer().review(
            branch=branch,
            evidence_items=evidence,
            evidence_review=evidence_review,
            research_task_ids=["task_collect_acme_pricing_model"],
        )
        coverage_outputs = _coverage_review_trace_outputs(coverage)
        self.assertEqual(coverage_outputs["next_action"], "ready_for_analysis")
        self.assertEqual(
            coverage_outputs["satisfied_criteria"][0]["id"],
            "public_pricing",
        )
        self.assertEqual(coverage_outputs["selected_follow_up_specs"], [])

    def test_research_engine_keeps_trace_context_out_of_llm_kwargs(self):
        trace_context = {
            "branch_id": "collect_acme_pricing",
            "research_task_id": "task_collect_acme_pricing",
            "search_stage": "focused",
        }

        with patch("rivalens.research.agent.Memory", return_value=SimpleNamespace()):
            researcher = ResearchEngine(
                query="Acme pricing",
                report_type="research_report",
                verbose=False,
                **{
                    RIVALENS_SEARCH_QUERIES_KEY: ["Acme pricing official"],
                    RIVALENS_TRACE_CONTEXT_KEY: trace_context,
                },
            )

        self.assertNotIn(RIVALENS_SEARCH_QUERIES_KEY, researcher.kwargs)
        self.assertNotIn(RIVALENS_TRACE_CONTEXT_KEY, researcher.kwargs)
        self.assertEqual(researcher.rivalens_search_queries, ["Acme pricing official"])
        self.assertEqual(
            researcher.rivalens_trace_context["branch_id"],
            "collect_acme_pricing",
        )

    def test_collection_root_branches_use_planned_industry_extensions(self):
        branches = CollectionAgent()._build_root_branches(
            query="Compare Acme and Beta",
            competitors=[{"name": "Acme"}],
            active_schema={
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {
                        "id": "direction_strategic_positioning",
                        "name": "战略定位",
                        "description": "品牌定位和市场细分。",
                        "source_hints": ["official_site", "news"],
                    }
                ],
            },
        )

        self.assertEqual(len(branches), 2)
        self.assertEqual(branches[0]["dimension_id"], "competitor_profile")
        self.assertEqual(branches[0]["dimension_name"], "竞品基础信息")
        self.assertEqual(branches[1]["dimension_id"], "direction_strategic_positioning")
        self.assertEqual(branches[1]["dimension_name"], "战略定位")
        self.assertLessEqual(_word_count(branches[1]["query"]), 15)
        self.assertEqual(branches[1]["query"], branches[1]["search_queries"][0])
        self.assertEqual(len(branches[1]["search_queries"]), 1)
        self.assertNotIn("Research focus:", branches[1]["query"])
        self.assertNotIn("Guiding questions:", branches[1]["query"])
        self.assertNotIn("Preferred evidence sources", branches[1]["query"])
        self.assertIn("Preferred evidence sources", branches[1]["task_context"])
        self.assertEqual(branches[1]["source_hints"], ["official_site", "news"])
        self.assertEqual(branches[1]["search_stage"], "focused")

    def test_collection_root_branch_limit_applies_per_competitor(self):
        class FakeCollector:
            async def collect(self, collection_task, mode, verbose, source_urls=None):
                return {
                    "task": collection_task,
                    "mode": mode.value,
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [],
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme and Beta",
                "verbose": False,
            },
            "competitors": [{"name": "Acme"}, {"name": "Beta"}],
            "active_knowledge_schema": {
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {"id": "positioning", "name": "Positioning"},
                    {"id": "pricing", "name": "Pricing"},
                    {"id": "security", "name": "Security"},
                ],
            },
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=FakeCollector(),
                max_branch_depth=0,
                max_root_branch_hard_limit=2,
            ).run(state)
        )

        root_branches = result["research_branches"]
        self.assertEqual(len(root_branches), 4)
        self.assertEqual(
            [branch["competitor"] for branch in root_branches],
            ["Acme", "Acme", "Beta", "Beta"],
        )
        self.assertEqual(
            result["agent_events"][-1]["input"]["max_root_branches_per_competitor"],
            2,
        )
        self.assertTrue(result["agent_events"][-1]["input"]["root_branch_limit_exceeded"])

    def test_collection_follow_up_slots_are_distributed_across_competitors(self):
        class EmptyCollector:
            async def collect(self, collection_task, mode, verbose, source_urls=None):
                return {
                    "task": collection_task,
                    "mode": mode.value,
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [],
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme and Beta pricing",
                "verbose": False,
            },
            "competitors": [{"name": "Acme"}, {"name": "Beta"}],
            "active_knowledge_schema": {
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {
                        "id": "pricing_business_model",
                        "name": "Pricing",
                        "description": "Pricing and packaging",
                        "source_hints": ["pricing_page", "official_site"],
                        "guiding_questions": ["What pricing evidence is public?"],
                    }
                ],
            },
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=EmptyCollector(),
                max_branch_depth=1,
                max_expansion_branches=2,
            ).run(state)
        )

        child_competitors = [
            branch["competitor"]
            for branch in result["research_branches"]
            if branch.get("depth") == 1
        ]
        self.assertEqual(len(child_competitors), 2)
        self.assertEqual(set(child_competitors), {"Acme", "Beta"})

    def test_collection_run_limits_concurrent_collection_tasks(self):
        class CountingCollector:
            def __init__(self):
                self.active = 0
                self.max_active = 0

            async def collect(self, collection_task, mode, verbose, source_urls=None):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0.01)
                self.active -= 1
                return {
                    "task": collection_task,
                    "mode": mode.value,
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [],
                    "costs": 0.0,
                }

        collector = CountingCollector()
        state = {
            "task": {
                "query": "Compare Acme and Beta",
                "verbose": False,
            },
            "competitors": [{"name": "Acme"}],
            "active_knowledge_schema": {
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {"id": "positioning", "name": "Positioning"},
                    {"id": "pricing", "name": "Pricing"},
                    {"id": "security", "name": "Security"},
                ],
            },
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=collector,
                max_branch_depth=0,
                max_concurrent_collections=2,
            ).run(state)
        )

        self.assertLessEqual(collector.max_active, 2)
        self.assertEqual(
            result["agent_events"][-1]["input"]["max_concurrent_collections"],
            2,
        )

    def test_research_conductor_limits_concurrent_subqueries(self):
        class FakeResearcher:
            verbose = False
            websocket = None
            retrievers = []
            report_type = "subtopic_report"
            mcp_strategy = "fast"

        async def run_probe():
            conductor = ResearchConductor(FakeResearcher())
            conductor.max_subquery_concurrency = 2
            active = 0
            max_active = 0

            async def fake_plan_research(query, query_domains=None):
                return ["query-1", "query-2", "query-3", "query-4"]

            async def fake_process_sub_query(sub_query, scraped_data=None, query_domains=None):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.01)
                active -= 1
                return sub_query

            conductor.plan_research = fake_plan_research
            conductor._process_sub_query = fake_process_sub_query

            context = await conductor._get_context_by_web_search("root", [], [])
            return context, max_active

        context, max_active = asyncio.run(run_probe())

        self.assertLessEqual(max_active, 2)
        self.assertIn("query-1", context)
        self.assertIn("query-4", context)

    def test_research_conductor_expands_single_seed_query(self):
        one_seed = ResearchConductor(
            SimpleNamespace(
                rivalens_search_queries=["Acme Pricing"],
                rivalens_trace_context={},
            )
        )
        multi_query = ResearchConductor(
            SimpleNamespace(
                rivalens_search_queries=["Acme Pricing", "Acme Reviews"],
                rivalens_trace_context={},
            )
        )

        self.assertEqual(one_seed._rivalens_preplanned_search_queries(), [])
        self.assertEqual(
            multi_query._rivalens_preplanned_search_queries(),
            ["Acme Pricing", "Acme Reviews"],
        )

    def test_collection_does_not_fallback_to_core_fields(self):
        branches = CollectionAgent()._build_root_branches(
            query="Compare Acme and Beta",
            competitors=[{"name": "Acme"}],
            active_schema={
                "selected_industry": {"name": "Productivity SaaS"},
                "core_fields": ["feature_tree", "pricing_model", "user_personas"],
                "industry_extensions": [],
            },
        )

        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["dimension_id"], "competitor_profile")

    def test_profile_collection_branch_targets_competitor_cards(self):
        branches = CollectionAgent()._build_root_branches(
            query="Compare Taobao and JD",
            competitors=[{"name": "淘宝"}],
            active_schema={
                "selected_industry": {"name": "零售 / 电商"},
                "industry_extensions": [],
            },
        )

        profile_branch = branches[0]
        self.assertEqual(profile_branch["dimension_id"], "competitor_profile")
        self.assertEqual(profile_branch["dimension_type"], "profile")
        self.assertIn("竞品基础信息", profile_branch["dimension_name"])
        self.assertIn("official_site", profile_branch["source_hints"])
        self.assertLessEqual(_word_count(profile_branch["query"]), 15)
        self.assertNotIn("report competitor information card", profile_branch["query"])
        self.assertIn("report competitor information card", profile_branch["task_context"])

    def test_collection_task_uses_short_query_and_keeps_context_separate(self):
        branches = CollectionAgent()._build_root_branches(
            query="Compare AcmeAI and BetaAI for pricing, packaging, and security posture",
            competitors=[{"name": "AcmeAI"}],
            active_schema={
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {
                        "id": "pricing_packaging",
                        "name": "Pricing and packaging",
                        "description": (
                            "Compare public plans, fees, packaging, "
                            "and enterprise tiers."
                        ),
                        "source_hints": ["official_site", "pricing_page", "review"],
                        "guiding_questions": [
                            "What plans are public?",
                            "What fees or tiers are visible?",
                        ],
                    }
                ],
            },
        )

        branch = next(
            branch
            for branch in branches
            if branch["dimension_id"] == "pricing_packaging"
        )
        collection_task = CollectionAgent()._branch_to_collection_task(branch)

        self.assertEqual(collection_task["query"], branch["search_queries"][0])
        self.assertLessEqual(_word_count(collection_task["query"]), 15)
        self.assertIn("AcmeAI", collection_task["query"])
        self.assertNotIn("Compare AcmeAI and BetaAI", collection_task["query"])
        self.assertNotIn("Guiding questions:", collection_task["query"])
        self.assertIn("Compare AcmeAI and BetaAI", collection_task["task_context"])
        self.assertIn("Success criteria:", collection_task["task_context"])
        self.assertEqual(collection_task["search_queries"], branch["search_queries"])
        self.assertEqual(
            [criterion["id"] for criterion in collection_task["success_criteria"]],
            ["guiding_question_1", "guiding_question_2"],
        )
        self.assertEqual(collection_task["search_queries"], [collection_task["query"]])

    def test_short_queries_are_generic_across_competitor_names(self):
        forbidden_demo_aliases = ["Feishu", "Lark", "DingTalk", "飞书", "钉钉"]
        for competitor in ["AcmeAI", "某通用协作工具", "美团"]:
            with self.subTest(competitor=competitor):
                branches = CollectionAgent()._build_root_branches(
                    query=f"分析 {competitor} 的定价和商业模式",
                    competitors=[{"name": competitor}],
                    active_schema={
                        "selected_industry": {"name": "通用行业"},
                        "industry_extensions": [
                            {
                                "id": "pricing_business_model",
                                "name": "定价和商业模式",
                                "description": (
                                    "Compare public pricing, packaging, "
                                    "fees, and business model."
                                ),
                                "source_hints": ["official_site", "pricing_page"],
                            }
                        ],
                    },
                )
                branch = next(
                    branch
                    for branch in branches
                    if branch["dimension_id"] == "pricing_business_model"
                )
                joined_queries = " ".join(branch["search_queries"])

                self.assertEqual(branch["query"], branch["search_queries"][0])
                self.assertTrue(any("定价" in query for query in branch["search_queries"]))
                self.assertEqual(len(branch["search_queries"]), 1)
                for query in branch["search_queries"]:
                    self.assertLessEqual(_word_count(query), 15)
                for alias in forbidden_demo_aliases:
                    self.assertNotIn(alias, joined_queries)

    def test_collection_run_does_not_append_file_rag_to_search_query(self):
        class CapturingCollector:
            def __init__(self):
                self.tasks = []

            async def collect(
                self,
                collection_task,
                mode="standard_evidence",
                verbose=True,
                source_urls=None,
            ):
                self.tasks.append(dict(collection_task))
                return {
                    "task": dict(collection_task),
                    "mode": str(mode),
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [],
                    "costs": 0.0,
                }

        collector = CapturingCollector()
        state = {
            "task": {
                "query": "Compare AcmeAI and BetaAI",
                "verbose": False,
            },
            "competitors": [{"name": "AcmeAI"}],
            "active_knowledge_schema": {
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [],
            },
            "file_context": {
                "chunks": [
                    {
                        "source_name": "brief.md",
                        "title": "Pricing",
                        "text": "AcmeAI enterprise pricing and packaging details.",
                    }
                ]
            },
            "messages": [],
        }

        asyncio.run(
            CollectionAgent(
                evidence_collector=collector,
                max_branch_depth=0,
            ).run(state)
        )

        self.assertTrue(collector.tasks)
        collection_task = collector.tasks[0]
        self.assertNotIn("Local file RAG context", collection_task["query"])
        self.assertIn("file_rag_context", collection_task)
        self.assertIn("Local file RAG context", collection_task["file_rag_context"])

    def test_knowledge_structuring_enriches_competitor_profiles_from_profile_evidence(self):
        state = {
            "task": {"query": "对比淘宝、京东、拼多多"},
            "competitors": [{"name": "淘宝"}],
            "active_knowledge_schema": {
                "id": "active_schema_retail",
                "selected_industry": {"name": "零售 / 电商"},
                "industry_extensions": [],
            },
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "淘宝",
                    "dimension_id": "competitor_profile",
                    "dimension_name": "竞品基础信息",
                    "title": "淘宝官网",
                    "url": "https://www.taobao.com",
                    "source_type": "official_site",
                    "excerpt": "淘宝是面向消费者和商家的综合电商平台。",
                    "confidence": 0.9,
                }
            ],
            "evidence_reviews": [{"accepted_evidence_ids": ["ev_1"]}],
            "messages": [],
        }

        result = asyncio.run(KnowledgeStructuringAgent().run(state))

        self.assertEqual(result["competitors"][0]["name"], "淘宝")
        self.assertEqual(result["competitors"][0]["product"], "淘宝")
        self.assertEqual(result["competitors"][0]["website"], "https://www.taobao.com")
        self.assertEqual(result["competitors"][0]["category"], "零售 / 电商")
        self.assertEqual(result["competitors"][0]["evidence_ids"], ["ev_1"])
        self.assertIn("综合电商平台", result["competitors"][0]["notes"])

    def test_collection_generates_guiding_question_follow_up_tasks(self):
        class FakeEvidenceCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                gap = collection_task.get("generated_from_gap", "")
                if collection_task.get("dimension_id") == "competitor_profile":
                    source = {
                        "competitor": "Acme",
                        "dimension_id": "competitor_profile",
                        "title": "Acme official site",
                        "url": "https://acme.example",
                        "source_type": "official_site",
                        "excerpt": (
                            "Acme is the official website and product brand identity "
                            "for the Acme platform, categorized and positioned as a "
                            "productivity SaaS platform."
                        ),
                        "confidence": 0.9,
                    }
                elif gap == "missing_guiding_question":
                    source = {
                        "competitor": "Acme",
                        "dimension_id": "pricing_business_model",
                        "title": "Acme packaging",
                        "url": "https://acme.example/packaging",
                        "source_type": "official_site",
                        "excerpt": "Acme publishes packaging details for enterprise buyers.",
                        "confidence": 0.9,
                    }
                else:
                    source = {
                        "competitor": "Acme",
                        "dimension_id": "pricing_business_model",
                        "title": "Acme market note",
                        "url": "https://news.example/acme-pricing",
                        "source_type": "news",
                        "excerpt": "A news item mentions Acme monetization but no official pricing page.",
                        "confidence": 0.6,
                    }

                return {
                    "task": dict(collection_task),
                    "mode": "standard_evidence",
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [source],
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme pricing",
                "competitors": [{"name": "Acme"}],
                "verbose": False,
            },
            "active_knowledge_schema": {
                "id": "schema_productivity",
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {
                        "id": "pricing_business_model",
                        "name": "定价与商业模式",
                        "description": "价格、套餐、计费单位、免费层、企业销售和收入模式。",
                        "source_hints": ["pricing_page", "official_site"],
                        "guiding_questions": [
                            "What monetization evidence is public?",
                            "What packaging details are available?",
                        ],
                    }
                ],
            },
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=FakeEvidenceCollector(),
                max_branch_depth=1,
                max_expansion_branches=4,
            ).run(state)
        )

        generated_gaps = [
            task.get("generated_from_gap", "")
            for task in result["research_tasks"]
        ]
        pricing_root_assessment = next(
            assessment
            for assessment in result["coverage_assessments"]
            if assessment["branch_id"] == "collect_acme_pricing_business_model"
        )
        self.assertIn("missing_guiding_question", generated_gaps)
        self.assertGreaterEqual(len(result["coverage_assessments"]), 2)
        self.assertEqual(
            pricing_root_assessment["next_action"],
            "collect_more",
        )
        self.assertEqual(
            pricing_root_assessment["decision"]["action"],
            "source_discovery",
        )
        self.assertEqual(
            pricing_root_assessment["decision"]["subtype"],
            "coverage_gap_search",
        )
        self.assertEqual(
            pricing_root_assessment["stage_contract"]["search_stage"],
            "focused",
        )
        self.assertTrue(
            pricing_root_assessment["stage_contract"]["produces_evidence"],
        )
        self.assertTrue(pricing_root_assessment["selected_follow_up_specs"])
        self.assertTrue(
            any(
                task.get("generated_from_gap") == "missing_guiding_question"
                and task.get("decision_action") == "source_discovery"
                and task.get("decision_subtype") == "coverage_gap_search"
                for task in result["research_tasks"]
            )
        )
        self.assertTrue(
            any(
                assessment["next_action"] == "ready_for_analysis"
                for assessment in result["coverage_assessments"][1:]
            )
        )
        self.assertTrue(
            any(
                "packaging details" in evidence.get("excerpt", "")
                for evidence in result["evidence_items"]
            )
        )

    def test_collection_uses_focused_for_all_planned_industry_extensions(self):
        branches = CollectionAgent()._build_root_branches(
            query="Compare Acme",
            competitors=[{"name": "Acme"}],
            active_schema={
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {
                        "id": "market_growth",
                        "name": "市场增长",
                        "description": "市场规模、增长速度、需求变化和商业机会。",
                        "source_hints": ["official_site", "news"],
                    },
                    {
                        "id": "competitive_moat",
                        "name": "竞争壁垒",
                        "description": "护城河、替代风险、迁移成本、生态依赖、品牌资产和长期优势。",
                        "source_hints": ["official_site", "review"],
                    },
                ],
            },
        )

        self.assertEqual(
            {branch["dimension_id"]: branch["search_stage"] for branch in branches},
            {
                "competitor_profile": "focused",
                "market_growth": "focused",
                "competitive_moat": "focused",
            },
        )

    def test_claim_support_review_does_not_generate_verification_by_default(self):
        state = {
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "pricing_business_model",
                    "branch_id": "collect_acme_pricing_business_model",
                    "claim": "Acme publishes enterprise pricing with public packaging.",
                    "competitors": ["Acme"],
                    "evidence_ids": [],
                    "confidence": 0.6,
                }
            ],
            "evidence_items": [],
            "messages": [],
            "verification_rounds": 0,
        }

        result = ClaimSupportReviewer().review(state)

        self.assertEqual(
            result["claim_support_reviews"][0]["support_status"],
            "unverifiable",
        )
        self.assertEqual(result["verification_task_queue"], [])
        self.assertFalse(
            result["agent_events"][-1]["input"]["verification_enabled"],
        )

    def test_claim_support_review_can_generate_verification_when_enabled(self):
        state = {
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "pricing_business_model",
                    "branch_id": "collect_acme_pricing_business_model",
                    "claim": "Acme publishes enterprise pricing with public packaging.",
                    "competitors": ["Acme"],
                    "evidence_ids": [],
                    "confidence": 0.6,
                }
            ],
            "evidence_items": [],
            "messages": [],
            "verification_rounds": 0,
        }

        result = ClaimSupportReviewer(enable_verification=True).review(state)

        self.assertEqual(
            result["claim_support_reviews"][0]["support_status"],
            "unverifiable",
        )
        self.assertEqual(
            result["verification_task_queue"][0]["search_stage"],
            "verification",
        )
        self.assertEqual(
            result["verification_task_queue"][0]["generated_from_gap"],
            "verification:claim_1",
        )
        self.assertEqual(
            result["verification_task_queue"][0]["decision_action"],
            "claim_verification",
        )
        self.assertEqual(
            result["verification_task_queue"][0]["decision_subtype"],
            "evidence_check",
        )
        self.assertTrue(
            result["agent_events"][-1]["input"]["verification_enabled"],
        )

    def test_claim_support_review_merges_prioritizes_and_caps_verification_tasks(self):
        reviewer = ClaimSupportReviewer(enable_verification=True, max_verification_tasks=2)

        def fake_support_status(claim_text, evidence_items, base_confidence):
            if "contradicted" in claim_text:
                return "contradicted", ["contradicted"], "Contradicted.", 0.2
            if "unverifiable" in claim_text:
                return "unverifiable", ["missing"], "Missing evidence.", 0.3
            return "weak", ["weak"], "Weak evidence.", 0.4

        reviewer._support_status = fake_support_status
        state = {
            "analysis_claims": [
                {
                    "id": "claim_contradicted",
                    "dimension": "pricing_model",
                    "branch_id": "branch_1",
                    "claim": "contradicted pricing claim",
                    "competitors": ["Acme"],
                    "evidence_ids": [],
                },
                {
                    "id": "claim_unverifiable_1",
                    "dimension": "security_compliance",
                    "branch_id": "branch_2",
                    "claim": "unverifiable security claim",
                    "competitors": ["Acme"],
                    "evidence_ids": [],
                },
                {
                    "id": "claim_unverifiable_2",
                    "dimension": "security_compliance",
                    "branch_id": "branch_3",
                    "claim": "unverifiable admin claim",
                    "competitors": ["Acme"],
                    "evidence_ids": [],
                },
                {
                    "id": "claim_weak",
                    "dimension": "user_personas",
                    "branch_id": "branch_4",
                    "claim": "weak persona claim",
                    "competitors": ["Acme"],
                    "evidence_ids": [],
                },
            ],
            "evidence_items": [],
            "messages": [],
            "verification_rounds": 0,
        }

        result = reviewer.review(state)
        queue = result["verification_task_queue"]

        self.assertEqual(len(queue), 2)
        self.assertEqual(queue[0]["support_statuses"], ["contradicted"])
        self.assertEqual(queue[1]["support_statuses"], ["unverifiable"])
        self.assertEqual(
            sorted(queue[1]["claim_ids"]),
            ["claim_unverifiable_1", "claim_unverifiable_2"],
        )
        self.assertEqual(queue[1]["merged_claim_count"], 2)
        self.assertNotIn("claim_weak", {claim_id for task in queue for claim_id in task["claim_ids"]})
        self.assertEqual(
            result["agent_events"][-1]["output"]["verification_task_candidate_count"],
            4,
        )

    def test_claim_support_review_supports_chinese_claims_with_chinese_evidence(self):
        state = {
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "strategic_positioning",
                    "branch_id": "collect_taobao_strategic_positioning",
                    "claim": "淘宝是面向消费者和商家的综合电商平台。",
                    "competitors": ["淘宝"],
                    "evidence_ids": ["ev_1"],
                    "confidence": 0.82,
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "淘宝",
                    "title": "淘宝官网",
                    "url": "https://www.taobao.com",
                    "excerpt": "淘宝是面向消费者和商家的综合电商平台。",
                }
            ],
            "messages": [],
            "verification_rounds": 0,
        }

        result = ClaimSupportReviewer().review(state)

        self.assertEqual(
            result["claim_support_reviews"][0]["support_status"],
            "supported",
        )
        self.assertEqual(result["verification_task_queue"], [])

    def test_collection_processes_verification_queue_without_rebuilding_roots(self):
        seen_tasks = []

        class FakeVerificationCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                seen_tasks.append(
                    {
                        "task": dict(collection_task),
                        "mode": getattr(mode, "value", mode),
                        "source_urls": source_urls or [],
                    }
                )
                return {
                    "task": dict(collection_task),
                    "mode": "standard_evidence",
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [
                        {
                            "competitor": "Acme",
                            "dimension_id": "pricing_business_model",
                            "title": "Acme enterprise pricing",
                            "url": "https://acme.example/pricing",
                            "source_type": "pricing_page",
                            "excerpt": "Acme describes enterprise pricing and packaging.",
                            "confidence": 0.9,
                        }
                    ],
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme pricing",
                "competitors": [{"name": "Acme"}],
                "verbose": False,
            },
            "active_knowledge_schema": {
                "selected_industry": {"name": "Productivity SaaS"},
                "industry_extensions": [
                    {
                        "id": "pricing_business_model",
                        "name": "定价与商业模式",
                        "source_hints": ["pricing_page"],
                    }
                ],
            },
            "verification_task_queue": [
                {
                    "objective": "Verify claim: Acme enterprise pricing",
                    "query": "Acme enterprise pricing packaging",
                    "target_source_types": ["pricing_page"],
                    "generated_from_gap": "verification:claim_1",
                    "reason": "Claim support review requested verification.",
                    "search_stage": "verification",
                    "competitor": "Acme",
                    "dimension_id": "pricing_business_model",
                    "parent_branch_id": "collect_acme_pricing_business_model",
                }
            ],
            "verification_rounds": 0,
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=FakeVerificationCollector(),
                max_branch_depth=0,
            ).run(state)
        )

        self.assertEqual(seen_tasks[0]["task"]["search_stage"], "verification")
        self.assertEqual(seen_tasks[0]["mode"], "standard_evidence")
        self.assertEqual(seen_tasks[0]["source_urls"], [])
        self.assertEqual(result["research_tasks"][0]["search_stage"], "verification")
        self.assertEqual(result["research_tasks"][0]["decision_action"], "claim_verification")
        self.assertEqual(result["research_tasks"][0]["decision_subtype"], "evidence_check")
        self.assertEqual(
            result["coverage_assessments"][0]["stage_contract"]["search_stage"],
            "verification",
        )
        self.assertEqual(
            result["coverage_assessments"][0]["stage_contract"]["stage_role"],
            "claim_verification",
        )
        self.assertEqual(
            result["research_tasks"][0]["generated_from_gap"],
            "verification:claim_1",
        )
        self.assertEqual(result["verification_rounds"], 1)
        self.assertEqual(result["verification_task_queue"], [])
        self.assertEqual(len(result["research_branches"]), 1)

    def test_collection_limits_verification_concurrency(self):
        active_count = 0
        max_seen_active = 0

        class SlowVerificationCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                nonlocal active_count, max_seen_active
                active_count += 1
                max_seen_active = max(max_seen_active, active_count)
                await asyncio.sleep(0.01)
                active_count -= 1
                return {
                    "task": dict(collection_task),
                    "mode": "standard_evidence",
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [
                        {
                            "competitor": "Acme",
                            "dimension_id": collection_task["dimension_id"],
                            "title": "Acme evidence",
                            "url": "https://acme.example/evidence",
                            "source_type": "official_site",
                            "excerpt": "Acme evidence.",
                            "confidence": 0.9,
                        }
                    ],
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme",
                "competitors": [{"name": "Acme"}],
                "verbose": False,
            },
            "active_knowledge_schema": {"industry_extensions": []},
            "verification_task_queue": [
                {
                    "objective": f"Verify claim {index}",
                    "query": f"Acme verification {index}",
                    "target_source_types": ["official_site"],
                    "generated_from_gap": f"verification:claim_{index}",
                    "reason": "Claim support review requested verification.",
                    "search_stage": "verification",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "parent_branch_id": "collect_acme_pricing_model",
                }
                for index in range(5)
            ],
            "verification_rounds": 0,
            "messages": [],
        }

        asyncio.run(
            CollectionAgent(
                evidence_collector=SlowVerificationCollector(),
                max_branch_depth=0,
                max_verification_concurrency=2,
            ).run(state)
        )

        self.assertLessEqual(max_seen_active, 2)

    def test_evidence_item_uses_query_relevant_chunk(self):
        irrelevant_intro = "General company overview. " * 80
        pricing_signal = (
            "Acme pricing includes a starter plan, enterprise billing, "
            "and public package details for buyer comparison. "
        )
        trailing = "Unrelated footer navigation. " * 20

        evidence = ResearchEngineEvidenceCollector()._to_evidence_items(
            collection_task={
                "id": "collect_acme_pricing_model",
                "branch_id": "collect_acme_pricing_model",
                "competitor": "Acme",
                "dimension_id": "pricing_model",
                "dimension_name": "Pricing Model",
                "query": "Compare Acme pricing model starter plan enterprise billing",
            },
            sources=[
                {
                    "title": "Acme overview",
                    "url": "https://acme.example/overview",
                    "raw_content": irrelevant_intro + pricing_signal + trailing,
                }
            ],
        )[0]

        self.assertIn("starter plan", evidence["excerpt"])
        self.assertNotIn("summary", evidence)
        self.assertNotEqual(
            evidence["excerpt"],
            (irrelevant_intro + pricing_signal + trailing)[:1000],
        )

    def test_evidence_collector_infers_priority_source_metadata(self):
        collector = ResearchEngineEvidenceCollector()
        task = {
            "id": "collect_acme_safety",
            "branch_id": "collect_acme_safety",
            "competitor": "Acme",
            "dimension_id": "safety_recalls",
            "dimension_name": "Safety Recalls",
        }

        evidence = collector._to_evidence_items(
            task,
            [
                {
                    "title": "NHTSA recalls database",
                    "url": "https://www.nhtsa.gov/recalls",
                    "content": "Recall and safety campaign records.",
                }
            ],
        )[0]

        self.assertEqual(evidence["source_type"], "regulator_database")
        self.assertEqual(
            evidence["source_priority"],
            SOURCE_TYPE_PRIORITY["regulator_database"],
        )
        self.assertTrue(evidence["is_primary_source"])

    def test_evidence_collector_repairs_utf8_mojibake(self):
        collector = ResearchEngineEvidenceCollector()
        mojibake_title = "淘宝官网".encode("utf-8").decode("latin-1")
        mojibake_content = "钉钉的钉盘有哪些功能".encode("utf-8").decode("latin-1")

        evidence = collector._to_evidence_items(
            {
                "id": "collect_dingtalk_features",
                "branch_id": "collect_dingtalk_features",
                "competitor": "钉钉",
                "dimension_id": "product_features",
                "dimension_name": "产品功能",
                "query": "钉钉的钉盘有哪些功能",
            },
            [
                {
                    "title": mojibake_title,
                    "url": "https://example.com/dingtalk",
                    "raw_content": mojibake_content,
                }
            ],
        )[0]

        self.assertEqual(evidence["title"], "淘宝官网")
        self.assertIn("钉钉的钉盘有哪些功能", evidence["excerpt"])

    def test_evidence_review_rejects_unrecoverable_garbled_text(self):
        review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            pricing_branch(),
            [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "https://acme.example/pricing",
                    "title": "Acme pricing",
                    "excerpt": "��ࡱ�����������������>���� ������������",
                    "source_type": "pricing_page",
                }
            ],
        )

        self.assertFalse(review["accepted"])
        self.assertEqual(review["accepted_evidence_ids"], [])
        self.assertEqual(review["rejected_evidence_ids"], ["ev_1"])
        self.assertEqual(review["required_action"], "retry")
        self.assertIn(
            "low_quality_text",
            {finding["code"] for finding in review["findings"]},
        )

    def test_evidence_review_accepts_url_backed_branch_evidence(self):
        review = EvidenceQualityReviewer(min_sources_per_branch=2).review(
            pricing_branch(),
            [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "https://acme.example/pricing",
                    "source_type": "pricing_page",
                },
                {
                    "id": "ev_2",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "https://docs.acme.example/plans",
                    "source_type": "docs",
                },
            ],
        )

        self.assertTrue(review["accepted"])
        self.assertEqual(review["required_action"], "accept")
        self.assertEqual(review["accepted_evidence_ids"], ["ev_1", "ev_2"])
        self.assertEqual(review["rejected_evidence_ids"], [])

    def test_evidence_review_requests_retry_for_missing_urls(self):
        review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            pricing_branch(),
            [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "",
                    "source_type": "pricing_page",
                }
            ],
        )

        self.assertFalse(review["accepted"])
        self.assertEqual(review["required_action"], "retry")
        self.assertEqual(review["accepted_evidence_ids"], [])
        self.assertEqual(review["rejected_evidence_ids"], ["ev_1"])

    def test_evidence_review_rejects_sources_that_miss_success_criteria(self):
        branch = {
            **pricing_branch(),
            "success_criteria": [
                {
                    "id": "pricing_details",
                    "description": "Find source-backed pricing evidence for Acme.",
                    "target_source_types": ["pricing_page"],
                    "kind": "success_criterion",
                }
            ],
        }

        review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "https://acme.example/careers",
                    "title": "Acme careers",
                    "excerpt": "Acme is hiring sales engineers.",
                    "source_type": "job_posting",
                }
            ],
        )

        self.assertEqual(review["accepted_evidence_ids"], [])
        self.assertEqual(review["rejected_evidence_ids"], ["ev_1"])
        self.assertEqual(review["required_action"], "retry")
        self.assertIn(
            "no_success_criterion_match",
            {finding["code"] for finding in review["findings"]},
        )

    def test_evidence_review_matches_chinese_criteria_to_english_dimension_evidence(self):
        branch = {
            **pricing_branch(),
            "dimension_name": "定价与商业模式",
            "success_criteria": [
                {
                    "id": "pricing_details",
                    "description": "价格、套餐和计费单位是否有公开信息？",
                    "target_source_types": ["pricing_page"],
                    "kind": "guiding_question",
                }
            ],
        }

        review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "https://acme.example/blog/pricing-update",
                    "title": "Acme pricing plans",
                    "excerpt": "Acme describes public pricing plans and billing options.",
                    "source_type": "news",
                }
            ],
        )

        self.assertEqual(review["accepted_evidence_ids"], ["ev_1"])
        self.assertEqual(review["rejected_evidence_ids"], [])
        self.assertNotIn(
            "no_success_criterion_match",
            {finding["code"] for finding in review["findings"]},
        )

    def test_coverage_review_refines_query_after_source_retry(self):
        branch = pricing_branch()
        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "",
                    "source_type": "pricing_page",
                }
            ],
        )

        assessment = CoverageReviewer().review(
            branch=branch,
            evidence_items=[
                {
                    "id": "ev_1",
                    "collection_task_id": branch["id"],
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "url": "",
                    "source_type": "pricing_page",
                }
            ],
            evidence_review=evidence_review,
        )

        self.assertEqual(assessment["next_action"], "refine_query")
        self.assertEqual(assessment["accepted_evidence_ids"], [])
        self.assertTrue(assessment["follow_up_task_specs"])
        self.assertEqual(
            assessment["follow_up_task_specs"][0]["generated_from_gap"],
            "retry_source_quality",
        )
        self.assertEqual(
            assessment["follow_up_task_specs"][0]["decision_action"],
            "scope_refinement",
        )
        self.assertEqual(
            assessment["follow_up_task_specs"][0]["decision_subtype"],
            "query_refinement",
        )
        self.assertEqual(assessment["decision"]["action"], "scope_refinement")
        self.assertEqual(assessment["decision"]["subtype"], "query_refinement")
        self.assertEqual(
            assessment["selected_follow_up_specs"],
            assessment["follow_up_task_specs"],
        )

    def test_coverage_review_generates_follow_up_after_competitor_mismatch(self):
        branch = pricing_branch()
        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            [
                {
                    "id": "ev_1",
                    "collection_task_id": branch["id"],
                    "competitor": "OtherCo",
                    "dimension_id": "pricing_model",
                    "url": "https://other.example/pricing",
                    "source_type": "pricing_page",
                }
            ],
        )

        assessment = CoverageReviewer().review(
            branch=branch,
            evidence_items=[
                {
                    "id": "ev_1",
                    "collection_task_id": branch["id"],
                    "competitor": "OtherCo",
                    "dimension_id": "pricing_model",
                    "url": "https://other.example/pricing",
                    "source_type": "pricing_page",
                }
            ],
            evidence_review=evidence_review,
        )

        self.assertEqual(evidence_review["required_action"], "retry")
        self.assertEqual(assessment["next_action"], "refine_query")
        self.assertTrue(assessment["follow_up_task_specs"])
        self.assertEqual(assessment["decision"]["action"], "entity_resolution")
        self.assertEqual(
            assessment["decision"]["subtype"],
            "competitor_disambiguation",
        )
        self.assertEqual(
            assessment["selected_follow_up_specs"][0]["decision_action"],
            "entity_resolution",
        )
        self.assertEqual(
            assessment["selected_follow_up_specs"][0]["decision_subtype"],
            "competitor_disambiguation",
        )

    def test_coverage_review_keeps_partial_evidence_and_targets_missing_criteria(self):
        branch = {
            **pricing_branch(),
            "success_criteria": [
                {
                    "id": "public_pricing",
                    "description": "What public starter pricing and billing terms are available?",
                    "target_source_types": ["pricing_page"],
                    "kind": "success_criterion",
                },
                {
                    "id": "enterprise_packaging",
                    "description": "What enterprise packaging details are public?",
                    "target_source_types": ["pricing_page"],
                    "kind": "guiding_question",
                },
            ],
            "guiding_questions": ["What enterprise packaging details are public?"],
        }
        evidence = [
            {
                "id": "ev_1",
                "collection_task_id": branch["id"],
                "competitor": "Acme",
                "dimension_id": "pricing_model",
                "title": "Acme pricing",
                "url": "https://acme.example/pricing",
                "source_type": "pricing_page",
                "excerpt": "Acme lists public starter pricing and billing terms.",
            }
        ]
        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            evidence,
        )

        assessment = CoverageReviewer().review(
            branch=branch,
            evidence_items=evidence,
            evidence_review=evidence_review,
        )

        self.assertEqual(evidence_review["accepted_evidence_ids"], ["ev_1"])
        self.assertEqual(assessment["accepted_evidence_ids"], ["ev_1"])
        self.assertEqual(
            [criterion["id"] for criterion in assessment["satisfied_criteria"]],
            ["public_pricing"],
        )
        self.assertEqual(
            [criterion["id"] for criterion in assessment["missing_criteria"]],
            ["enterprise_packaging"],
        )
        self.assertEqual(
            assessment["selected_follow_up_specs"][0]["generated_from_gap"],
            "missing_guiding_question",
        )
        self.assertEqual(
            assessment["selected_follow_up_specs"][0]["success_criteria"][0]["id"],
            "enterprise_packaging",
        )

    def test_coverage_review_uses_dimension_policy_guiding_questions(self):
        branch = {
            "id": "collect_acme_pricing_business_model",
            "depth": 0,
            "competitor": "Acme",
            "dimension_id": "pricing_business_model",
            "dimension_name": "定价与商业模式",
            "topic": "定价与商业模式",
            "guiding_questions": [],
        }
        evidence = [
            {
                "id": "ev_1",
                "collection_task_id": branch["id"],
                "competitor": "Acme",
                "dimension_id": "pricing_business_model",
                "title": "Acme funding news",
                "url": "https://news.example/acme-funding",
                "source_type": "news",
                "excerpt": "Acme announced new funding but did not discuss public pricing.",
            }
        ]
        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            evidence,
        )

        assessment = CoverageReviewer().review(
            branch=branch,
            evidence_items=evidence,
            evidence_review=evidence_review,
        )

        self.assertTrue(assessment["missing_questions"])
        self.assertTrue(
            any(
                spec["generated_from_gap"] == "missing_guiding_question"
                for spec in assessment["follow_up_task_specs"]
            )
        )

    def test_coverage_review_does_not_treat_source_hints_as_required_sources(self):
        branch = {
            "id": "collect_acme_direction_pricing_packaging",
            "depth": 0,
            "competitor": "Acme",
            "dimension_id": "direction_pricing_packaging",
            "dimension_name": "定价与套餐分层",
            "topic": "定价与套餐分层",
            "source_hints": ["pricing_page", "official_site"],
            "guiding_questions": [],
        }
        evidence = [
            {
                "id": "ev_1",
                "collection_task_id": branch["id"],
                "competitor": "Acme",
                "dimension_id": "direction_pricing_packaging",
                "title": "Acme market note",
                "url": "https://news.example/acme-pricing",
                "source_type": "news",
                "excerpt": "Acme pricing is mentioned in a market note.",
            }
        ]
        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            evidence,
        )

        assessment = CoverageReviewer().review(
            branch=branch,
            evidence_items=evidence,
            evidence_review=evidence_review,
        )

        self.assertEqual(assessment["next_action"], "ready_for_analysis")

    def test_coverage_review_generates_guiding_question_follow_up(self):
        branch = {
            "id": "collect_acme_customer_proof",
            "depth": 0,
            "competitor": "Acme",
            "dimension_id": "customer_proof",
            "dimension_name": "客户证明",
            "topic": "客户证明",
            "guiding_questions": ["What reviews mention onboarding pain?"],
        }
        evidence = [
            {
                "id": "ev_1",
                "collection_task_id": branch["id"],
                "competitor": "Acme",
                "dimension_id": "customer_proof",
                "title": "Acme customers",
                "url": "https://acme.example/customers",
                "source_type": "official_site",
                "excerpt": "Acme lists customer logos and enterprise adoption.",
            }
        ]
        evidence_review = EvidenceQualityReviewer(min_sources_per_branch=1).review(
            branch,
            evidence,
        )

        assessment = CoverageReviewer().review(
            branch=branch,
            evidence_items=evidence,
            evidence_review=evidence_review,
        )

        self.assertIn("What reviews mention onboarding pain?", assessment["missing_questions"])
        self.assertTrue(
            any(
                spec["generated_from_gap"] == "missing_guiding_question"
                and "Guiding question to answer" in spec["query"]
                for spec in assessment["follow_up_task_specs"]
            )
        )

    def test_knowledge_structuring_uses_only_accepted_evidence(self):
        state = {
            "active_knowledge_schema": {"id": "schema_1"},
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "title": "Acme pricing",
                    "excerpt": "Acme pricing starts with a public plan.",
                    "source_type": "pricing_page",
                    "confidence": 0.8,
                },
                {
                    "id": "ev_2",
                    "competitor": "Acme",
                    "title": "Rejected scrape",
                    "excerpt": "This should not enter knowledge.",
                    "source_type": "other",
                    "confidence": 0.8,
                },
            ],
            "evidence_reviews": [
                {
                    "accepted_evidence_ids": ["ev_1"],
                    "rejected_evidence_ids": ["ev_2"],
                }
            ],
            "messages": [],
        }

        result = asyncio.run(KnowledgeStructuringAgent().run(state))
        knowledge = result["competitor_knowledge"][0]

        self.assertEqual(knowledge["evidence_ids"], ["ev_1"])
        serialized = str(knowledge)
        self.assertIn("Acme pricing", serialized)
        self.assertNotIn("Rejected scrape", serialized)

    def test_knowledge_structuring_skips_unreadable_feature_text(self):
        state = {
            "active_knowledge_schema": {"id": "schema_1"},
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "product_features",
                    "dimension_name": "产品功能",
                    "title": "Broken scrape",
                    "excerpt": "��ࡱ�����������������>���� ������������",
                    "source_type": "docs",
                    "confidence": 0.8,
                }
            ],
            "evidence_reviews": [{"accepted_evidence_ids": ["ev_1"]}],
            "messages": [],
        }

        result = asyncio.run(KnowledgeStructuringAgent().run(state))
        knowledge = result["competitor_knowledge"][0]

        self.assertEqual(knowledge["feature_tree"], [])
        self.assertNotIn("��ࡱ", str(knowledge))

    def test_analysis_uses_quality_accepted_branch_evidence(self):
        state = {
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Acme pricing",
                    "excerpt": "Acme publishes a starter pricing plan.",
                    "confidence": 0.8,
                },
                {
                    "id": "ev_2",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Rejected scrape",
                    "excerpt": "This should not become a claim.",
                    "confidence": 0.9,
                },
            ],
            "research_branches": [pricing_branch()],
            "evidence_reviews": [
                {
                    "id": "ev_review_collect_acme_pricing_model",
                    "branch_id": "collect_acme_pricing_model",
                    "accepted": True,
                    "score": 0.9,
                    "accepted_evidence_ids": ["ev_1"],
                    "rejected_evidence_ids": ["ev_2"],
                    "required_action": "accept",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(AnalysisAgent().run(state))
        claim = result["analysis_claims"][0]

        self.assertEqual(claim["branch_id"], "collect_acme_pricing_model")
        self.assertEqual(claim["evidence_review_id"], "ev_review_collect_acme_pricing_model")
        self.assertEqual(claim["evidence_ids"], ["ev_1"])
        self.assertIn("Acme Pricing Model:", claim["claim"])
        self.assertIn("Acme publishes a starter pricing plan", claim["claim"])
        self.assertNotIn("Rejected scrape", claim["claim"])

    def test_analysis_keeps_partial_accepted_evidence_from_expand_reviews(self):
        state = {
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Beta",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Beta pricing note",
                    "excerpt": "Beta describes public pricing but still needs official page verification.",
                    "confidence": 0.7,
                }
            ],
            "research_branches": [
                {
                    "id": "collect_beta_pricing_model",
                    "competitor": "Beta",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                }
            ],
            "evidence_reviews": [
                {
                    "id": "ev_review_collect_beta_pricing_model",
                    "branch_id": "collect_beta_pricing_model",
                    "accepted": False,
                    "score": 0.64,
                    "accepted_evidence_ids": ["ev_1"],
                    "rejected_evidence_ids": [],
                    "required_action": "expand",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(AnalysisAgent().run(state))

        self.assertEqual(len(result["analysis_claims"]), 1)
        self.assertEqual(result["analysis_claims"][0]["competitors"], ["Beta"])
        self.assertEqual(result["analysis_claims"][0]["evidence_ids"], ["ev_1"])

    def test_analysis_repairs_mojibake_and_skips_unreadable_claim_text(self):
        mojibake_excerpt = "飞书核心功能说明".encode("utf-8").decode("latin-1")
        state = {
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "飞书",
                    "dimension_id": "product_features",
                    "dimension_name": "产品功能",
                    "title": "飞书功能",
                    "excerpt": mojibake_excerpt,
                    "confidence": 0.8,
                },
                {
                    "id": "ev_2",
                    "competitor": "飞书",
                    "dimension_id": "product_features",
                    "dimension_name": "产品功能",
                    "title": "Broken scrape",
                    "excerpt": "��ࡱ�����������������>���� ������������",
                    "confidence": 0.8,
                },
            ],
            "research_branches": [
                {
                    "id": "collect_feishu_product_features",
                    "competitor": "飞书",
                    "dimension_id": "product_features",
                    "dimension_name": "产品功能",
                }
            ],
            "evidence_reviews": [
                {
                    "id": "ev_review_collect_feishu_product_features",
                    "branch_id": "collect_feishu_product_features",
                    "accepted": True,
                    "score": 0.9,
                    "accepted_evidence_ids": ["ev_1", "ev_2"],
                    "required_action": "accept",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(AnalysisAgent().run(state))
        claims = result["analysis_claims"]

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["evidence_ids"], ["ev_1"])
        self.assertIn("飞书核心功能说明", claims[0]["claim"])
        self.assertNotIn("��ࡱ", claims[0]["claim"])

    def test_analysis_skips_low_quality_feature_claims_from_knowledge(self):
        state = {
            "competitor_knowledge": [
                {
                    "competitor": "飞书",
                    "feature_tree": [
                        {
                            "category": "core_feature",
                            "description": "��ࡱ�����������������>���� ������������",
                            "evidence_ids": ["ev_1"],
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
            "messages": [],
        }

        result = asyncio.run(AnalysisAgent().run(state))

        self.assertEqual(result["analysis_claims"], [])

    def test_analysis_emits_multiple_atomic_claims_per_dimension(self):
        state = {
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Starter plan",
                    "excerpt": "Acme publishes a starter pricing plan.",
                    "confidence": 0.8,
                },
                {
                    "id": "ev_2",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Enterprise contact",
                    "excerpt": "Acme directs enterprise pricing inquiries to sales.",
                    "confidence": 0.7,
                },
            ],
            "research_branches": [pricing_branch()],
            "evidence_reviews": [
                {
                    "id": "ev_review_collect_acme_pricing_model",
                    "branch_id": "collect_acme_pricing_model",
                    "accepted": True,
                    "score": 0.9,
                    "accepted_evidence_ids": ["ev_1", "ev_2"],
                    "rejected_evidence_ids": [],
                    "required_action": "accept",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(AnalysisAgent().run(state))
        claims = result["analysis_claims"]

        self.assertEqual(len(claims), 2)
        self.assertEqual([claim["dimension"] for claim in claims], ["pricing_model", "pricing_model"])
        self.assertEqual([claim["evidence_ids"] for claim in claims], [["ev_1"], ["ev_2"]])
        self.assertIn("starter pricing plan", claims[0]["claim"])
        self.assertNotIn("enterprise pricing", claims[0]["claim"])
        self.assertIn("enterprise pricing inquiries", claims[1]["claim"])
        self.assertNotIn("starter pricing plan", claims[1]["claim"])
        self.assertEqual(result["messages"][-1]["evidence_ids"], ["ev_1", "ev_2"])
        self.assertEqual(
            result["agent_events"][-1]["output"]["claim_granularity"],
            "accepted_evidence_cluster",
        )

    def test_analysis_merges_multiple_evidence_items_for_same_atomic_claim(self):
        state = {
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Acme pricing page",
                    "excerpt": "Acme publishes a starter pricing plan.",
                    "confidence": 0.8,
                },
                {
                    "id": "ev_2",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Acme help center",
                    "excerpt": "Acme publishes a starter pricing plan on its pricing page.",
                    "confidence": 0.7,
                },
            ],
            "research_branches": [pricing_branch()],
            "evidence_reviews": [
                {
                    "id": "ev_review_collect_acme_pricing_model",
                    "branch_id": "collect_acme_pricing_model",
                    "accepted": True,
                    "score": 0.9,
                    "accepted_evidence_ids": ["ev_1", "ev_2"],
                    "rejected_evidence_ids": [],
                    "required_action": "accept",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(AnalysisAgent().run(state))
        claims = result["analysis_claims"]

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["dimension"], "pricing_model")
        self.assertEqual(claims[0]["evidence_ids"], ["ev_1", "ev_2"])
        self.assertIn("starter pricing plan", claims[0]["claim"])
        self.assertIn("2 EvidenceItem", claims[0]["reasoning"])

    def test_writer_uses_report_generator_with_traceable_evidence_context(self):
        created_researchers = []

        class FakeReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher
                created_researchers.append(researcher)

            async def write_report(self, **kwargs):
                self.researcher.add_costs(0.25)
                context = self.researcher.context
                if "Only write chapters one and two" in context:
                    return "\n".join(
                        [
                            "# 竞品分析报告",
                            "",
                            "## 第一章：分析目的",
                            "本次分析围绕 Compare Acme pricing 展开。",
                            "",
                            "## 第二章：确定竞品",
                            "### 竞品信息卡片",
                            "- **Acme**：公开资料显示其定价信息可复核。[1]",
                            "",
                            "### 竞品分类表格",
                            "| 竞品 | 产品/品牌 | 分类 | 官网 | 备注 | 主要引用 |",
                            "| --- | --- | --- | --- | --- | --- |",
                            "| Acme | Acme | 公开资料不足 | https://acme.example/pricing | 定价页 | [1] |",
                        ]
                    )
                if "Only write chapter four" in context:
                    return "\n".join(
                        [
                            "## 第四章：总结",
                            "### SWOT 分析矩阵",
                            "| 类型 | 内容 | 引用 |",
                            "| --- | --- | --- |",
                            "| Strengths 优势 | Acme 的公开定价页提供可复核入口。 | [1] |",
                            "",
                            "### 总结论述",
                            "Acme pricing 的主要差异需要围绕公开定价页继续复核。",
                        ]
                    )
                if "Only write the dynamic analysis overview table" in context:
                    return "\n".join(
                        [
                            "### 分析维度总览",
                            "",
                            "| 章节 | 动态维度 | 证据覆盖 | 主要竞品 | 主要引用 |",
                            "| --- | --- | --- | --- | --- |",
                            "| 3.1 pricing model | 定价模式公开信号 | 1 条可追溯 claim | Acme | [1] |",
                        ]
                    )
                if '"id": "pricing_model"' in context:
                    return "\n".join(
                        [
                            "| 竞品 | 结论 | 引用 |",
                            "| --- | --- | --- |",
                            "| Acme | Acme publishes a starter pricing plan. | [1] |",
                            "",
                            "分析：Acme publishes a starter pricing plan.",
                        ]
                    )
                return ""

        state = {
            "task": {"query": "Compare Acme pricing"},
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "pricing_model",
                    "claim": "Acme publishes a starter pricing plan.",
                    "evidence_ids": ["ev_1", "ev_2"],
                    "confidence": 0.9,
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "title": "Acme pricing",
                    "url": "https://acme.example/pricing",
                    "excerpt": "Acme publishes a starter pricing plan.",
                    "source_type": "pricing_page",
                    "confidence": 0.9,
                },
                {
                    "id": "ev_2",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "title": "Rejected scrape",
                    "url": "https://acme.example/rejected",
                    "excerpt": "This rejected source should not support the report.",
                    "source_type": "other",
                    "confidence": 0.4,
                },
            ],
            "evidence_reviews": [
                {
                    "accepted_evidence_ids": ["ev_1"],
                    "rejected_evidence_ids": ["ev_2"],
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=FakeReportGenerator).run(state)
        )

        self.assertEqual(len(created_researchers), 4)
        opening_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: opening" in researcher.query
        )
        pricing_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: analysis_pricing_model" in researcher.query
        )
        overview_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: analysis_overview" in researcher.query
        )
        summary_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: summary" in researcher.query
        )
        self.assertIn("第一章：分析目的", opening_researcher.custom_prompt)
        self.assertIn("分析维度总览", overview_researcher.custom_prompt)
        self.assertIn("pricing model", pricing_researcher.custom_prompt)
        self.assertIn("第四章：总结", summary_researcher.custom_prompt)
        self.assertIn("Acme publishes a starter pricing plan", pricing_researcher.context)
        self.assertNotIn("https://acme.example/pricing", pricing_researcher.context)
        self.assertNotIn("evidence_items", pricing_researcher.context)
        self.assertNotIn("product_analysis_checklist", pricing_researcher.context)
        for researcher in created_researchers:
            self.assertNotIn("profile_evidence_items", researcher.context)
            self.assertNotIn("evidence_items", researcher.context)
            self.assertNotIn("ev_2", researcher.context)
            self.assertNotIn("https://acme.example/rejected", researcher.context)
        self.assertIn("# 竞品分析报告", result["report"])
        self.assertIn("Acme publishes a starter pricing plan. [1]", result["report"])
        self.assertIn("## 第三章：竞品分析", result["report"])
        self.assertIn("### 分析维度总览", result["report"])
        self.assertNotIn("数据来源约束", result["report"])
        self.assertIn("| 3.1 | pricing model |", result["report"])
        self.assertIn("| 3.1 | pricing model | 1 条可追溯 claim", result["report"])
        self.assertIn("## 附录：信息索引表格", result["report"])
        self.assertIn("| 引用标号 | 信息 ID |", result["report"])
        self.assertIn("| [1] | ev_1 | claim_1 |", result["report"])
        self.assertIn("claim_1", result["report"])
        self.assertIn("ev_1", result["report"])
        self.assertNotIn("ev_2", result["report"])
        self.assertIn("https://acme.example/pricing", result["report"])
        self.assertNotIn("https://acme.example/rejected", result["report"])
        self.assertEqual(result["messages"][-1]["evidence_ids"], ["ev_1"])
        event = result["agent_events"][-1]
        self.assertEqual(event["input"]["segment_count"], 4)
        self.assertEqual(
            event["input"]["max_segment_context_length"],
            max(len(researcher.context) for researcher in created_researchers),
        )
        self.assertGreater(
            event["input"]["context_length"],
            event["input"]["max_segment_context_length"],
        )
        self.assertEqual(result["agent_events"][-1]["output"]["cost"], 1.0)

    def test_writer_compresses_segment_contexts_and_keeps_raw_evidence_out(self):
        created_researchers = []

        class EmptyReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher
                created_researchers.append(researcher)

            async def write_report(self, **kwargs):
                return ""

        long_claim = " ".join(["Acme has a pricing signal supported by reviewed claims."] * 900)
        raw_evidence_text = "RAW_EVIDENCE_SHOULD_NOT_BE_SENT " * 900
        state = {
            "task": {"query": "Compare Acme pricing"},
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "pricing_model",
                    "claim": long_claim,
                    "evidence_ids": ["ev_1"],
                    "reasoning": " ".join(["Long reasoning should be compressed."] * 400),
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "title": "Acme pricing",
                    "url": "https://acme.example/pricing",
                    "excerpt": raw_evidence_text,
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=EmptyReportGenerator).run(state)
        )

        opening_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: opening" in researcher.query
        )
        pricing_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: analysis_pricing_model" in researcher.query
        )
        overview_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: analysis_overview" in researcher.query
        )
        summary_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: summary" in researcher.query
        )
        self.assertLessEqual(len(opening_researcher.context), OPENING_CONTEXT_CHAR_LIMIT)
        self.assertLessEqual(len(overview_researcher.context), ANALYSIS_OVERVIEW_CONTEXT_CHAR_LIMIT)
        self.assertLessEqual(len(pricing_researcher.context), SECTION_CONTEXT_CHAR_LIMIT)
        self.assertLessEqual(len(summary_researcher.context), SUMMARY_CONTEXT_CHAR_LIMIT)
        for researcher in created_researchers:
            self.assertNotIn("evidence_items", researcher.context)
            self.assertNotIn("RAW_EVIDENCE_SHOULD_NOT_BE_SENT", researcher.context)
            self.assertNotIn("https://acme.example/pricing", researcher.context)
        self.assertIn("https://acme.example/pricing", result["report"])

    def test_writer_falls_back_to_traceable_markdown_when_generation_is_empty(self):
        class EmptyReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher

            async def write_report(self, **kwargs):
                return ""

        state = {
            "task": {"query": "Compare Acme pricing"},
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "claim": "Acme publishes a starter pricing plan.",
                    "evidence_ids": ["ev_1"],
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "title": "Acme pricing",
                    "url": "https://acme.example/pricing",
                    "excerpt": "Acme publishes a starter pricing plan.",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=EmptyReportGenerator).run(state)
        )

        self.assertIn("# 竞品分析报告", result["report"])
        self.assertIn("## 第一章：分析目的", result["report"])
        self.assertIn("## 第二章：确定竞品", result["report"])
        self.assertIn("## 第三章：竞品分析", result["report"])
        self.assertIn("### 分析维度总览", result["report"])
        self.assertIn("### 3.1 证据支持发现", result["report"])
        self.assertNotIn("| 章节 | 引导问题 |", result["report"])
        self.assertIn("## 第四章：总结", result["report"])
        self.assertIn("Acme publishes a starter pricing plan", result["report"])
        self.assertIn("[1]", result["report"])
        self.assertIn("## 附录：信息索引表格", result["report"])
        self.assertIn("https://acme.example/pricing", result["report"])

    def test_writer_replaces_noncompliant_generated_chapter_three(self):
        class NoncompliantReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher

            async def write_report(self, **kwargs):
                return "\n".join(
                    [
                        "# 竞品分析报告",
                        "",
                        "## 第三章：竞品分析",
                        "",
                        "### 3.1 Random Dimension",
                        "This chapter does not follow the product checklist.",
                        "",
                        "## 第四章：总结",
                        "Initial summary.",
                    ]
                )

        state = {
            "task": {"query": "Compare Acme pricing"},
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "pricing_model",
                    "claim": "Acme publishes a starter pricing plan.",
                    "evidence_ids": ["ev_1"],
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing Model",
                    "title": "Acme pricing",
                    "url": "https://acme.example/pricing",
                    "excerpt": "Acme publishes a starter pricing plan.",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=NoncompliantReportGenerator).run(state)
        )

        self.assertNotIn("Random Dimension", result["report"])
        self.assertIn("### 分析维度总览", result["report"])
        self.assertIn("| 3.1 | Pricing Model | 1 条可追溯 claim", result["report"])
        self.assertIn("### 3.1 Pricing Model", result["report"])
        self.assertNotIn("| 章节 | 引导问题 |", result["report"])
        self.assertIn("Acme publishes a starter pricing plan. [1]", result["report"])
        self.assertIn("## 第四章：总结", result["report"])

    def test_writer_replaces_weak_generated_overview_but_keeps_sections(self):
        agent = ReportWriterAgent()
        report = "\n".join(
            [
                "# 竞品分析报告",
                "",
                "## 第三章：竞品分析",
                "",
                "### 分析维度总览",
                "",
                "| 章节 | 动态维度 | 证据覆盖 | 主要竞品 | 主要引用 |",
                "| --- | --- | --- | --- | --- |",
                "| 3.1 | Security and compliance | 公开证据不足 | 飞书、钉钉 | 公开证据不足 |",
                "",
                "### 3.1 Security and compliance",
                "",
                "| 对比维度 | 飞书 | 钉钉 |",
                "| --- | --- | --- |",
                "| 内部安全管理机制 | 飞书有安全意识宣导。[1] | 钉钉有安全能力框架。[2] |",
                "",
                "分析：公开资料显示两款产品均有可追溯安全相关披露。[1][2]",
                "",
                "## 第四章：总结",
                "",
                "保留总结。",
            ]
        )
        claims = [
            {
                "id": "claim_1",
                "dimension": "security_compliance",
                "claim": "飞书公开资料显示其安全披露覆盖内部安全管理。",
                "competitors": ["飞书"],
                "evidence_ids": ["ev_1"],
            },
            {
                "id": "claim_2",
                "dimension": "security_compliance",
                "claim": "钉钉公开资料显示其安全披露覆盖安全能力框架。",
                "competitors": ["钉钉"],
                "evidence_ids": ["ev_2"],
            },
        ]
        evidence_items = [
            {
                "id": "ev_1",
                "competitor": "飞书",
                "dimension_id": "security_compliance",
                "dimension_name": "Security and compliance",
            },
            {
                "id": "ev_2",
                "competitor": "钉钉",
                "dimension_id": "security_compliance",
                "dimension_name": "Security and compliance",
            },
        ]

        fixed_report = agent._ensure_dynamic_analysis_chapter(
            report,
            claims,
            evidence_items,
            [],
        )

        self.assertIn(
            "| 3.1 | Security and compliance | 2 条可追溯 claim，2 项公开证据 | 飞书, 钉钉 | [1][2] |",
            fixed_report,
        )
        self.assertIn("| 内部安全管理机制 | 飞书有安全意识宣导。[1] | 钉钉有安全能力框架。[2] |", fixed_report)
        self.assertNotIn("| 3.1 | Security and compliance | 公开证据不足 |", fixed_report)

    def test_writer_fallback_uses_profile_fields_and_evidence_ids(self):
        class EmptyReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher

            async def write_report(self, **kwargs):
                return ""

        state = {
            "task": {"query": "对比淘宝、京东、拼多多"},
            "competitors": [
                {
                    "name": "淘宝",
                    "product": "淘宝",
                    "website": "https://www.taobao.com",
                    "category": "零售 / 电商",
                    "notes": "淘宝是面向消费者和商家的综合电商平台。",
                    "evidence_ids": ["ev_1"],
                }
            ],
            "analysis_claims": [],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "淘宝",
                    "dimension_id": "competitor_profile",
                    "dimension_name": "竞品基础信息",
                    "title": "淘宝官网",
                    "url": "https://www.taobao.com",
                    "excerpt": "淘宝是面向消费者和商家的综合电商平台。",
                    "source_type": "official_site",
                }
            ],
            "evidence_reviews": [{"accepted_evidence_ids": ["ev_1"]}],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=EmptyReportGenerator).run(state)
        )

        self.assertIn("官网：https://www.taobao.com", result["report"])
        self.assertIn("主要引用：[1]", result["report"])
        self.assertIn("| 淘宝 | 淘宝 | 零售 / 电商 | https://www.taobao.com", result["report"])
        self.assertIn("ev_1", result["report"])

    def test_writer_uses_competitor_website_without_report_time_domain_validation(self):
        agent = ReportWriterAgent()
        state = {
            "task": {
                "query": "对比钉钉和企业微信",
                "competitors": [
                    {
                        "name": "钉钉",
                        "product": "钉钉",
                        "website": "https://work.weixin.qq.com",
                    }
                ],
            },
            "competitors": [
                {
                    "name": "钉钉",
                    "product": "DingTalk",
                    "website": "https://work.weixin.qq.com",
                    "category": "协同办公",
                    "notes": "企业协同办公产品",
                    "evidence_ids": ["ev_1"],
                }
            ],
            "messages": [],
        }

        opening_context = agent._build_opening_context(state, {"ev_1": "[1]"})
        opening_fallback = agent._fallback_opening_chapters(state, {"ev_1": "[1]"})
        report_fallback = agent._fallback_report(state, [], [], [])

        self.assertIn("work.weixin.qq.com", opening_context)
        self.assertIn("官网：https://work.weixin.qq.com", opening_fallback)
        self.assertIn("| 钉钉 | DingTalk | 协同办公 | https://work.weixin.qq.com |", report_fallback)
        self.assertNotIn('"website": ""', opening_context)
        self.assertNotIn("官网：公开资料不足", opening_fallback)

    def test_writer_fairly_samples_dynamic_section_claims_by_competitor(self):
        agent = ReportWriterAgent()
        section = {
            "id": "direction_core_product_supply",
            "source_dimension_ids": ["direction_core_product_supply"],
        }
        claims = [
            {
                "id": f"claim_feishu_{index}",
                "dimension": "direction_core_product_supply",
                "claim": f"飞书功能证据 {index}",
                "competitors": ["飞书"],
                "evidence_ids": [f"ev_feishu_{index}"],
            }
            for index in range(11)
        ] + [
            {
                "id": f"claim_dingtalk_{index}",
                "dimension": "direction_core_product_supply",
                "claim": f"钉钉功能证据 {index}",
                "competitors": ["钉钉"],
                "evidence_ids": [f"ev_dingtalk_{index}"],
            }
            for index in range(6)
        ]

        sampled_claims = agent._claims_for_dynamic_section(
            claims,
            section,
            limit=12,
        )

        self.assertEqual(len(sampled_claims), 12)
        sampled_competitors = [
            claim["competitors"][0]
            for claim in sampled_claims
        ]
        self.assertGreaterEqual(sampled_competitors.count("飞书"), 1)
        self.assertGreaterEqual(sampled_competitors.count("钉钉"), 1)
        self.assertEqual(sampled_competitors[:4], ["飞书", "钉钉", "飞书", "钉钉"])

    def test_writer_builds_dynamic_sections_from_claim_dimensions(self):
        agent = ReportWriterAgent()
        claims = [
            {
                "id": "claim_1",
                "dimension": "direction_core_product_supply",
                "claim": "飞书公开资料显示其多维表格能力覆盖项目管理。",
                "competitors": ["飞书"],
                "evidence_ids": ["ev_1"],
            },
            {
                "id": "claim_2",
                "dimension": "direction_ai_capability_application",
                "claim": "钉钉公开资料显示其 AI 助理覆盖审批场景。",
                "competitors": ["钉钉"],
                "evidence_ids": ["ev_2"],
            },
        ]
        evidence_items = [
            {
                "id": "ev_1",
                "dimension_id": "direction_core_product_supply",
                "dimension_name": "核心产品供给",
                "competitor": "飞书",
            },
            {
                "id": "ev_2",
                "dimension_id": "direction_ai_capability_application",
                "dimension_name": "AI 能力落地",
                "competitor": "钉钉",
            },
        ]

        sections = agent._dynamic_analysis_sections(claims, evidence_items, [])

        self.assertEqual(
            [section["title"] for section in sections],
            ["核心产品供给", "AI 能力落地"],
        )
        self.assertEqual(
            [section["source_dimension_ids"] for section in sections],
            [["direction_core_product_supply"], ["direction_ai_capability_application"]],
        )

    def test_writer_keeps_weak_claims_with_evidence_bindings(self):
        class EmptyReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher

            async def write_report(self, **kwargs):
                return ""

        state = {
            "task": {"query": "对比淘宝、京东、拼多多"},
            "competitors": [{"name": "淘宝"}],
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "market_growth",
                    "claim": "淘宝公开资料显示其平台定位覆盖综合电商场景。",
                    "competitors": ["淘宝"],
                    "evidence_ids": ["ev_1"],
                    "confidence": 0.62,
                }
            ],
            "claim_support_reviews": [
                {
                    "claim_id": "claim_1",
                    "support_status": "weak",
                    "evidence_ids": ["ev_1"],
                    "reviewer_notes": "Evidence is traceable but wording needs tightening.",
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "淘宝",
                    "dimension_id": "market_growth",
                    "dimension_name": "市场与增长",
                    "title": "淘宝官网",
                    "url": "https://www.taobao.com",
                    "excerpt": "淘宝平台提供综合电商服务。",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=EmptyReportGenerator).run(state)
        )

        self.assertIn("淘宝公开资料显示其平台定位覆盖综合电商场景", result["report"])
        self.assertIn("证据较弱，需复核", result["report"])
        self.assertNotIn("| 市场与增长 | 综合 | 公开证据不足 | 无 |", result["report"])

    def test_writer_escapes_information_index_markdown_table_cells(self):
        class EmptyReportGenerator:
            def __init__(self, researcher):
                self.researcher = researcher

            async def write_report(self, **kwargs):
                return ""

        state = {
            "task": {"query": "Compare Acme pricing"},
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "dimension": "pricing_model",
                    "claim": "Acme publishes pricing tiers.",
                    "evidence_ids": ["ev_1"],
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "Acme",
                    "dimension_id": "pricing_model",
                    "dimension_name": "Pricing | Packaging",
                    "title": "Acme | pricing",
                    "url": "https://acme.example/pricing?a=1|b=2",
                    "excerpt": "Starter | Pro\nEnterprise tiers are listed.",
                    "source_type": "pricing_page",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            ReportWriterAgent(report_generator_factory=EmptyReportGenerator).run(state)
        )

        self.assertIn("Pricing \\| Packaging", result["report"])
        self.assertIn("Acme \\| pricing", result["report"])
        self.assertIn("Starter \\| Pro Enterprise tiers are listed.", result["report"])
        self.assertIn("https://acme.example/pricing?a=1\\|b=2", result["report"])


if __name__ == "__main__":
    unittest.main()
