import asyncio
import unittest
from unittest.mock import patch

from rivalens.agents.analysis import AnalysisAgent
from rivalens.agents.claim_support import ClaimSupportReviewer
from rivalens.agents.collection import CollectionAgent
from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.evidence_review import EvidenceQualityReviewer
from rivalens.agents.knowledge_structuring import KnowledgeStructuringAgent
from rivalens.agents.writing import (
    OPENING_CONTEXT_CHAR_LIMIT,
    SECTION_CONTEXT_CHAR_LIMIT,
    SUMMARY_CONTEXT_CHAR_LIMIT,
    ReportWriterAgent,
)
from rivalens.research.evidence_collector import ResearchEngineEvidenceCollector
from rivalens.schema import SOURCE_TYPE_PRIORITY
from rivalens.workflows.competitive_analysis import _int_budget


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
        self.assertGreaterEqual(len(branches[1]["search_queries"]), 2)
        self.assertTrue(
            any("official" in query.lower() for query in branches[1]["search_queries"])
        )
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
        self.assertEqual(collection_task["search_queries"], branch["search_queries"])
        self.assertTrue(
            any(
                "pricing" in query.lower() or "plans" in query.lower()
                for query in collection_task["search_queries"]
            )
        )

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
                self.assertTrue(
                    any("pricing" in query.lower() for query in branch["search_queries"])
                )
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
                if gap == "missing_guiding_question":
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
                        "guiding_questions": ["What packaging details are available?"],
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
        self.assertIn("missing_guiding_question", generated_gaps)
        self.assertGreaterEqual(len(result["coverage_assessments"]), 2)
        self.assertEqual(
            result["coverage_assessments"][0]["next_action"],
            "collect_more",
        )
        self.assertEqual(
            result["coverage_assessments"][0]["decision"]["action"],
            "source_discovery",
        )
        self.assertEqual(
            result["coverage_assessments"][0]["decision"]["subtype"],
            "coverage_gap_search",
        )
        self.assertEqual(
            result["coverage_assessments"][0]["stage_contract"]["search_stage"],
            "focused",
        )
        self.assertTrue(
            result["coverage_assessments"][0]["stage_contract"]["produces_evidence"],
        )
        self.assertTrue(result["coverage_assessments"][0]["selected_follow_up_specs"])
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
                if '"id": "business_model"' in context:
                    return "\n".join(
                        [
                            "| 竞品 | 结论 | 引用 |",
                            "| --- | --- | --- |",
                            "| Acme | Acme publishes a starter pricing plan. | [1] |",
                            "",
                            "分析：Acme publishes a starter pricing plan.",
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

        self.assertEqual(len(created_researchers), 3)
        opening_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: opening" in researcher.query
        )
        pricing_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: product_business_model" in researcher.query
        )
        summary_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: summary" in researcher.query
        )
        self.assertIn("第一章：分析目的", opening_researcher.custom_prompt)
        self.assertIn("3.3 商业模式", pricing_researcher.custom_prompt)
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
        self.assertIn("| 章节 | 引导问题 | 数据来源约束 |", result["report"])
        self.assertIn("| 3.3 商业模式 | 这个产品怎么赚钱？定价策略是什么？ | 定价页、公开财务信息 |", result["report"])
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
        self.assertEqual(event["input"]["segment_count"], 3)
        self.assertEqual(
            event["input"]["max_segment_context_length"],
            max(len(researcher.context) for researcher in created_researchers),
        )
        self.assertGreater(
            event["input"]["context_length"],
            event["input"]["max_segment_context_length"],
        )
        self.assertEqual(result["agent_events"][-1]["output"]["cost"], 0.75)

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
            if "Segment: product_business_model" in researcher.query
        )
        summary_researcher = next(
            researcher
            for researcher in created_researchers
            if "Segment: summary" in researcher.query
        )
        self.assertLessEqual(len(opening_researcher.context), OPENING_CONTEXT_CHAR_LIMIT)
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
        self.assertIn("| 3.1 战略定位 | 这个产品把自己定位成什么？和竞品的定位差异在哪？ | 官网首页、公开采访、品牌宣传 |", result["report"])
        self.assertIn("### 3.3 商业模式", result["report"])
        self.assertIn("### 3.10 用户口碑", result["report"])
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
        self.assertIn("| 章节 | 引导问题 | 数据来源约束 |", result["report"])
        self.assertIn("| 3.1 战略定位 | 这个产品把自己定位成什么？和竞品的定位差异在哪？ | 官网首页、公开采访、品牌宣传 |", result["report"])
        self.assertIn("### 3.10 用户口碑", result["report"])
        self.assertIn("Acme publishes a starter pricing plan. [1]", result["report"])
        self.assertIn("## 第四章：总结", result["report"])

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
