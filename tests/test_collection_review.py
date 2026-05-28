import asyncio
import unittest

from rivalens.agents.analysis import AnalysisAgent
from rivalens.agents.branch_review import BranchReviewAgent
from rivalens.agents.collection import CollectionAgent
from rivalens.agents.evidence_review import EvidenceQualityReviewer
from rivalens.agents.knowledge_structuring import KnowledgeStructuringAgent
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

    def test_branch_review_uses_evidence_review_for_retry_decision(self):
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

        decision = BranchReviewAgent(min_sources_per_branch=1).review(
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
            active_schema={},
            root_query="Compare Acme pricing",
            evidence_review=evidence_review,
        )

        self.assertEqual(decision["decision"], "retry")
        self.assertEqual(decision["evidence_review_id"], evidence_review["id"])
        self.assertIn("missing_source_url", decision["evidence_gaps"])
        self.assertTrue(decision["next_queries"])

    def test_competitor_mismatch_retries_instead_of_failing_branch(self):
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

        decision = BranchReviewAgent(min_sources_per_branch=1).review(
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
            active_schema={},
            root_query="Compare Acme pricing",
            evidence_review=evidence_review,
        )

        self.assertEqual(evidence_review["required_action"], "retry")
        self.assertEqual(decision["decision"], "retry")
        self.assertIn("competitor_mismatch", decision["evidence_gaps"])
        self.assertTrue(decision["next_queries"])

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
