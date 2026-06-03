"""Fixed report-section taxonomy and dimension-to-section routing."""

from typing import Any


PRODUCT_ANALYSIS_SECTIONS: list[dict[str, Any]] = [
    {
        "number": "3.1",
        "id": "strategic_positioning",
        "title": "战略定位",
        "guiding_question": "这个产品把自己定位成什么？和竞品的定位差异在哪？",
        "source_constraints": "官网首页、公开采访、品牌宣传",
    },
    {
        "number": "3.2",
        "id": "target_users",
        "title": "目标用户",
        "guiding_question": "这个产品主要服务谁？用户画像是什么？",
        "source_constraints": "官网描述、定价页暗示、公开报道",
    },
    {
        "number": "3.3",
        "id": "business_model",
        "title": "商业模式",
        "guiding_question": "这个产品怎么赚钱？定价策略是什么？",
        "source_constraints": "定价页、公开财务信息",
    },
    {
        "number": "3.4",
        "id": "operation_strategy",
        "title": "运营策略",
        "guiding_question": "这个产品怎么获客、怎么留存、怎么做增长？",
        "source_constraints": "可观察的公开运营动作",
    },
    {
        "number": "3.5",
        "id": "product_features",
        "title": "产品功能",
        "guiding_question": "核心功能有哪些？和竞品功能差异在哪？",
        "source_constraints": "官方文档、功能页、帮助中心",
    },
    {
        "number": "3.6",
        "id": "product_flow",
        "title": "产品流程",
        "guiding_question": "用户的核心使用路径是什么？",
        "source_constraints": "官方文档、教程、演示视频",
    },
    {
        "number": "3.7",
        "id": "product_structure",
        "title": "产品结构",
        "guiding_question": "产品的模块划分和信息架构是什么？",
        "source_constraints": "帮助中心目录、功能导航",
    },
    {
        "number": "3.8",
        "id": "interaction_design",
        "title": "交互设计",
        "guiding_question": "交互有什么特点？体验亮点和不足？",
        "source_constraints": "产品截图、评测文章",
    },
    {
        "number": "3.9",
        "id": "signature_features",
        "title": "特色功能",
        "guiding_question": "有什么独有的、竞品没有的能力？",
        "source_constraints": "官方宣传重点、对比评测",
    },
    {
        "number": "3.10",
        "id": "user_reputation",
        "title": "用户口碑",
        "guiding_question": "用户怎么评价？好评和差评集中在哪？",
        "source_constraints": "搜索API可索引的公开评价（尽力而为）",
    },
]


PRODUCT_SECTION_IDS = tuple(section["id"] for section in PRODUCT_ANALYSIS_SECTIONS)

DEFAULT_DIMENSION_SECTION_ROUTES: dict[str, tuple[str, ...]] = {
    "strategic_positioning": ("strategic_positioning",),
    "direction_strategic_positioning": ("strategic_positioning",),
    "market_trends_opportunities": ("strategic_positioning",),
    "direction_market_trends_opportunities": ("strategic_positioning",),
    "target_users_segments": ("target_users",),
    "direction_target_users_segments": ("target_users",),
    "business_model_pricing": ("business_model",),
    "pricing_business_model": ("business_model",),
    "direction_business_model_pricing": ("business_model",),
    "growth_channels": ("operation_strategy",),
    "direction_growth_channels": ("operation_strategy",),
    "operations_fulfillment": ("operation_strategy", "product_flow"),
    "direction_operations_fulfillment": ("operation_strategy", "product_flow"),
    "core_product_supply": ("product_features", "product_structure"),
    "direction_core_product_supply": ("product_features", "product_structure"),
    "integrations_ecosystem": ("product_features", "product_structure"),
    "direction_integrations_ecosystem": ("product_features", "product_structure"),
    "ai_capability_application": ("product_features", "signature_features"),
    "direction_ai_capability_application": ("product_features", "signature_features"),
    "product_experience": ("product_flow", "product_structure", "interaction_design"),
    "direction_product_experience": ("product_flow", "product_structure", "interaction_design"),
    "baseline_trust_security_compliance": ("product_features", "strategic_positioning", "signature_features"),
    "direction_baseline_trust_security_compliance": ("product_features", "strategic_positioning", "signature_features"),
    "security_compliance": ("product_features", "strategic_positioning"),
    "compliance_risk": ("product_features", "strategic_positioning"),
    "sla_reliability": ("product_features",),
    "direction_sla_reliability": ("product_features",),
    "moat_resources_team": ("strategic_positioning", "signature_features"),
    "direction_moat_resources_team": ("strategic_positioning", "signature_features"),
    "migration_switching_cost": ("product_flow", "user_reputation"),
    "direction_migration_switching_cost": ("product_flow", "user_reputation"),
    "user_reputation": ("user_reputation",),
    "direction_user_reputation": ("user_reputation",),
}


def report_targets_for_dimension(
    dimension_id: str,
    *,
    name: str = "",
    description: str = "",
    source_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    section_ids = _section_ids_for_dimension(
        dimension_id,
        name=name,
        description=description,
        source_hints=source_hints or [],
    )
    return [
        {
            "section_id": section_id,
            "role": "primary" if index == 0 else "secondary",
            "reason": _mapping_reason(section_id, dimension_id, name),
        }
        for index, section_id in enumerate(section_ids)
    ]


def primary_report_section_id(dimension: dict[str, Any]) -> str:
    targets = dimension.get("report_targets", [])
    for target in targets:
        if target.get("role") == "primary" and target.get("section_id") in PRODUCT_SECTION_IDS:
            return target["section_id"]
    if targets and targets[0].get("section_id") in PRODUCT_SECTION_IDS:
        return targets[0]["section_id"]
    return report_targets_for_dimension(
        str(dimension.get("id", "")),
        name=str(dimension.get("name", "")),
        description=str(dimension.get("description", "")),
        source_hints=list(dimension.get("source_hints", []) or []),
    )[0]["section_id"]


def _section_ids_for_dimension(
    dimension_id: str,
    *,
    name: str,
    description: str,
    source_hints: list[str],
) -> tuple[str, ...]:
    for candidate_id in _dimension_id_candidates(dimension_id):
        if candidate_id in DEFAULT_DIMENSION_SECTION_ROUTES:
            return DEFAULT_DIMENSION_SECTION_ROUTES[candidate_id]

    searchable = " ".join(
        [
            dimension_id,
            name,
            description,
            " ".join(source_hints),
        ]
    ).lower()

    keyword_routes: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (("pricing", "price", "monetization", "定价", "收费", "商业模式"), ("business_model",)),
        (("persona", "segment", "customer", "用户", "客户", "画像", "人群"), ("target_users",)),
        (("growth", "channel", "operation", "运营", "增长", "获客", "留存"), ("operation_strategy",)),
        (("workflow", "flow", "onboarding", "tutorial", "流程", "路径", "教程"), ("product_flow",)),
        (("architecture", "module", "navigation", "structure", "结构", "模块", "导航"), ("product_structure",)),
        (("ux", "ui", "interaction", "experience", "体验", "交互"), ("interaction_design",)),
        (("review", "reputation", "complaint", "口碑", "评价", "评论", "投诉"), ("user_reputation",)),
        (("moat", "unique", "differentiation", "差异化", "特色", "独有"), ("signature_features",)),
        (("positioning", "market", "brand", "定位", "市场", "品牌"), ("strategic_positioning",)),
    )
    for keywords, section_ids in keyword_routes:
        if any(keyword in searchable for keyword in keywords):
            return section_ids

    return ("product_features",)


def _dimension_id_candidates(dimension_id: str) -> tuple[str, ...]:
    dimension_id = dimension_id.strip()
    if not dimension_id:
        return ("",)
    candidates = [dimension_id]
    if dimension_id.startswith("direction_"):
        candidates.append(dimension_id.removeprefix("direction_"))
    else:
        candidates.append(f"direction_{dimension_id}")
    return tuple(dict.fromkeys(candidates))


def _mapping_reason(section_id: str, dimension_id: str, name: str) -> str:
    section_title = next(
        (section["title"] for section in PRODUCT_ANALYSIS_SECTIONS if section["id"] == section_id),
        section_id,
    )
    label = name or dimension_id
    return f"{label} 的证据和结论应优先沉淀到第三章「{section_title}」小节。"
