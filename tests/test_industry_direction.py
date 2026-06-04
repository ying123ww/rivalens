import asyncio
import unittest

from rivalens.agents.industry_direction import IndustryDirectionSkill
from rivalens.agents.industry_llm_fallback import IndustryFallbackResult
from rivalens.agents.planning import (
    PlanningAgent,
    _planning_trace_inputs,
    _planning_trace_outputs,
)
from rivalens.industry_templates import (
    INDUSTRY_DIRECTION_TEMPLATES,
    L0_COMMON_DIRECTIONS,
    L1_ARCHETYPE_DIRECTIONS,
    L2_REGULATED_DOMAIN_DIRECTIONS,
)
from rivalens.schema.competitive import EvidenceType, SOURCE_TYPE_PRIORITY


class IndustryDirectionSkillTest(unittest.TestCase):
    def test_templates_are_facet_composed(self):
        self.assertEqual(len(INDUSTRY_DIRECTION_TEMPLATES), 15)

        template_by_id = {
            template["industry_id"]: template
            for template in INDUSTRY_DIRECTION_TEMPLATES
        }
        financial = template_by_id["financial_services"]
        ecommerce = template_by_id["ecommerce_retail"]

        self.assertEqual(financial["gics_sector"], "financials")
        self.assertEqual(
            financial["archetypes"],
            ["api_infrastructure", "saas_subscription"],
        )
        self.assertEqual(financial["regulated_domains"], ["finance"])
        self.assertEqual(
            len(financial["directions"]),
            len(L0_COMMON_DIRECTIONS)
            + len(L1_ARCHETYPE_DIRECTIONS["api_infrastructure"])
            + len(L1_ARCHETYPE_DIRECTIONS["saas_subscription"])
            + len(L2_REGULATED_DOMAIN_DIRECTIONS["finance"]),
        )
        self.assertEqual(
            len(ecommerce["directions"]),
            len(L0_COMMON_DIRECTIONS)
            + len(L1_ARCHETYPE_DIRECTIONS["two_sided_platform"])
            + len(L1_ARCHETYPE_DIRECTIONS["transaction_fulfillment"]),
        )

    def test_rule_plan_returns_l0_l1_l2_direction_stack(self):
        plan = IndustryDirectionSkill().build_plan(
            query="分析 Stripe 和 PayPal 的金融支付竞品",
        )
        direction_ids = [
            direction["direction_id"] for direction in plan["suggested_directions"]
        ]

        self.assertEqual(plan["industry"]["industry_id"], "financial_services")
        self.assertEqual(plan["selection_method"], "rule_facet_template")
        self.assertIn("strategic_positioning", direction_ids)
        self.assertIn("performance_rate_limits", direction_ids)
        self.assertIn("integrations_ecosystem", direction_ids)
        self.assertIn("financial_licenses_qualifications", direction_ids)
        self.assertIn("aml_kyc_sanctions", direction_ids)
        self.assertEqual(plan["planner_added_directions"], [])
        self.assertEqual(
            plan["final_analysis_plan"]["direction_composition"],
            {
                "model": "facet_l0_l1_l2",
                "gics_sector": "financials",
                "archetypes": ["api_infrastructure", "saas_subscription"],
                "regulated_domains": ["finance"],
                "layers": {
                    "l0": "common_business_analysis",
                    "l1": ["api_infrastructure", "saas_subscription"],
                    "l2": ["finance"],
                },
            },
        )

    def test_templates_define_source_hints_and_required_flags(self):
        valid_source_hints = set(EvidenceType.__args__)

        for template in INDUSTRY_DIRECTION_TEMPLATES:
            directions = template.get("default_directions") or template.get("directions")
            self.assertGreaterEqual(len(directions), len(L0_COMMON_DIRECTIONS))
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
            if row["industry_id"] == "financial_services"
            and row["direction_id"] == "financial_licenses_qualifications"
        )

        self.assertEqual(len(rows), expected_count)
        self.assertEqual(sample["industry_name"], "金融 / 支付 / Fintech")
        self.assertEqual(sample["required"], "是")
        self.assertIn("regulator_database", sample["source_hints"])
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
            "direction_composition",
            validated.final_analysis_plan,
        )

    def test_plan_detects_known_competitors_from_query(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 Notion 和 飞书 的 SaaS 协作能力",
        )

        self.assertEqual(plan["detected_competitors"], ["notion", "飞书"])
        self.assertNotIn("notion", plan["suggested_competitors"])
        self.assertNotIn("飞书", plan["suggested_competitors"])

    def test_low_confidence_industry_uses_llm_fallback_plan(self):
        class FakeFallback:
            llm_spec = "anthropic:mimo-v2.5-pro"

            def __init__(self):
                self.called = False

            def is_configured(self):
                return True

            async def classify(self, query, competitors, candidate_industries):
                self.called = True
                return IndustryFallbackResult(
                    industry_id="smart_hardware_wearables",
                    industry_name="智能硬件 / 可穿戴设备",
                    confidence=0.78,
                    reason="用户请求中的产品和竞品更接近可穿戴硬件，而非现有模板的明确命中。",
                    suggested_competitors=["Garmin"],
                    suggested_analysis_directions=[
                        {
                            "direction_id": "sensor_health_metrics",
                            "name": "健康传感与指标",
                            "reason": "可穿戴设备竞争依赖传感器、健康指标和数据解释能力。",
                            "search_focus": "公开健康传感器和指标能力",
                            "source_hints": ["official_site", "docs", "review"],
                            "required": True,
                        }
                    ],
                )

        fake_fallback = FakeFallback()
        plan = asyncio.run(
            IndustryDirectionSkill(
                llm_fallback=fake_fallback,
                fallback_threshold=0.95,
            ).build_plan_with_fallback(
                query="对比 Oura 和 Whoop 的可穿戴健康追踪能力",
                competitors=[{"name": "Oura"}, {"name": "Whoop"}],
            )
        )

        self.assertTrue(fake_fallback.called)
        self.assertEqual(plan["selection_method"], "llm_fallback")
        self.assertEqual(plan["industry"]["industry_id"], "smart_hardware_wearables")
        self.assertEqual(plan["fallback_model"], "anthropic:mimo-v2.5-pro")
        self.assertEqual(
            plan["default_directions"][0]["origin"],
            "llm_fallback",
        )
        self.assertEqual(
            plan["final_analysis_plan"]["final_directions"][0],
            "sensor_health_metrics",
        )
        from rivalens.schema import IndustryDirectionPlanPayload

        validated = IndustryDirectionPlanPayload(**plan)
        self.assertEqual(validated.selection_method, "llm_fallback")

    def test_high_confidence_industry_skips_llm_fallback(self):
        class FailingFallback:
            llm_spec = "anthropic:mimo-v2.5-pro"

            def is_configured(self):
                return True

            async def classify(self, query, competitors, candidate_industries):
                raise AssertionError("fallback should not be called")

        plan = asyncio.run(
            IndustryDirectionSkill(
                llm_fallback=FailingFallback(),
                fallback_threshold=0.35,
            ).build_plan_with_fallback(
                query="对比 Notion 和飞书的 SaaS 协作能力",
            )
        )

        self.assertEqual(plan["selection_method"], "rule_facet_template")
        self.assertEqual(plan["industry"]["industry_id"], "saas_collaboration")

    def test_identifies_ai_tools_and_merges_user_directions(self):
        plan = IndustryDirectionSkill().build_plan(
            query="对比 ChatGPT、Kimi 和 Perplexity 的 AI 产品竞争格局",
            competitors=[{"name": "ChatGPT"}, {"name": "Kimi"}],
            user_directions=["我还想重点看 AI 写作能力和私有化部署能力。"],
            user_confirmed=True,
        )

        self.assertEqual(plan["industry"]["industry_id"], "ai_product_application")
        self.assertTrue(plan["user_confirmed"])
        self.assertIn(
            "ai_capability_application",
            [direction["direction_id"] for direction in plan["default_directions"]],
        )
        self.assertIn(
            "integrations_ecosystem",
            [direction["direction_id"] for direction in plan["default_directions"]],
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
            selected_direction_ids=["strategic_positioning", "integrations_ecosystem"],
            user_directions=["私有化部署能力"],
            user_confirmed=True,
        )

        self.assertIn(
            "strategic_positioning",
            plan["final_analysis_plan"]["final_directions"],
        )
        self.assertIn(
            "integrations_ecosystem",
            plan["final_analysis_plan"]["final_directions"],
        )
        self.assertIn(
            "private_deployment",
            plan["final_analysis_plan"]["final_directions"],
        )
        self.assertNotIn(
            "planner_suggested",
            {direction["origin"] for direction in plan["final_directions"]},
        )

    def test_limit_keywords_no_longer_restrict_planner_directions(self):
        plan = IndustryDirectionSkill().build_plan(
            query="帮我对比钉钉和飞书，只看产品定位和定价，给出带来源的简短结论",
        )

        self.assertEqual(plan["industry"]["industry_id"], "saas_collaboration")
        self.assertFalse(plan["final_analysis_plan"]["scope_limited_by_query"])
        self.assertFalse(plan["final_analysis_plan"]["planner_supplement_skipped"])
        self.assertEqual(len(plan["planner_added_directions"]), 0)
        self.assertIn(
            "baseline_trust_security_compliance",
            plan["final_analysis_plan"]["final_directions"],
        )

    def test_planning_agent_derives_schema_field_ids_from_directions(self):
        state = {
            "task": {
                "query": "帮我对比钉钉和飞书，只看产品定位和定价，给出带来源的简短结论",
                "competitors": ["钉钉", "飞书"],
            },
            "messages": [],
        }

        result = asyncio.run(PlanningAgent().run(state))
        schema_field_ids = [
            schema_field_id
            for dimension in result["analysis_dimensions"]
            for schema_field_id in dimension["schema_field_ids"]
        ]

        self.assertIn("direction_business_model_pricing", schema_field_ids)
        self.assertIn("direction_strategic_positioning", schema_field_ids)
        self.assertNotIn("security_compliance", schema_field_ids)
        self.assertTrue(
            all(schema_field_id.startswith("direction_") for schema_field_id in schema_field_ids)
        )

    def test_planning_agent_injects_directions_into_research_plan(self):
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
        analysis_dimensions = result["analysis_dimensions"]
        schema_field_ids = [
            schema_field_id
            for dimension in analysis_dimensions
            for schema_field_id in dimension["schema_field_ids"]
        ]

        self.assertEqual(
            result["industry_direction_plan"]["industry"]["industry_id"],
            "ecommerce_retail",
        )
        self.assertIn("direction_user_direction_1", schema_field_ids)
        self.assertIn(
            "direction_platform_supply_demand_liquidity",
            schema_field_ids,
        )
        self.assertEqual(result["messages"][-1]["type"], "research_plan")
        self.assertIn(
            "industry_direction_plan",
            result["messages"][-1]["payload"],
        )
        user_dimension = next(
            dimension
            for dimension in analysis_dimensions
            if dimension["id"] == "user_direction_1"
        )
        self.assertEqual(user_dimension["schema_field_ids"], ["direction_user_direction_1"])
        self.assertEqual(
            user_dimension["report_targets"][0]["section_id"],
            "user_direction_1",
        )
        self.assertEqual(
            result["messages"][-1]["payload"]["analysis_dimensions"],
            analysis_dimensions,
        )
        monetization_dimension = next(
            dimension
            for dimension in analysis_dimensions
            if dimension["id"] == "take_rate_monetization_governance"
        )
        self.assertIn("pricing_page", monetization_dimension["source_hints"])

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

    def test_planning_trace_summarizes_scope_decisions(self):
        state = {
            "task": {
                "query": "对比 ChatGPT、Kimi 和 Perplexity 的 AI 产品体验",
                "competitors": ["ChatGPT", "Kimi", "Perplexity"],
                "custom_analysis_directions": ["搜索体验"],
                "industry_directions_confirmed": True,
            },
            "messages": [],
        }

        inputs = _planning_trace_inputs({"state": state})
        result = asyncio.run(PlanningAgent().run(state))
        outputs = _planning_trace_outputs(result)

        self.assertEqual(inputs["competitors"], ["ChatGPT", "Kimi", "Perplexity"])
        self.assertEqual(inputs["custom_analysis_direction_count"], 1)
        self.assertEqual(outputs["selected_industry"], "ai_product_application")
        self.assertEqual(outputs["message_type"], "research_plan")
        self.assertIn("final_direction_ids", outputs)
        self.assertIn("user_direction_1", outputs["user_added_direction_ids"])


if __name__ == "__main__":
    unittest.main()
