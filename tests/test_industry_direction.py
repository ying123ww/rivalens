import asyncio
import unittest

from rivalens.agents.industry_direction import IndustryDirectionSkill
from rivalens.agents.planning import PlanningAgent


class IndustryDirectionSkillTest(unittest.TestCase):
    def test_uses_user_maintained_industry_templates(self):
        cases = [
            (
                "对比 Notion 和飞书的 SaaS 协作能力",
                "saas_collaboration",
                ["features", "pricing", "security", "integrations", "user_reviews"],
            ),
            (
                "分析 Stripe 和 PayPal 的金融支付竞品",
                "financial_services",
                ["fees", "compliance", "risk_control", "security", "regulatory_disclosure"],
            ),
            (
                "分析 Shopify 和 Amazon 的电商零售竞争",
                "ecommerce_retail",
                ["pricing", "logistics", "assortment", "promotions", "user_reviews"],
            ),
            (
                "分析 微医 和 平安好医生 的医疗健康竞品",
                "healthcare",
                ["qualification", "privacy", "security", "service_scope", "doctor_resources"],
            ),
        ]

        skill = IndustryDirectionSkill()
        for query, expected_industry, expected_directions in cases:
            with self.subTest(query=query):
                plan = skill.build_plan(query=query)
                self.assertEqual(plan["industry"]["industry_id"], expected_industry)
                self.assertEqual(
                    [
                        direction["direction_id"]
                        for direction in plan["suggested_directions"]
                    ],
                    expected_directions,
                )
                self.assertFalse(
                    any("id" in direction for direction in plan["suggested_directions"])
                )

    def test_identifies_ai_tools_and_merges_user_directions(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 ChatGPT、Claude 和 Kimi 的大模型产品竞争格局",
            competitors=[{"name": "ChatGPT"}, {"name": "Claude"}],
            user_directions=["我还想重点看 AI 写作能力和私有化部署能力。"],
            user_confirmed=True,
        )

        self.assertEqual(plan["industry"]["industry_id"], "ai_tools_llm")
        self.assertTrue(plan["user_confirmed"])
        self.assertEqual(
            [direction["direction_id"] for direction in plan["default_directions"]],
            ["model_capability", "pricing", "security", "developer_ecosystem", "user_reviews"],
        )
        self.assertEqual(
            [direction["direction_id"] for direction in plan["user_added_directions"]],
            ["ai_capability", "private_deployment"],
        )
        self.assertIn(
            "ai_capability",
            plan["final_analysis_plan"]["final_directions"],
        )
        self.assertIn(
            "private_deployment",
            plan["final_analysis_plan"]["final_directions"],
        )
        self.assertEqual(
            plan["final_analysis_plan"]["direction_count"],
            len(plan["final_directions"]),
        )

    def test_can_remove_default_directions_before_collection(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 Notion 和飞书的 SaaS 协作能力",
            selected_direction_ids=["features", "pricing"],
            user_directions=["私有化部署能力"],
            user_confirmed=True,
        )

        self.assertEqual(
            plan["final_analysis_plan"]["final_directions"],
            ["features", "pricing", "security", "user_reviews", "private_deployment"],
        )
        self.assertNotIn(
            "integrations",
            plan["final_analysis_plan"]["final_directions"],
        )

    def test_planning_agent_injects_directions_into_schema_selection(self):
        plan = IndustryDirectionSkill().build_plan(
            query="分析 Shopify 和 Amazon 在电商零售行业的竞品差异",
            user_directions=["商家侧运营工具"],
            user_confirmed=True,
        )
        state = {
            "task": {
                "query": "分析 Shopify 和 Amazon 在电商零售行业的竞品差异",
                "competitors": ["Shopify", "Amazon"],
                "industry_direction_plan": plan,
            },
            "messages": [],
        }

        result = asyncio.run(PlanningAgent().run(state))
        active_schema = result["active_knowledge_schema"]
        direction_extension_ids = [
            extension["id"]
            for extension in active_schema["industry_extensions"]
            if extension["id"].startswith("direction_")
        ]

        self.assertEqual(
            result["industry_direction_plan"]["industry"]["industry_id"],
            "ecommerce_retail",
        )
        self.assertIn("direction_user_direction_1", direction_extension_ids)
        self.assertEqual(result["messages"][-1]["type"], "schema_selection")
        self.assertIn(
            "industry_direction_plan",
            result["messages"][-1]["payload"],
        )


if __name__ == "__main__":
    unittest.main()
