import asyncio
import unittest

from rivalens.agents.industry_direction import IndustryDirectionSkill
from rivalens.agents.planning import PlanningAgent
from rivalens.industry_templates import INDUSTRY_DIRECTION_TEMPLATES
from rivalens.schema.competitive import EvidenceType, SOURCE_TYPE_PRIORITY


class IndustryDirectionSkillTest(unittest.TestCase):
    def test_uses_user_maintained_industry_templates(self):
        cases = [
            (
                "对比 Notion 和飞书的 SaaS 协作能力",
                "saas_collaboration",
                [
                    "pricing_packaging",
                    "collaboration_workflows",
                    "integrations_ecosystem",
                    "ai_assistance",
                    "security_admin_controls",
                    "reliability_status_sla",
                    "templates_use_cases",
                    "user_sentiment_reviews",
                    "mobile_offline_experience",
                    "data_portability_migration",
                ],
            ),
            (
                "分析 Stripe 和 PayPal 的金融支付竞品",
                "financial_services",
                [
                    "licenses_compliance",
                    "payment_security",
                    "fraud_risk_controls",
                    "pricing_fee_transparency",
                    "consumer_complaints",
                    "ecosystem_integrations",
                    "disclosure_transparency",
                    "merchant_developer_api",
                    "payment_success_settlement",
                    "aml_kyc_sanctions",
                    "fund_safeguarding",
                ],
            ),
            (
                "分析 Shopify 和 Amazon 的电商零售竞争",
                "ecommerce_retail",
                [
                    "pricing_fees",
                    "fulfillment_returns",
                    "assortment_catalog",
                    "seller_tools",
                    "trust_reviews",
                    "promotion_loyalty",
                    "ads_search_ranking",
                    "live_content_commerce",
                ],
            ),
            (
                "分析 微医 和 平安好医生 的医疗健康竞品",
                "healthcare",
                [
                    "regulatory_clearance",
                    "clinical_evidence",
                    "privacy_phi_security",
                    "patient_safety_quality",
                    "provider_network_access",
                    "pricing_insurance",
                    "care_operations",
                    "pharmaceutical_supply_chain",
                    "interoperability_ehr_fhir",
                ],
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

    def test_templates_define_source_hints_and_required_flags(self):
        self.assertEqual(len(INDUSTRY_DIRECTION_TEMPLATES), 14)
        valid_source_hints = set(EvidenceType.__args__)

        for template in INDUSTRY_DIRECTION_TEMPLATES:
            directions = template.get("default_directions") or template.get("directions")
            self.assertGreaterEqual(len(directions), 6, template["industry_id"])
            for direction in directions:
                with self.subTest(
                    industry=template["industry_id"],
                    direction=direction["direction_id"],
                ):
                    self.assertIsInstance(direction.get("required"), bool)
                    self.assertGreaterEqual(len(direction.get("source_hints", [])), 2)
                    self.assertTrue(
                        set(direction.get("source_hints", [])).issubset(
                            valid_source_hints
                        )
                    )

    def test_schema_supports_priority_evidence_sources(self):
        expected_sources = {
            "regulator_database",
            "financial_filing",
            "standards_body",
            "complaint_database",
            "incident_database",
            "case_study",
            "trust_center",
            "status_page",
            "benchmark",
            "analyst_report",
            "public_registry",
        }

        self.assertTrue(expected_sources.issubset(set(EvidenceType.__args__)))
        self.assertLess(
            SOURCE_TYPE_PRIORITY["regulator_database"],
            SOURCE_TYPE_PRIORITY["social"],
        )
        self.assertLess(
            SOURCE_TYPE_PRIORITY["pricing_page"],
            SOURCE_TYPE_PRIORITY["review"],
        )

    def test_template_source_hints_are_preserved_in_plan(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 ChatGPT、Claude 和 Kimi 的大模型产品竞争格局",
            competitors=[{"name": "ChatGPT"}, {"name": "Claude"}],
        )

        pricing_direction = next(
            direction
            for direction in plan["default_directions"]
            if direction["direction_id"] == "pricing_usage_limits"
        )
        self.assertEqual(
            pricing_direction["source_hints"],
            ["pricing_page", "docs", "official_site"],
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
            [
                "model_capabilities",
                "pricing_usage_limits",
                "benchmarks_evaluations",
                "developer_experience",
                "safety_compliance",
                "data_usage_training_policy",
                "deployment_options",
                "ecosystem_adoption",
                "context_window_long_context",
                "inference_speed_latency",
                "multimodal_capabilities",
                "finetuning_rag_customization",
            ],
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

    def test_can_remove_optional_default_directions_before_collection(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 Notion 和飞书的 SaaS 协作能力",
            selected_direction_ids=["pricing_packaging", "collaboration_workflows"],
            user_directions=["私有化部署能力"],
            user_confirmed=True,
        )

        self.assertEqual(
            plan["final_analysis_plan"]["final_directions"],
            [
                "pricing_packaging",
                "collaboration_workflows",
                "integrations_ecosystem",
                "ai_assistance",
                "security_admin_controls",
                "reliability_status_sla",
                "private_deployment",
            ],
        )
        self.assertNotIn(
            "templates_use_cases",
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
        direction_extensions = [
            extension
            for extension in active_schema["industry_extensions"]
            if extension["id"].startswith("direction_")
        ]
        direction_extension_ids = [extension["id"] for extension in direction_extensions]

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
        promotion_extension = next(
            extension
            for extension in direction_extensions
            if extension["id"] == "direction_promotion_loyalty"
        )
        self.assertIn("source_hints", promotion_extension)
        self.assertIn("pricing_page", promotion_extension["source_hints"])

    def test_priority_directions_are_required_and_use_specific_sources(self):
        required_direction_ids = {
            "promotion_loyalty",
            "ads_search_ranking",
            "ecosystem_integrations",
            "learner_outcomes_reviews",
            "privacy_accessibility_compliance",
            "care_operations",
            "interoperability_ehr_fhir",
            "search_packaging",
            "merchant_marketing_tools",
            "merchant_qualification_safety",
            "discovery_reviews_ranking",
            "safety_moderation_compliance",
            "ownership_cost",
            "ota_cybersecurity",
            "proof_and_trust",
            "sla_support_reliability",
            "food_safety_labeling_claims",
            "fair_housing_advertising_compliance",
            "technology_visibility",
            "deployment_options",
            "data_usage_training_policy",
        }
        direction_index = {
            direction["direction_id"]: direction
            for template in INDUSTRY_DIRECTION_TEMPLATES
            for direction in template.get("directions", [])
        }

        for direction_id in required_direction_ids:
            with self.subTest(direction_id=direction_id):
                self.assertIn(direction_id, direction_index)
                self.assertTrue(direction_index[direction_id]["required"])

        expected_source_hints = {
            "consumer_complaints": "complaint_database",
            "benchmarks_evaluations": "benchmark",
            "proof_and_trust": "case_study",
            "safety_recalls": "regulator_database",
            "operating_authority": "public_registry",
            "reliability_status_sla": "status_page",
            "food_safety_labeling_claims": "regulator_database",
        }
        for direction_id, source_hint in expected_source_hints.items():
            with self.subTest(direction_id=direction_id):
                self.assertIn(
                    source_hint,
                    direction_index[direction_id]["source_hints"],
                )


if __name__ == "__main__":
    unittest.main()
