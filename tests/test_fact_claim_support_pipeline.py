"""Focused tests for the KnowledgeFact -> AnalysisClaim -> support gate path."""

import asyncio

from rivalens.agents.analysis import AnalysisAgent
from rivalens.agents.claim_support import ClaimSupportReviewer
from rivalens.agents.knowledge_structuring import KnowledgeStructuringAgent
from rivalens.agents.writing import ReportWriterAgent
from rivalens.workflows.competitive_analysis import _route_after_claim_support


def _combined_pricing_evidence():
    return [
        {
            "id": "ev_pricing",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": (
                "Free plan available. Pro is $20/user/month. "
                "Enterprise is quote-only. Usage-based billing is available. "
                "Annual billing gets 20% off."
            ),
            "url": "https://acme.example/pricing",
            "confidence": 0.9,
        }
    ]


def test_knowledge_structuring_uses_rule_extractor_metadata():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_1",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
            "url": "https://acme.example/pricing",
            "confidence": 0.8,
        }
    ]

    facts, metadata = agent._build_knowledge_facts_with_metadata(evidence)

    assert metadata["source"] == "rule"
    assert metadata["knowledge_fact_count"] == 1
    assert metadata["rule_input_evidence_count"] == 1
    assert metadata["rule_skipped_evidence_count"] == 0
    assert facts[0]["fact_type"] == "pricing_signal"
    assert facts[0]["subject"] == "Acme Pricing Model"
    assert facts[0]["evidence_ids"] == ["ev_1"]
    assert facts[0]["normalized_key"]


def test_rule_extraction_skips_javascript_fallback_noise():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_js",
            "competitor": "Acme",
            "analysis_dimension_id": "core_product_supply",
            "dimension_name": "Core product supply",
            "source_type": "official_site",
            "title": "Acme App",
            "excerpt": "You need to enable JavaScript to run this app.",
            "url": "https://acme.example/app",
        },
    ]

    facts, metadata = agent._build_knowledge_facts_with_metadata(evidence)

    assert facts == []
    assert metadata["rule_skipped_evidence_count"] == 1
    assert metadata["rule_semantic_noise_count"] == 1


def test_rule_extraction_selects_concrete_sentence_after_boilerplate():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_ai",
            "competitor": "飞书",
            "analysis_dimension_id": "ai_capability_application",
            "dimension_name": "AI 能力应用",
            "source_type": "official_site",
            "title": "飞书智能伙伴",
            "excerpt": (
                "登录 注册 下载 免费试用 联系销售。"
                "以下内容由 AI 匹配目标关键词生成。"
                "智能伙伴创建平台采用运行额度作为计费单元，首次开通赠送 20,000 运行额度。"
                "热门推荐 案例与方案 产品功能 本文目录。"
            ),
            "url": "https://feishu.example/ai",
            "confidence": 0.9,
        }
    ]

    facts, metadata = agent._build_knowledge_facts_with_metadata(evidence)

    assert len(facts) == 1
    assert facts[0]["object"] == (
        "智能伙伴创建平台采用运行额度作为计费单元，首次开通赠送 20,000 运行额度。"
    )
    assert "登录" not in facts[0]["object"]
    assert "AI 匹配目标关键词" not in facts[0]["object"]
    assert metadata["rule_sentence_selected_count"] == 1


def test_rule_extraction_skips_download_directory_noise():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_download",
            "competitor": "钉钉",
            "analysis_dimension_id": "product_experience",
            "dimension_name": "产品体验",
            "source_type": "other",
            "title": "路行钉钉虚拟定位app下载安卓手机版",
            "excerpt": (
                "路行钉钉虚拟定位app下载安卓手机版 最新版下载2025 "
                "当前位置：首页 手机应用 安卓系统 应用类型：辅助工具 请先登录"
            ),
            "url": "https://download.example/dingtalk-helper",
        }
    ]

    facts, metadata = agent._build_knowledge_facts_with_metadata(evidence)

    assert facts == []
    assert metadata["rule_skipped_evidence_count"] == 1
    assert metadata["rule_semantic_noise_count"] == 1


def test_knowledge_structuring_enriches_top_evidence_snippets():
    agent = KnowledgeStructuringAgent()
    state = {
        "task": {"query": "Compare Acme pricing.", "competitors": ["Acme"]},
        "competitors": ["Acme"],
        "research_branches": [
            {
                "id": "collect_acme_pricing_model",
                "competitor": "Acme",
                "dimension_id": "pricing_model",
                "dimension_name": "Pricing Model",
                "success_criteria": [
                    {
                        "id": "pricing_content",
                        "description": "Identify public pricing plans and billing.",
                    }
                ],
            }
        ],
        "evidence_reviews": [
            {
                "id": "ev_review_pricing",
                "branch_id": "collect_acme_pricing_model",
                "accepted_evidence_ids": ["ev_1"],
                "rejected_evidence_ids": [],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "branch_id": "collect_acme_pricing_model",
                "analysis_dimension_id": "pricing_model",
                "dimension_name": "Pricing Model",
                "source_type": "pricing_page",
                "title": "Acme Pricing",
                "excerpt": (
                    "Acme launched a new enterprise product. "
                    "Acme offers Free, Pro, and Enterprise plans with monthly billing. "
                    "The company also announced new integrations."
                ),
                "url": "https://acme.example/pricing",
                "success_criterion_ids": ["pricing_content"],
                "confidence": 0.9,
            }
        ],
    }

    result = asyncio.run(agent.run(state))
    evidence = result["evidence_items"][0]
    snippets = evidence["evidence_snippets"]

    assert snippets
    assert snippets[0]["success_criterion_id"] == "pricing_content"
    assert snippets[0]["rank"] == 1
    assert "plans with monthly billing" in snippets[0]["text"]
    assert set(snippets[0]["matched_terms"]).intersection({"plans", "billing"})
    assert result["agent_events"][-1]["output"]["evidence_snippet_count"] >= 1
    assert result["agent_events"][-1]["output"]["knowledge_fact_source"] == "rule"


def test_competitor_profile_evidence_fills_canonical_website():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_registry",
            "competitor": "飞书",
            "analysis_dimension_id": "competitor_profile",
            "source_type": "public_registry",
            "title": "飞书企业信息公开登记",
            "excerpt": "公开登记资料描述飞书相关主体。",
            "url": "https://registry.example/feishu",
            "confidence": 0.96,
        },
        {
            "id": "ev_official",
            "competitor": "飞书",
            "analysis_dimension_id": "competitor_profile",
            "source_type": "other",
            "title": "OpenClaw - 飞书官网",
            "excerpt": "飞书官网公开介绍产品和品牌信息。",
            "url": "https://www.feishu.cn/content/article/example?utm_source=search",
            "confidence": 0.72,
        },
    ]

    enriched = agent._enrich_competitors(
        [{"name": "飞书"}],
        evidence,
        {"industry": {"name": "协同办公"}},
    )

    assert enriched[0]["website"] == "https://www.feishu.cn"
    assert enriched[0]["category"] == "协同办公"
    assert enriched[0]["evidence_ids"] == ["ev_registry", "ev_official"]
    assert "飞书官网" in enriched[0]["notes"]


def test_competitor_profile_registry_evidence_does_not_fill_website():
    agent = KnowledgeStructuringAgent()

    enriched = agent._enrich_competitors(
        [{"name": "Acme"}],
        [
            {
                "id": "ev_registry",
                "competitor": "Acme",
                "analysis_dimension_id": "competitor_profile",
                "source_type": "public_registry",
                "title": "Acme public registry profile",
                "excerpt": "A registry record describes Acme.",
                "url": "https://registry.example/acme",
                "confidence": 0.9,
            }
        ],
        {},
    )

    assert enriched[0]["website"] == ""
    assert enriched[0]["evidence_ids"] == ["ev_registry"]


def test_competitor_profile_page_subdomain_fills_site_root():
    agent = KnowledgeStructuringAgent()

    enriched = agent._enrich_competitors(
        [{"name": "钉钉"}],
        [
            {
                "id": "ev_dingtalk_official",
                "competitor": "钉钉",
                "analysis_dimension_id": "competitor_profile",
                "source_type": "other",
                "title": "企业网盘安全空间-钉盘-钉钉官网",
                "excerpt": "钉钉官网公开介绍钉盘产品能力。",
                "url": "https://page.dingtalk.com/wow/dingtalk/act/clouddisk",
                "confidence": 0.78,
            }
        ],
        {},
    )

    assert enriched[0]["website"] == "https://dingtalk.com"
    assert enriched[0]["evidence_ids"] == ["ev_dingtalk_official"]


def test_knowledge_structuring_splits_pricing_evidence_into_atom_facts():
    agent = KnowledgeStructuringAgent()

    facts = agent._build_knowledge_facts(_combined_pricing_evidence())

    atom_kinds = sorted(
        (fact.get("qualifiers", {}) or {}).get("pricing_atom_kind", "")
        for fact in facts
    )
    assert atom_kinds == sorted(
        [
            "free_tier",
            "published_plan_price",
            "quote_only",
            "usage_based_billing",
            "annual_discount",
        ]
    )
    assert len(facts) == 5
    assert {
        fact["predicate"]
        for fact in facts
    } == {
        "exists",
        "publishes_price",
        "requires_quote",
        "uses_billing_model",
        "offers_discount",
    }
    assert all(fact["evidence_ids"] == ["ev_pricing"] for fact in facts)


def test_knowledge_structuring_keeps_multiple_published_price_atoms():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_project_pricing",
            "competitor": "飞书",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "商业模式与定价",
            "source_type": "pricing_page",
            "title": "飞书项目管理工具收费标准",
            "excerpt": (
                "*所有版本需按年付费 商业版 ¥60/人/月 "
                "旗舰版 ¥80/人/月 核心功能：项目管理全场景覆盖"
            ),
            "url": "https://pricing.example/feishu-project",
            "confidence": 0.9,
        }
    ]

    facts = agent._build_knowledge_facts(evidence)
    objects = sorted(fact["object"] for fact in facts)

    assert "商业版 pricing is ¥60/人/月" in objects
    assert "旗舰版 pricing is ¥80/人/月" in objects


def test_rule_pricing_evidence_reports_atomization_metadata():
    agent = KnowledgeStructuringAgent()

    facts, metadata = agent._build_knowledge_facts_with_metadata(
        _combined_pricing_evidence()
    )

    assert metadata["source"] == "rule"
    assert metadata["knowledge_fact_count"] == 5
    assert metadata["atomization_split_count"] == 5
    assert sorted(
        (fact.get("qualifiers", {}) or {}).get("pricing_atom_kind", "")
        for fact in facts
    ) == sorted(
        [
            "free_tier",
            "published_plan_price",
            "quote_only",
            "usage_based_billing",
            "annual_discount",
        ]
    )


def test_rule_atomic_pricing_fact_is_not_duplicated_by_splitter():
    evidence = [
        {
            "id": "ev_price",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Pro is $20/user/month.",
            "url": "https://acme.example/pricing",
            "confidence": 0.9,
        }
    ]

    facts = KnowledgeStructuringAgent()._build_knowledge_facts(evidence)

    assert len(facts) == 1
    assert facts[0]["predicate"] == "publishes_price"
    assert (facts[0].get("qualifiers", {}) or {}).get("pricing_atom_kind") == (
        "published_plan_price"
    )


def test_knowledge_structuring_builds_and_merges_fact_atoms():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_1",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
            "url": "https://acme.example/pricing",
            "confidence": 0.8,
        },
        {
            "id": "ev_2",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
            "url": "https://acme.example/pricing?ref=copy",
            "confidence": 0.9,
        },
    ]

    facts = agent._build_knowledge_facts(evidence)

    assert len(facts) == 1
    fact = facts[0]
    assert fact["fact_type"] == "pricing_signal"
    assert fact["subject"]
    assert fact["predicate"] == "publishes"
    assert fact["object"]
    assert fact["normalized_key"]
    assert fact["evidence_ids"] == ["ev_1", "ev_2"]


def test_analysis_groups_fact_atoms_into_one_traceable_claim():
    agent = AnalysisAgent()
    facts = [
        {
            "id": "fact_1",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "fact_type": "pricing_signal",
            "subject": "Acme pricing tiers",
            "predicate": "publishes",
            "normalized_key": "acme|pricing_model|pricing_signal|publishes|pricing_tiers",
            "object": "Acme publishes public Pro and Enterprise pricing tiers.",
            "statement": "Acme pricing source publishes public Pro and Enterprise pricing tiers.",
            "evidence_ids": ["ev_1"],
            "confidence": 0.8,
        },
        {
            "id": "fact_2",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "fact_type": "pricing_signal",
            "subject": "Acme pricing tiers",
            "predicate": "publishes",
            "normalized_key": "acme|pricing_model|pricing_signal|publishes|pricing_tiers",
            "object": "Acme shows per-user pricing for paid tiers.",
            "statement": "Acme pricing source publishes per-user pricing for paid tiers.",
            "evidence_ids": ["ev_2"],
            "confidence": 0.9,
        },
    ]
    state = {
        "analysis_dimensions": [
            {"id": "pricing_model", "name": "Pricing Model"},
        ],
    }

    claims = agent._claims_from_knowledge_facts(state, facts)

    assert len(claims) == 1
    claim = claims[0]
    assert claim["claim_source"] == "knowledge_fact_group"
    assert claim["claim_type"] == "pricing_strategy"
    assert claim["claim_risk_level"] == "high"
    assert claim["knowledge_fact_ids"] == ["fact_1", "fact_2"]
    assert claim["evidence_ids"] == ["ev_1", "ev_2"]
    assert "public evidence" in claim["claim"]


def test_analysis_keeps_distinct_pricing_atoms_as_distinct_claims():
    facts = KnowledgeStructuringAgent()._build_knowledge_facts(
        _combined_pricing_evidence()
    )
    state = {
        "analysis_dimensions": [
            {"id": "pricing_model", "name": "Pricing Model"},
        ],
    }

    claims = AnalysisAgent()._claims_from_knowledge_facts(state, facts)

    assert len(claims) == 5
    assert all(len(claim["knowledge_fact_ids"]) == 1 for claim in claims)
    assert len({claim["normalized_key"] for claim in claims}) == 5
    assert not any("multiple pricing signals" in claim["claim"] for claim in claims)


def test_analysis_pricing_claim_includes_specific_price():
    evidence = [
        {
            "id": "ev_project_pricing",
            "competitor": "飞书",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "商业模式与定价",
            "source_type": "pricing_page",
            "title": "飞书项目管理工具收费标准",
            "excerpt": "商业版 ¥60/人/月 旗舰版 ¥80/人/月",
            "url": "https://pricing.example/feishu-project",
            "confidence": 0.9,
        }
    ]
    facts = KnowledgeStructuringAgent()._build_knowledge_facts(evidence)
    state = {
        "analysis_dimensions": [
            {"id": "pricing_model", "name": "商业模式与定价"},
        ],
    }

    claims = AnalysisAgent()._claims_from_knowledge_facts(state, facts)

    assert any("¥60/人/月" in claim["claim"] for claim in claims)
    assert any("¥80/人/月" in claim["claim"] for claim in claims)


def test_claim_support_accepts_supported_fact_bound_claim():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_1",
                "analysis_dimension_id": "pricing_model",
                "knowledge_fact_ids": ["fact_1"],
                "claim": "Acme Pricing Model: public evidence pricing signals Acme publishes public Pro and Enterprise pricing tiers.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_1"],
                "confidence": 0.8,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "object": "Acme publishes public Pro and Enterprise pricing tiers.",
                "statement": "Acme pricing source publishes public Pro and Enterprise pricing tiers.",
                "evidence_ids": ["ev_1"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "supported"
    assert review["recommended_action"] == "accept"
    assert review["claim_risk_level"] == "high"
    assert review["required_follow_up_tasks"] == []
    assert "verification_task_queue" not in result


def test_claim_support_flags_overclaim_and_writer_filters_it():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_1",
                "analysis_dimension_id": "pricing_model",
                "knowledge_fact_ids": ["fact_1"],
                "claim": "Acme is the leading pricing platform with the strongest enterprise advantage.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_1"],
                "confidence": 0.8,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "object": "Acme publishes public Pro and Enterprise pricing tiers.",
                "statement": "Acme pricing source publishes public Pro and Enterprise pricing tiers.",
                "evidence_ids": ["ev_1"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "weak"
    assert review["recommended_action"] == "revise"
    assert review["suggested_revision"]
    assert ReportWriterAgent()._supported_claims(
        state["analysis_claims"],
        result["claim_support_reviews"],
    ) == []


def test_claim_support_flags_pricing_claim_without_available_price_detail():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_price",
                "analysis_dimension_id": "pricing_model",
                "claim_type": "pricing_strategy",
                "claim_risk_level": "high",
                "knowledge_fact_ids": ["fact_price"],
                "claim": "Acme Pricing Model: public evidence contains multiple pricing signals.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_price"],
                "confidence": 0.9,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_price",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "object": "Pro pricing is $20/user/month",
                "statement": "Pro plan publishes pricing at $20/user/month.",
                "evidence_ids": ["ev_price"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_price",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Pro plan is $20/user/month.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "weak"
    assert review["recommended_action"] == "revise"
    assert "$20/user/month" in review["suggested_revision"]


def test_claim_support_accepts_ai_billing_claim_with_usage_quota_details():
    reviewer = ClaimSupportReviewer()
    excerpt = (
        "智能伙伴创建平台采用「运行额度」作为计费单元。首次开通平台时，"
        "我们将赠送 20,000 运行额度。运行额度由「基础运行」和「模型调用」"
        "两部分组成。每次 AI 应用运行调用将固定消耗 1 个运行额度。"
    )
    state = {
        "analysis_claims": [
            {
                "id": "claim_ai_billing",
                "analysis_dimension_id": "ai_capability_application",
                "claim_type": "pricing_strategy",
                "claim_risk_level": "high",
                "knowledge_fact_ids": ["fact_ai_billing"],
                "claim": (
                    "飞书智能伙伴创建平台采用运行额度作为计费单元，首次开通赠送 "
                    "20,000 运行额度；运行额度由基础运行和模型调用两部分组成，"
                    "每次 AI 应用运行调用固定消耗 1 个运行额度。"
                ),
                "competitors": ["飞书"],
                "evidence_ids": ["ev_ai_billing"],
                "confidence": 0.9,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_ai_billing",
                "competitor": "飞书",
                "analysis_dimension_id": "ai_capability_application",
                "object": excerpt,
                "statement": excerpt,
                "evidence_ids": ["ev_ai_billing"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_ai_billing",
                "competitor": "飞书",
                "analysis_dimension_id": "ai_capability_application",
                "title": "智能伙伴创建平台计费说明 - 飞书官网",
                "excerpt": excerpt
                + " 仅飞书超级管理员或拥有费用中心权限的管理员可以执行付费操作。",
                "url": "https://www.feishu.cn/content/1cnvbb55",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "supported"
    assert review["recommended_action"] == "accept"


def test_claim_support_revises_generic_ai_billing_claim_without_quota_details():
    reviewer = ClaimSupportReviewer()
    excerpt = (
        "智能伙伴创建平台采用「运行额度」作为计费单元。首次开通平台时，"
        "我们将赠送 20,000 运行额度。运行额度由「基础运行」和「模型调用」"
        "两部分组成。"
    )
    state = {
        "analysis_claims": [
            {
                "id": "claim_ai_billing_generic",
                "analysis_dimension_id": "ai_capability_application",
                "claim_type": "pricing_strategy",
                "claim_risk_level": "high",
                "knowledge_fact_ids": ["fact_ai_billing"],
                "claim": "飞书 AI 计费有公开信息。",
                "competitors": ["飞书"],
                "evidence_ids": ["ev_ai_billing"],
                "confidence": 0.9,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_ai_billing",
                "competitor": "飞书",
                "analysis_dimension_id": "ai_capability_application",
                "object": excerpt,
                "statement": excerpt,
                "evidence_ids": ["ev_ai_billing"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_ai_billing",
                "competitor": "飞书",
                "analysis_dimension_id": "ai_capability_application",
                "title": "智能伙伴创建平台计费说明 - 飞书官网",
                "excerpt": excerpt,
                "url": "https://www.feishu.cn/content/1cnvbb55",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "weak"
    assert review["recommended_action"] == "revise"
    assert "20,000 运行额度" in review["suggested_revision"]


def test_claim_support_flags_generic_non_pricing_claim_when_details_exist():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_feature",
                "analysis_dimension_id": "ai_capability_application",
                "claim_type": "capability_signal",
                "claim_risk_level": "medium",
                "knowledge_fact_ids": ["fact_feature"],
                "claim": (
                    "飞书 AI capability: public evidence contains multiple "
                    "capability signals for enterprise collaboration."
                ),
                "competitors": ["飞书"],
                "evidence_ids": ["ev_feature"],
                "confidence": 0.86,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_feature",
                "competitor": "飞书",
                "analysis_dimension_id": "ai_capability_application",
                "object": (
                    "飞书People supports talent management, 飞书项目 supports ITR管理, "
                    "and 安全白皮书 3.0 cites ISO 27001 certification."
                ),
                "statement": (
                    "飞书 publishes concrete modules including 飞书People, 飞书项目, "
                    "ITR管理, 安全白皮书 3.0, and ISO 27001."
                ),
                "evidence_ids": ["ev_feature"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_feature",
                "competitor": "飞书",
                "analysis_dimension_id": "ai_capability_application",
                "title": "飞书 People and Project capability pages",
                "excerpt": (
                    "飞书People covers talent management. 飞书项目 supports ITR管理. "
                    "安全白皮书 3.0 cites ISO 27001."
                ),
                "url": "https://example.com/feishu/features",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "weak"
    assert review["recommended_action"] == "revise"
    assert "飞书People" in review["suggested_revision"]
    assert "飞书项目" in review["suggested_revision"]
    assert review["required_follow_up_tasks"] == []


def test_writer_compact_claim_includes_non_pricing_specificity_hints():
    writer = ReportWriterAgent()
    claim = {
        "id": "claim_feature",
        "analysis_dimension_id": "ai_capability_application",
        "knowledge_fact_ids": ["fact_feature"],
        "claim": "飞书 AI capability: public evidence contains multiple capability signals.",
        "competitors": ["飞书"],
        "evidence_ids": ["ev_feature"],
        "confidence": 0.86,
    }
    fact = {
        "id": "fact_feature",
        "object": "飞书People, 飞书项目, ITR管理, 安全白皮书 3.0, ISO 27001",
        "statement": "飞书 publishes concrete capability and security details.",
        "evidence_ids": ["ev_feature"],
    }
    evidence = {
        "id": "ev_feature",
        "title": "飞书 People and Project capability pages",
        "excerpt": "飞书People covers talent management. 飞书项目 supports ITR管理.",
    }

    compact = writer._compact_claim(
        claim,
        {"ev_feature"},
        {"ev_feature": "[1]"},
        {"ev_feature": evidence},
        {"fact_feature": fact},
    )

    assert "飞书People" in compact["specificity_hints"]
    assert "飞书项目" in compact["specificity_hints"]
    assert compact["citation_refs"] == ["[1]"]


def test_analysis_rewrites_claims_from_claim_support_feedback():
    state = {
        "analysis_claims": [
            {
                "id": "claim_price",
                "analysis_dimension_id": "pricing_model",
                "claim": "Acme Pricing Model: public evidence contains multiple pricing signals.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_price"],
                "confidence": 0.9,
            }
        ],
        "claim_support_reviews": [
            {
                "claim_id": "claim_price",
                "recommended_action": "revise",
                "suggested_revision": (
                    "Acme pricing_model: public evidence reports Pro $20/user/month."
                ),
                "confidence": 0.7,
            }
        ],
    }

    result = asyncio.run(AnalysisAgent().run(state))
    claim = result["analysis_claims"][0]

    assert claim["claim"] == "Acme pricing_model: public evidence reports Pro $20/user/month."
    assert claim["confidence"] == 0.7
    assert result["agent_events"][-1]["output"]["claim_granularity"] == (
        "claim_support_revision"
    )


def test_workflow_routes_revision_once_after_claim_support():
    first_review_state = {
        "claim_support_reviews": [
            {
                "claim_id": "claim_price",
                "recommended_action": "revise",
                "suggested_revision": "Acme pricing reports Pro $20/user/month.",
            }
        ],
        "agent_events": [
            {"agent": "claim_support", "action": "review_claim_support"},
        ],
    }
    second_review_state = {
        **first_review_state,
        "agent_events": [
            {"agent": "claim_support", "action": "review_claim_support"},
            {"agent": "claim_support", "action": "review_claim_support"},
        ],
    }

    assert _route_after_claim_support(first_review_state) == "dimension_analysis"
    assert _route_after_claim_support(second_review_state) == "report_writer"


def test_high_risk_claim_without_knowledge_fact_requires_revision_only():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_1",
                "analysis_dimension_id": "pricing_model",
                "claim_type": "pricing_strategy",
                "claim_risk_level": "high",
                "claim": "Acme pricing is cheaper than Beta for enterprise teams.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_1"],
                "confidence": 0.8,
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["claim_risk_level"] == "high"
    assert review["support_status"] == "weak"
    assert review["recommended_action"] == "revise"
    assert review["suggested_revision"]


def test_claim_support_suppresses_claim_without_evidence_binding():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_without_evidence",
                "analysis_dimension_id": "pricing_model",
                "claim_type": "pricing_strategy",
                "claim_risk_level": "high",
                "claim": "Acme pricing is cheaper than Beta.",
                "competitors": ["Acme"],
                "evidence_ids": [],
                "confidence": 0.8,
            }
        ],
        "evidence_items": [],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "unverifiable"
    assert review["recommended_action"] == "suppress"
