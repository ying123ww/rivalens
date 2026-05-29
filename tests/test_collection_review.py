import asyncio
import unittest

from rivalens.agents.analysis import AnalysisAgent
from rivalens.agents.claim_support import ClaimSupportReviewer
from rivalens.agents.collection import CollectionAgent
from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.evidence_review import EvidenceQualityReviewer
from rivalens.agents.knowledge_structuring import KnowledgeStructuringAgent
from rivalens.agents.landscape_review import LandscapeReviewer
from rivalens.agents.planning import PlanningAgent
from rivalens.agents.writing import ReportWriterAgent
from rivalens.research.evidence_collector import ResearchEngineEvidenceCollector


def pricing_branch():
    return {
        "id": "collect_acme_pricing_model",
        "depth": 0,
        "competitor": "Acme",
        "dimension_id": "pricing_model",
        "dimension_name": "Pricing Model",
        "topic": "Pricing Model",
    }


class CollectionReviewTest(unittest.TestCase):
    def test_planning_creates_ten_confirmable_analysis_dimensions(self):
        state = {
            "task": {
                "query": "Compare Acme and Beta productivity tools",
                "competitors": ["Acme", "Beta"],
            },
            "messages": [],
        }

        result = asyncio.run(PlanningAgent().run(state))

        dimensions = result["analysis_dimensions"]
        self.assertEqual(len(dimensions), 10)
        self.assertEqual(dimensions[0]["name"], "战略定位")
        dimension_artifact = result["research_artifacts"][-1]
        self.assertEqual(dimension_artifact["mode"], "dimension_confirmation")
        self.assertIn("维度确认", dimension_artifact["report"])
        self.assertIn("3.1 战略定位", dimension_artifact["report"])
        pricing_dimension = [
            dimension
            for dimension in dimensions
            if dimension["id"] == "pricing_business_model"
        ][0]
        self.assertIn("pricing_page", pricing_dimension["expected_source_types"])
        self.assertTrue(pricing_dimension["minimum_coverage"])

    def test_collection_root_branches_use_confirmed_analysis_dimensions(self):
        branches = CollectionAgent()._build_root_branches(
            query="Compare Acme and Beta",
            competitors=[{"name": "Acme"}],
            active_schema={"selected_industry": {"name": "Productivity SaaS"}},
            analysis_dimensions=[
                {
                    "id": "strategic_positioning",
                    "name": "战略定位",
                    "description": "品牌定位和市场细分。",
                    "guiding_questions": ["各竞品官方的产品定位是什么？"],
                    "search_intent": "搜索战略定位公开证据。",
                    "priority": "P0",
                }
            ],
        )

        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["dimension_id"], "strategic_positioning")
        self.assertEqual(branches[0]["dimension_name"], "战略定位")
        self.assertIn("各竞品官方的产品定位是什么？", branches[0]["query"])
        self.assertIn("搜索战略定位公开证据", branches[0]["query"])
        self.assertEqual(branches[0]["search_stage"], "focused")

    def test_collection_generates_gap_driven_follow_up_tasks(self):
        class FakeEvidenceCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                gap = collection_task.get("generated_from_gap", "")
                if "pricing_page" in gap:
                    source = {
                        "competitor": "Acme",
                        "dimension_id": "pricing_business_model",
                        "title": "Acme Pricing",
                        "url": "https://acme.example/pricing",
                        "source_type": "pricing_page",
                        "excerpt": "Acme publishes official pricing plans and enterprise packaging.",
                        "confidence": 0.9,
                    }
                elif "official_site" in gap:
                    source = {
                        "competitor": "Acme",
                        "dimension_id": "pricing_business_model",
                        "title": "Acme Plans",
                        "url": "https://acme.example/plans",
                        "source_type": "other",
                        "excerpt": "Acme describes plan packaging on its official site.",
                        "confidence": 0.8,
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
            },
            "analysis_dimensions": [
                {
                    "id": "pricing_business_model",
                    "name": "定价与商业模式",
                    "description": "价格、套餐、计费单位、免费层、企业销售和收入模式。",
                    "priority": "P0",
                    "guiding_questions": ["公开定价和套餐结构是什么？"],
                    "search_intent": "搜索官方定价证据。",
                    "expected_source_types": ["pricing_page", "official_site"],
                    "minimum_coverage": ["Official pricing source required."],
                    "risk_level": "high",
                    "expected_claim_types": ["pricing"],
                }
            ],
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
        self.assertIn("missing_source_type:pricing_page", generated_gaps)
        self.assertIn("missing_source_type:official_site", generated_gaps)
        self.assertGreaterEqual(len(result["coverage_assessments"]), 2)
        self.assertEqual(
            result["coverage_assessments"][0]["next_action"],
            "collect_more",
        )
        self.assertTrue(
            any(
                task.get("generated_from_gap") == "missing_source_type:pricing_page"
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
                evidence["source_type"] == "pricing_page"
                for evidence in result["evidence_items"]
            )
        )

    def test_landscape_task_creates_assessment_without_evidence_items(self):
        seen_calls = []

        class FakeLandscapeCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                seen_calls.append(
                    {
                        "task": dict(collection_task),
                        "mode": getattr(mode, "value", mode),
                        "source_urls": source_urls or [],
                    }
                )
                if collection_task.get("search_stage") == "landscape":
                    sources = [
                        {
                            "title": "Acme product overview",
                            "url": "https://acme.example/product",
                            "source_type": "official_site",
                            "excerpt": "Acme product overview.",
                            "confidence": 0.7,
                        }
                    ]
                else:
                    sources = []
                return {
                    "task": dict(collection_task),
                    "mode": "standard_evidence",
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": sources,
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme moat",
                "competitors": [{"name": "Acme"}],
                "verbose": False,
            },
            "active_knowledge_schema": {
                "id": "schema_productivity",
                "selected_industry": {"name": "Productivity SaaS"},
            },
            "analysis_dimensions": [
                {
                    "id": "market_growth",
                    "name": "市场增长",
                    "description": "市场规模、增长速度、需求变化和商业机会。",
                    "priority": "P1",
                    "guiding_questions": ["公开市场增长线索是什么？"],
                    "search_intent": "搜索市场增长公开线索。",
                    "expected_source_types": ["official_site", "review"],
                    "minimum_coverage": ["Landscape first, then focused collection."],
                    "risk_level": "high",
                    "expected_claim_types": ["market_signal"],
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=FakeLandscapeCollector(),
                max_branch_depth=1,
                max_expansion_branches=2,
            ).run(state)
        )

        self.assertEqual(len(result["evidence_items"]), 0)
        self.assertEqual(len(result["landscape_assessments"]), 1)
        landscape = result["landscape_assessments"][0]
        self.assertEqual(landscape["decision"]["action"], "evidence_extraction")
        self.assertEqual(landscape["decision"]["subtype"], "targeted_url_extract")
        self.assertIn("official_site", landscape["discovered_source_types"])
        self.assertTrue(landscape["focused_task_specs"])
        self.assertEqual(
            landscape["focused_task_specs"][0]["target_urls"],
            ["https://acme.example/product"],
        )
        self.assertTrue(
            any(
                task["search_stage"] == "focused"
                and task["generated_from_gap"] == "landscape_candidate_source"
                and task["parent_task_id"] == "task_collect_acme_market_growth"
                and task["target_urls"] == ["https://acme.example/product"]
                and task["decision_action"] == "evidence_extraction"
                and task["decision_subtype"] == "targeted_url_extract"
                for task in result["research_tasks"]
            )
        )
        self.assertTrue(
            any(
                call["task"].get("search_stage") == "focused"
                and call["mode"] == "standard_evidence"
                and call["source_urls"] == ["https://acme.example/product"]
                for call in seen_calls
            )
        )
        self.assertTrue(
            any(
                call["task"].get("search_stage") == "landscape"
                and call["mode"] == "source_discovery"
                for call in seen_calls
            )
        )

    def test_landscape_budget_stop_is_recorded_when_depth_budget_blocks_follow_up(self):
        class FakeLandscapeCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                return {
                    "task": dict(collection_task),
                    "mode": "standard_evidence",
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": [
                        {
                            "title": "Acme market page",
                            "url": "https://acme.example/market",
                            "source_type": "official_site",
                            "excerpt": "Acme market page.",
                            "confidence": 0.8,
                        }
                    ],
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme market growth",
                "competitors": [{"name": "Acme"}],
                "verbose": False,
            },
            "analysis_dimensions": [
                {
                    "id": "market_growth",
                    "name": "市场增长",
                    "expected_source_types": ["official_site"],
                    "risk_level": "high",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=FakeLandscapeCollector(),
                max_branch_depth=0,
                max_expansion_branches=4,
            ).run(state)
        )

        landscape = result["landscape_assessments"][0]
        self.assertEqual(landscape["decision"]["action"], "stop")
        self.assertEqual(landscape["decision"]["subtype"], "budget_stop")
        self.assertEqual(len(result["research_tasks"]), 1)
        self.assertEqual(result["research_branches"][0]["status"], "stopped")

    def test_landscape_allocator_preserves_candidate_and_missing_source_types(self):
        assessment = LandscapeReviewer().review(
            branch={
                "id": "collect_acme_pricing_business_model",
                "competitor": "Acme",
                "dimension_id": "pricing_business_model",
                "dimension_name": "定价与商业模式",
                "expected_source_types": ["pricing_page", "official_site", "review"],
            },
            research_task={
                "id": "task_collect_acme_pricing_business_model",
                "query": "Compare Acme pricing",
            },
            sources=[
                {
                    "title": "Acme product page",
                    "url": "https://acme.example/product",
                    "source_type": "official_site",
                },
                {
                    "title": "Acme docs",
                    "url": "https://docs.acme.example/start",
                    "source_type": "docs",
                },
            ],
        )

        specs = assessment["focused_task_specs"]
        self.assertEqual(len(specs), 3)
        self.assertEqual(specs[0]["generated_from_gap"], "landscape_candidate_source")
        self.assertEqual(specs[0]["decision_action"], "evidence_extraction")
        self.assertEqual(specs[0]["decision_subtype"], "targeted_url_extract")
        self.assertEqual(
            specs[1]["generated_from_gap"],
            "landscape_missing_source_type:pricing_page",
        )
        self.assertEqual(specs[1]["decision_action"], "source_discovery")
        self.assertEqual(specs[1]["decision_subtype"], "source_type_search")
        self.assertEqual(
            specs[2]["generated_from_gap"],
            "landscape_missing_source_type:review",
        )

    def test_landscape_competitor_disambiguation_is_reachable(self):
        assessment = LandscapeReviewer().review(
            branch={
                "id": "collect_acme_market_growth",
                "competitor": "Acme",
                "dimension_id": "market_growth",
                "dimension_name": "市场增长",
                "expected_source_types": ["official_site"],
            },
            research_task={
                "id": "task_collect_acme_market_growth",
                "query": "Compare Acme market growth",
            },
            sources=[
                {
                    "title": "Unrelated Acme listing",
                    "url": "https://directory.example/acme",
                    "source_type": "other",
                }
            ],
        )

        self.assertEqual(assessment["decision"]["action"], "entity_resolution")
        self.assertEqual(
            assessment["decision"]["subtype"],
            "competitor_disambiguation",
        )
        self.assertEqual(
            assessment["focused_task_specs"][0]["generated_from_gap"],
            "competitor_disambiguation",
        )
        self.assertIn("Acme official site", assessment["focused_task_specs"][0]["query"])

    def test_landscape_dimension_split_creates_child_dimension_tasks(self):
        class FakeSplitCollector:
            async def collect(self, collection_task, mode="standard_evidence", verbose=True, source_urls=None):
                sources = []
                if collection_task.get("search_stage") == "landscape":
                    sources = [
                        {
                            "title": "Acme moat overview",
                            "url": "https://acme.example/moat",
                            "source_type": "official_site",
                            "excerpt": "Acme product overview.",
                            "confidence": 0.7,
                        }
                    ]
                return {
                    "task": dict(collection_task),
                    "mode": "standard_evidence",
                    "query": collection_task["query"],
                    "context": "",
                    "evidence_items": sources,
                    "costs": 0.0,
                }

        state = {
            "task": {
                "query": "Compare Acme moat",
                "competitors": [{"name": "Acme"}],
                "verbose": False,
            },
            "analysis_dimensions": [
                {
                    "id": "competitive_moat",
                    "name": "竞争壁垒",
                    "description": "护城河、替代风险、迁移成本、生态依赖、品牌资产和长期优势。",
                    "expected_source_types": ["official_site", "review"],
                    "risk_level": "high",
                }
            ],
            "messages": [],
        }

        result = asyncio.run(
            CollectionAgent(
                evidence_collector=FakeSplitCollector(),
                max_branch_depth=1,
                max_expansion_branches=4,
            ).run(state)
        )

        landscape = result["landscape_assessments"][0]
        self.assertEqual(landscape["decision"]["action"], "scope_refinement")
        self.assertEqual(
            landscape["decision"]["subtype"],
            "dimension_decomposition",
        )
        self.assertTrue(landscape["split_task_specs"])
        split_tasks = [
            task
            for task in result["research_tasks"]
            if task.get("generated_from_gap", "").startswith("dimension_split:")
        ]
        self.assertTrue(split_tasks)
        self.assertEqual(
            split_tasks[0]["dimension_id"],
            "competitive_moat.switching_cost",
        )
        self.assertEqual(split_tasks[0]["decision_action"], "scope_refinement")
        self.assertEqual(split_tasks[0]["decision_subtype"], "dimension_decomposition")
        self.assertEqual(split_tasks[0]["parent_task_id"], "task_collect_acme_competitive_moat")

    def test_claim_support_review_generates_verification_task_for_unverifiable_claim(self):
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
            "analysis_dimensions": [
                {
                    "id": "pricing_business_model",
                    "name": "定价与商业模式",
                    "description": "价格、套餐、计费单位、免费层、企业销售和收入模式。",
                    "expected_source_types": ["pricing_page"],
                }
            ],
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
            "source_discovery",
        )
        self.assertEqual(
            assessment["follow_up_task_specs"][0]["decision_subtype"],
            "coverage_gap_search",
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
        self.assertEqual(
            assessment["follow_up_task_specs"][0]["decision_action"],
            "source_discovery",
        )
        self.assertEqual(
            assessment["follow_up_task_specs"][0]["decision_subtype"],
            "coverage_gap_search",
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
        self.assertIn("quality-reviewed Pricing Model evidence", claim["claim"])
        self.assertIn("Acme publishes a starter pricing plan", claim["claim"])
        self.assertNotIn("Rejected scrape", claim["claim"])

    def test_writer_uses_report_generator_with_traceable_evidence_context(self):
        created_researchers = []

        class FakeReportGenerator:
            def __init__(self, researcher):
                created_researchers.append(researcher)

            async def write_report(self, **kwargs):
                created_researchers[0].add_costs(0.25)
                return "# Generated Report\n\nAcme has a public starter plan."

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

        researcher = created_researchers[0]
        self.assertIn("第一章：分析目的", researcher.custom_prompt)
        self.assertIn("第三章：竞品分析", researcher.custom_prompt)
        self.assertIn("Acme publishes a starter pricing plan", researcher.context)
        self.assertIn("https://acme.example/pricing", researcher.context)
        self.assertNotIn("ev_2", researcher.context)
        self.assertNotIn("https://acme.example/rejected", researcher.context)
        self.assertIn("# Generated Report", result["report"])
        self.assertIn("## 附录：信息索引表格", result["report"])
        self.assertIn("claim_1", result["report"])
        self.assertIn("ev_1", result["report"])
        self.assertNotIn("ev_2", result["report"])
        self.assertIn("https://acme.example/pricing", result["report"])
        self.assertNotIn("https://acme.example/rejected", result["report"])
        self.assertEqual(result["messages"][-1]["evidence_ids"], ["ev_1"])
        self.assertEqual(result["agent_events"][-1]["output"]["cost"], 0.25)

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
        self.assertIn("## 第四章：总结", result["report"])
        self.assertIn("Acme publishes a starter pricing plan", result["report"])
        self.assertIn("## 附录：信息索引表格", result["report"])
        self.assertIn("https://acme.example/pricing", result["report"])


if __name__ == "__main__":
    unittest.main()
