"""Focused tests for collection search query planning."""

from rivalens.agents.search_query_builder import SearchQueryBuilder


def test_ai_capability_queries_preserve_ai_and_pricing_entitlement_terms():
    dimension = {
        "id": "ai_capability_application",
        "name": "AI 能力与应用",
        "type": "analysis_dimension",
        "description": (
            "研究产品内 AI 写作、搜索、总结、自动化、个性化等能力，"
            "以及输出质量、可控性和 AI 加购定价。"
        ),
        "source_hints": ["docs", "pricing_page", "official_site", "review"],
    }

    plan = SearchQueryBuilder().build(
        original_query="分析飞书和钉钉的企业协同竞争格局",
        competitor="飞书",
        dimension=dimension,
        industry_direction_plan={"industry": {"name": "SaaS / 协作文档工具"}},
    )

    assert plan.primary_query == "飞书 AI 功能 文档 定价"
    assert len(plan.search_queries) == 5
    assert all("AI" in query for query in plan.search_queries)
    assert any("会员" in query for query in plan.search_queries)
    assert any("权益" in query for query in plan.search_queries)
    assert any("额度" in query and "点数" in query for query in plan.search_queries)
    assert any("消耗规则" in query for query in plan.search_queries)


def test_non_ai_capability_queries_keep_generic_capability_terms():
    dimension = {
        "id": "core_product_supply",
        "name": "核心产品与供给能力",
        "type": "analysis_dimension",
        "description": "研究核心功能模块、产品形态和供给能力。",
        "source_hints": ["official_site", "docs"],
    }

    plan = SearchQueryBuilder().build(
        original_query="分析飞书和钉钉的企业协同竞争格局",
        competitor="飞书",
        dimension=dimension,
        industry_direction_plan={"industry": {"name": "SaaS / 协作文档工具"}},
    )

    assert plan.primary_query == "飞书 核心产品与供给能力 官网 文档"
    assert all("AI" not in query for query in plan.search_queries)
