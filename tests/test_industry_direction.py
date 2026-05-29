import asyncio
import unittest

from rivalens.agents.industry_direction import IndustryDirectionSkill
from rivalens.agents.planning import PlanningAgent
from rivalens.industry_templates import INDUSTRY_DIRECTION_TEMPLATES
from rivalens.schema.competitive import EvidenceType, SOURCE_TYPE_PRIORITY
from rivalens.schema_registry.registry import SchemaRegistry


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
            (
                "对比 OpenAI API、Claude API 和 Gemini API 的模型平台能力",
                "ai_model_platform",
                [
                    "model_capabilities",
                    "benchmarks_evaluations",
                    "context_window_long_context",
                    "inference_speed_latency",
                    "multimodal_capabilities",
                    "developer_experience",
                    "finetuning_rag_customization",
                    "deployment_options",
                    "reliability_rate_limits",
                ],
            ),
            (
                "对比 ChatGPT、Kimi 和 Perplexity 的 AI 产品体验",
                "ai_product_application",
                [
                    "strategic_positioning",
                    "target_users_personas",
                    "core_feature_matrix",
                    "signature_features",
                    "product_flow_experience",
                    "ai_output_quality",
                    "pricing_business_model",
                    "data_privacy_trust",
                    "ecosystem_integrations",
                    "user_sentiment_pain_points",
                    "platform_device_coverage",
                    "safety_content_limits",
                    "growth_retention_strategy",
                    "team_funding_momentum",
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
        self.assertEqual(len(INDUSTRY_DIRECTION_TEMPLATES), 15)
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

    def test_schema_registry_uses_industry_direction_template_ids(self):
        template_ids = {
            template["industry_id"] for template in INDUSTRY_DIRECTION_TEMPLATES
        }
        registry = SchemaRegistry()
        registry_ids = {
            definition.industry_id for definition in registry.industries
        }

        self.assertTrue(template_ids.issubset(registry_ids))
        self.assertIn(
            "security_compliance",
            [
                extension["id"]
                for extension in registry.get_extensions("saas_collaboration")
            ],
        )
        self.assertIn(
            "regulatory_compliance",
            [
                extension["id"]
                for extension in registry.get_extensions("financial_services")
            ],
        )

    def test_builds_flat_direction_review_rows(self):
        from rivalens.industry_templates.review import build_direction_review_rows

        rows = build_direction_review_rows(INDUSTRY_DIRECTION_TEMPLATES)
        expected_count = sum(
            len(template.get("directions", []))
            for template in INDUSTRY_DIRECTION_TEMPLATES
        )
        sample = next(
            row
            for row in rows
            if row["industry_id"] == "ai_product_application"
            and row["direction_id"] == "pricing_business_model"
        )

        self.assertEqual(len(rows), expected_count)
        self.assertEqual(sample["industry_name"], "AI 产品 / 智能应用")
        self.assertEqual(sample["required"], "是")
        self.assertEqual(
            sample["source_hints"],
            "pricing_page, official_site, review, news",
        )
        self.assertIn("人工备注", sample)
        self.assertIn("动作", sample)

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
            query="对比 ChatGPT、Kimi 和 Perplexity 的 AI 产品竞争格局",
            competitors=[{"name": "ChatGPT"}, {"name": "Kimi"}],
        )

        pricing_direction = next(
            direction
            for direction in plan["default_directions"]
            if direction["direction_id"] == "pricing_business_model"
        )
        self.assertEqual(
            pricing_direction["source_hints"],
            ["pricing_page", "official_site", "review", "news"],
        )

    def test_planner_additions_do_not_change_industry_default_directions(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 Notion 和飞书的 SaaS 协作能力",
            competitors=[{"name": "Notion"}, {"name": "飞书"}],
        )
        default_ids = [
            direction["direction_id"] for direction in plan["default_directions"]
        ]
        planner_added_ids = [
            direction["direction_id"]
            for direction in plan["planner_added_directions"]
        ]

        self.assertEqual(
            default_ids,
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
        )
        self.assertIn("strategic_positioning", planner_added_ids)
        self.assertTrue(set(default_ids).isdisjoint(planner_added_ids))
        self.assertTrue(
            all(
                direction["origin"] == "planner_suggested"
                for direction in plan["planner_added_directions"]
            )
        )
        self.assertEqual(
            [
                direction["direction_id"]
                for direction in plan["suggested_directions"]
            ],
            default_ids,
        )

    def test_plan_suggests_competitors_when_query_has_no_pair(self):
        from rivalens.schema import IndustryDirectionPlanPayload

        plan = IndustryDirectionSkill().build_plan(
            query="分析 SaaS 协作文档工具的竞争格局",
        )
        validated = IndustryDirectionPlanPayload(**plan)

        self.assertEqual(validated.detected_competitors, [])
        self.assertIn("notion", validated.suggested_competitors)
        self.assertIn("飞书", validated.suggested_competitors)
        self.assertEqual(
            validated.final_analysis_plan["detected_competitors"],
            [],
        )
        self.assertIn(
            "suggested_competitors",
            validated.final_analysis_plan,
        )

    def test_plan_detects_known_competitors_from_query(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 Notion 和 飞书 的 SaaS 协作能力",
        )

        self.assertEqual(plan["detected_competitors"], ["notion", "飞书"])
        self.assertNotIn("notion", plan["suggested_competitors"])
        self.assertNotIn("飞书", plan["suggested_competitors"])

    def test_identifies_ai_tools_and_merges_user_directions(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 ChatGPT、Kimi 和 Perplexity 的 AI 产品竞争格局",
            competitors=[{"name": "ChatGPT"}, {"name": "Kimi"}],
            user_directions=["我还想重点看 AI 写作能力和私有化部署能力。"],
            user_confirmed=True,
        )

        self.assertEqual(plan["industry"]["industry_id"], "ai_product_application")
        self.assertTrue(plan["user_confirmed"])
        self.assertEqual(
            [direction["direction_id"] for direction in plan["default_directions"]],
            [
                "strategic_positioning",
                "target_users_personas",
                "core_feature_matrix",
                "signature_features",
                "product_flow_experience",
                "ai_output_quality",
                "pricing_business_model",
                "data_privacy_trust",
                "ecosystem_integrations",
                "user_sentiment_pain_points",
                "platform_device_coverage",
                "safety_content_limits",
                "growth_retention_strategy",
                "team_funding_momentum",
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
        self.assertIn("planner_added_directions", plan["final_analysis_plan"])

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
        self.assertNotIn(
            "strategic_positioning",
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

    def test_planning_agent_uses_detected_competitors_when_none_are_explicit(self):
        state = {
            "task": {
                "query": "对比 ChatGPT、Kimi 和 Perplexity 的 AI 产品体验",
            },
            "messages": [],
        }

        result = asyncio.run(PlanningAgent().run(state))

        self.assertEqual(
            [competitor["name"] for competitor in result["competitors"]],
            ["chatgpt", "kimi", "perplexity"],
        )
        self.assertEqual(
            result["industry_direction_plan"]["detected_competitors"],
            ["chatgpt", "kimi", "perplexity"],
        )

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
            "context_window_long_context",
            "inference_speed_latency",
            "reliability_rate_limits",
            "strategic_positioning",
            "target_users_personas",
            "core_feature_matrix",
            "signature_features",
            "product_flow_experience",
            "ai_output_quality",
            "pricing_business_model",
            "data_privacy_trust",
            "user_sentiment_pain_points",
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

    def test_scenario_specific_directions_are_optional_defaults(self):
        optional_direction_ids = {
            "live_content_commerce",
            "merchant_developer_api",
            "payment_success_settlement",
            "ai_personalization_learning",
            "disruption_support_insurance",
            "merchant_marketing_tools",
            "smart_cockpit_system",
            "sales_volume_market_share",
            "multimodal_capabilities",
            "developer_experience",
            "finetuning_rag_customization",
            "deployment_options",
            "platform_device_coverage",
            "safety_content_limits",
            "growth_retention_strategy",
            "team_funding_momentum",
        }
        direction_index = {
            direction["direction_id"]: direction
            for template in INDUSTRY_DIRECTION_TEMPLATES
            for direction in template.get("directions", [])
        }

        for direction_id in optional_direction_ids:
            with self.subTest(direction_id=direction_id):
                self.assertIn(direction_id, direction_index)
                self.assertFalse(direction_index[direction_id]["required"])


if __name__ == "__main__":
    unittest.main()
