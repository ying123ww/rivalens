"""Facet-based industry direction templates.

Industry entries now carry reusable facet tags instead of hand-written per-
industry direction lists. Directions are composed as:

L0 common directions + L1 archetype directions + L2 regulated-domain directions.
"""

from __future__ import annotations

from typing import Any


L0_COMMON_DIRECTIONS: tuple[dict[str, Any], ...] = (
    {
        "direction_id": "strategic_positioning",
        "name": "战略定位与差异化",
        "reason": "研究竞品定位、市场卡位、差异化叙事和品牌主张，避免只比较功能而忽略竞争语境。",
        "source_hints": ["official_site", "news", "analyst_report", "social"],
        "required": True,
    },
    {
        "direction_id": "target_users_segments",
        "name": "目标用户与细分场景",
        "reason": "研究目标人群、典型使用场景、用户画像和细分市场，明确竞品服务谁以及为什么被选择。",
        "source_hints": ["official_site", "review", "social", "news"],
        "required": True,
    },
    {
        "direction_id": "core_product_supply",
        "name": "核心产品与供给能力",
        "reason": "研究产品本体、核心功能、能力深度、能力边界和供给质量，建立功能与供给侧对比基础。",
        "source_hints": ["official_site", "docs", "marketplace", "review"],
        "required": True,
    },
    {
        "direction_id": "product_experience",
        "name": "交互与产品体验",
        "reason": "研究关键任务流程、界面操作体验、信息架构，以及移动端、桌面端等多端体验差异。",
        "source_hints": ["official_site", "docs", "review", "social"],
        "required": True,
    },
    {
        "direction_id": "ai_capability_application",
        "name": "AI 能力与应用",
        "reason": "研究产品内 AI 写作、搜索、总结、自动化、个性化等能力，以及输出质量、可控性和 AI 加购定价。",
        "source_hints": ["official_site", "docs", "pricing_page", "benchmark", "review"],
        "required": True,
    },
    {
        "direction_id": "business_model_pricing",
        "name": "商业模式与定价",
        "reason": "研究赚钱方式、定价套餐、收费单位、变现路径、成本结构和单位经济学。",
        "source_hints": ["pricing_page", "official_site", "financial_filing", "news"],
        "required": True,
    },
    {
        "direction_id": "growth_channels",
        "name": "增长与渠道获客",
        "reason": "研究获客方式、主要渠道、增长打法、留存机制和复购机制。",
        "source_hints": ["official_site", "news", "social", "review"],
        "required": True,
    },
    {
        "direction_id": "operations_fulfillment",
        "name": "运营与履约",
        "reason": "研究关键业务如何运转、核心流程、交付方式和服务履约能力。",
        "source_hints": ["official_site", "docs", "review", "news"],
        "required": True,
    },
    {
        "direction_id": "baseline_trust_security_compliance",
        "name": "信任·安全·合规（基线）",
        "reason": "研究隐私、数据安全、权限、通用合规和采购信任门槛，不覆盖行业特有监管义务。",
        "source_hints": ["trust_center", "official_site", "docs", "standards_body"],
        "required": True,
    },
    {
        "direction_id": "user_reputation",
        "name": "用户口碑与体验",
        "reason": "研究公开评价、真实痛点、满意度和官网之外的用户反馈。",
        "source_hints": ["review", "social", "marketplace", "complaint_database"],
        "required": True,
    },
    {
        "direction_id": "moat_resources_team",
        "name": "壁垒·资源·团队",
        "reason": "研究护城河、网络效应、转换成本、关键资源、团队背景、融资和资源禀赋。",
        "source_hints": ["news", "financial_filing", "job_posting", "official_site"],
        "required": True,
    },
    {
        "direction_id": "market_trends_opportunities",
        "name": "市场趋势与机会信号",
        "reason": "行业级方向：研究市场规模、融资动态、政策变化、招聘扩张和新进入者信号，为机会与市场格局章节提供来源。",
        "source_hints": ["analyst_report", "news", "financial_filing", "job_posting"],
        "required": True,
    },
)


L1_ARCHETYPE_DIRECTIONS: dict[str, tuple[dict[str, Any], ...]] = {
    "two_sided_platform": (
        {
            "direction_id": "platform_supply_demand_liquidity",
            "name": "双边供需与流动性",
            "reason": "研究供给侧和需求侧规模、匹配效率与流动性，这是平台型业务的核心竞争支点。",
            "source_hints": ["marketplace", "official_site", "news", "review"],
            "required": True,
        },
        {
            "direction_id": "take_rate_monetization_governance",
            "name": "抽佣率与变现治理",
            "reason": "研究抽佣率、佣金费率结构和平台变现方式，判断平台商业化强度与供需两侧负担。",
            "source_hints": ["pricing_page", "official_site", "financial_filing", "docs"],
            "required": True,
        },
        {
            "direction_id": "platform_trust_dispute_governance",
            "name": "平台信任与纠纷治理",
            "reason": "研究假货治理、内容或卖家审核、纠纷处理、投诉机制和平台信任基础设施。",
            "source_hints": ["official_site", "docs", "review", "complaint_database", "news"],
            "required": True,
        },
        {
            "direction_id": "traffic_distribution_ad_monetization",
            "name": "流量分发与广告变现",
            "reason": "研究搜索推荐排序、付费广告、竞价、促销会员倾斜和流量分配机制。",
            "source_hints": ["official_site", "docs", "pricing_page", "marketplace"],
            "required": True,
        },
    ),
    "saas_subscription": (
        {
            "direction_id": "integrations_ecosystem",
            "name": "集成与生态",
            "reason": "研究第三方集成、API、插件、模板生态和工作流嵌入能力。",
            "source_hints": ["docs", "marketplace", "official_site", "review"],
            "required": True,
        },
        {
            "direction_id": "migration_switching_cost",
            "name": "迁移与转换成本",
            "reason": "研究数据导出自由度、迁入迁出难度、用户锁定程度和长期粘性。",
            "source_hints": ["docs", "official_site", "review", "social"],
            "required": True,
        },
        {
            "direction_id": "sla_reliability",
            "name": "SLA 与可靠性",
            "reason": "研究服务等级协议、状态页、可用性、限流、事故记录和企业支持承诺。",
            "source_hints": ["status_page", "trust_center", "docs", "news", "review"],
            "required": True,
        },
    ),
    "transaction_fulfillment": (
        {
            "direction_id": "supply_chain_inventory",
            "name": "供应链与库存",
            "reason": "研究采购、库存、货源组织和供应稳定性。",
            "source_hints": ["official_site", "financial_filing", "news", "job_posting"],
            "required": True,
        },
        {
            "direction_id": "fulfillment_speed_coverage",
            "name": "履约时效与覆盖",
            "reason": "研究配送时效、覆盖范围、服务承诺和履约能力。",
            "source_hints": ["official_site", "docs", "review", "news"],
            "required": True,
        },
        {
            "direction_id": "returns_after_sales",
            "name": "退换货与售后",
            "reason": "研究退货退款流程、换货、售后服务和质量问题处理。",
            "source_hints": ["official_site", "docs", "review", "complaint_database"],
            "required": True,
        },
    ),
    "hardware_manufacturing": (
        {
            "direction_id": "manufacturing_supply_capacity",
            "name": "供应链与产能",
            "reason": "研究产能、交付周期、供应稳定性、关键零部件和制造组织能力。",
            "source_hints": ["official_site", "financial_filing", "news", "job_posting"],
            "required": True,
        },
        {
            "direction_id": "warranty_after_sales_network",
            "name": "质保与售后网络",
            "reason": "研究保修政策、线下售后、服务网络、维修体验和召回处理。",
            "source_hints": ["official_site", "docs", "review", "complaint_database"],
            "required": True,
        },
        {
            "direction_id": "hardware_specs_iteration",
            "name": "硬件规格与迭代",
            "reason": "研究关键规格参数、产品代际迭代、性能指标和发布节奏。",
            "source_hints": ["official_site", "docs", "review", "benchmark"],
            "required": True,
        },
    ),
    "content_media": (
        {
            "direction_id": "content_supply_ip_rights",
            "name": "内容供给与版权",
            "reason": "研究内容来源、版权、IP、授权和内容供给深度。",
            "source_hints": ["official_site", "news", "docs", "marketplace"],
            "required": True,
        },
        {
            "direction_id": "creator_distribution_ecosystem",
            "name": "创作者与分发生态",
            "reason": "研究创作者激励、内容分发、发行渠道、伙伴生态和内容生产机制。",
            "source_hints": ["official_site", "news", "social", "marketplace"],
            "required": True,
        },
        {
            "direction_id": "recommendation_engagement_mechanics",
            "name": "推荐与活跃机制",
            "reason": "研究推荐算法、活跃度、沉浸式体验机制、社区互动和留存机制。",
            "source_hints": ["official_site", "docs", "review", "social"],
            "required": True,
        },
    ),
    "api_infrastructure": (
        {
            "direction_id": "performance_rate_limits",
            "name": "性能与限流",
            "reason": "研究延迟、吞吐、速率限制、并发能力和生产环境性能约束。",
            "source_hints": ["docs", "status_page", "benchmark", "review"],
            "required": True,
        },
        {
            "direction_id": "metering_usage_billing",
            "name": "计量与计费",
            "reason": "研究用量计量、按量计费、token 或请求定价、账单透明度和成本控制。",
            "source_hints": ["pricing_page", "docs", "official_site", "review"],
            "required": True,
        },
        {
            "direction_id": "developer_docs_ecosystem",
            "name": "开发者生态与文档",
            "reason": "研究文档、SDK、示例、控制台、部署方式、开发者社区和接入体验。",
            "source_hints": ["docs", "official_site", "marketplace", "social"],
            "required": True,
        },
        {
            "direction_id": "capability_quality_evaluation",
            "name": "能力·质量·评测",
            "reason": "研究能力边界、服务质量、公开评测、基准表现和能力型产品的质量证据。",
            "source_hints": ["benchmark", "docs", "official_site", "analyst_report", "news"],
            "required": True,
        },
    ),
}


L2_REGULATED_DOMAIN_DIRECTIONS: dict[str, tuple[dict[str, Any], ...]] = {
    "finance": (
        {
            "direction_id": "financial_licenses_qualifications",
            "name": "牌照与监管资质",
            "reason": "研究经营牌照、监管许可、注册范围和公开资质，验证金融业务合法展业边界。",
            "source_hints": ["regulator_database", "public_registry", "official_site", "docs"],
            "required": True,
        },
        {
            "direction_id": "aml_kyc_sanctions",
            "name": "反洗钱·KYC·制裁筛查",
            "reason": "研究反洗钱、客户身份核验、制裁名单筛查和商户审核机制。",
            "source_hints": ["regulator_database", "standards_body", "official_site", "docs", "news"],
            "required": True,
        },
        {
            "direction_id": "customer_fund_safeguarding",
            "name": "客户资金隔离与保障",
            "reason": "研究备付金、资金隔离、托管账户、赔付机制和用户资金保障披露。",
            "source_hints": ["regulator_database", "financial_filing", "official_site", "docs"],
            "required": True,
        },
    ),
    "healthcare": (
        {
            "direction_id": "medical_regulatory_access",
            "name": "医疗资质与监管准入",
            "reason": "研究医疗经营资质、审批路径、执业许可和监管准入条件。",
            "source_hints": ["regulator_database", "public_registry", "official_site", "docs", "news"],
            "required": True,
        },
        {
            "direction_id": "clinical_evidence_effectiveness",
            "name": "临床证据与有效性",
            "reason": "研究临床证据、疗效、准确性、有效性和医疗价值证明。",
            "source_hints": ["docs", "case_study", "official_site", "analyst_report", "news"],
            "required": True,
        },
        {
            "direction_id": "phi_health_data_security",
            "name": "PHI 隐私与健康数据安全",
            "reason": "研究患者健康信息隐私、健康数据安全、访问控制、加密、审计和泄露披露。",
            "source_hints": ["trust_center", "standards_body", "official_site", "docs", "news"],
            "required": True,
        },
    ),
    "food": (
        {
            "direction_id": "food_safety_labeling_claims",
            "name": "食品安全·标签·健康声明",
            "reason": "研究食品安全、标签规范、营养与健康声明合规，以及门店或产品质量要求。",
            "source_hints": ["regulator_database", "standards_body", "official_site", "news", "review"],
            "required": True,
        },
        {
            "direction_id": "food_recall_quality_incidents",
            "name": "食品召回与质量事件",
            "reason": "研究召回记录、质量安全事件、投诉和监管处罚。",
            "source_hints": ["regulator_database", "incident_database", "news", "complaint_database"],
            "required": True,
        },
    ),
    "automotive": (
        {
            "direction_id": "vehicle_recalls_safety_ratings",
            "name": "召回与安全评级",
            "reason": "研究召回记录、安全评级、事故披露和安全缺陷处理。",
            "source_hints": ["regulator_database", "incident_database", "news", "official_site"],
            "required": True,
        },
        {
            "direction_id": "emissions_certification",
            "name": "排放与认证",
            "reason": "研究排放标准、产品认证、准入要求和区域合规披露。",
            "source_hints": ["regulator_database", "standards_body", "official_site", "docs"],
            "required": True,
        },
    ),
    "transportation": (
        {
            "direction_id": "transport_operating_authority",
            "name": "运营资质与授权",
            "reason": "研究运营牌照、经营授权、承运资质、保险和跨境或区域许可。",
            "source_hints": ["public_registry", "regulator_database", "official_site", "docs"],
            "required": True,
        },
        {
            "direction_id": "transport_safety_compliance",
            "name": "运输安全合规",
            "reason": "研究运输安全记录、事故、检查、处罚和合规运行情况。",
            "source_hints": ["incident_database", "regulator_database", "official_site", "news"],
            "required": True,
        },
    ),
    "real_estate": (
        {
            "direction_id": "fair_housing_advertising_compliance",
            "name": "公平住房与广告合规",
            "reason": "研究公平住房法规、反歧视、房产广告、费用披露和平台展示合规。",
            "source_hints": ["regulator_database", "public_registry", "official_site", "docs", "news"],
            "required": True,
        },
        {
            "direction_id": "tenant_screening_compliance",
            "name": "租客筛选合规",
            "reason": "研究租客背调、信用报告、收入验证、申请费和筛选流程合规。",
            "source_hints": ["regulator_database", "official_site", "pricing_page", "docs", "review"],
            "required": True,
        },
    ),
    "education": (
        {
            "direction_id": "student_privacy_accessibility",
            "name": "学生隐私与无障碍合规",
            "reason": "研究学生隐私、儿童数据保护、无障碍可访问性和学校采购合规。",
            "source_hints": ["regulator_database", "standards_body", "trust_center", "official_site", "docs"],
            "required": True,
        },
    ),
    "content_regulation": (
        {
            "direction_id": "content_licenses_access",
            "name": "内容牌照与资质准入",
            "reason": "研究游戏版号、网络视听许可、内容牌照、备案和资质准入要求。",
            "source_hints": ["regulator_database", "public_registry", "official_site", "news"],
            "required": True,
        },
        {
            "direction_id": "content_moderation_minor_protection",
            "name": "内容审核与未成年人保护",
            "reason": "研究内容审核机制、未成年人保护、防沉迷、违规处理和社区安全治理。",
            "source_hints": ["regulator_database", "official_site", "docs", "news", "review"],
            "required": True,
        },
    ),
}


_INDUSTRY_FACETS: tuple[dict[str, Any], ...] = (
    {
        "industry_id": "saas_collaboration",
        "name": "SaaS / 协作文档工具",
        "gics_sector": "information_technology",
        "archetypes": ["saas_subscription"],
        "regulated_domains": [],
        "aliases": ["互联网", "saas", "software", "订阅", "协作", "效率", "云服务", "文档", "知识库", "project management"],
        "known_competitors": ["notion", "slack", "zoom", "asana", "monday", "airtable", "飞书", "钉钉"],
    },
    {
        "industry_id": "ecommerce_retail",
        "name": "电商 / 零售",
        "gics_sector": "consumer_discretionary",
        "archetypes": ["two_sided_platform", "transaction_fulfillment"],
        "regulated_domains": [],
        "aliases": ["电商", "零售", "retail", "marketplace", "d2c", "新零售", "商城", "卖家", "商家"],
        "known_competitors": ["amazon", "shopify", "walmart", "淘宝", "京东", "拼多多", "抖音电商"],
    },
    {
        "industry_id": "financial_services",
        "name": "金融 / 支付 / Fintech",
        "gics_sector": "financials",
        "archetypes": ["api_infrastructure", "saas_subscription"],
        "regulated_domains": ["finance"],
        "aliases": ["金融", "经济服务", "fintech", "支付", "银行", "理财", "保险", "风控", "payment"],
        "known_competitors": ["stripe", "paypal", "wise", "adyen", "square", "支付宝", "微信支付", "陆金所"],
    },
    {
        "industry_id": "edtech",
        "name": "教育科技 / 在线学习",
        "gics_sector": "consumer_discretionary",
        "archetypes": ["saas_subscription", "content_media"],
        "regulated_domains": ["education"],
        "aliases": ["教育", "edtech", "在线课程", "学习", "培训", "教培", "lms", "课程"],
        "known_competitors": ["coursera", "duolingo", "udemy", "kahoot", "作业帮", "猿辅导", "学而思"],
    },
    {
        "industry_id": "healthcare",
        "name": "医疗健康",
        "gics_sector": "health_care",
        "archetypes": ["saas_subscription", "two_sided_platform"],
        "regulated_domains": ["healthcare"],
        "aliases": ["医疗", "医药", "健康", "healthcare", "medical", "clinic", "patient", "医生", "医院"],
        "known_competitors": ["teladoc", "zocdoc", "epic", "平安好医生", "丁香园", "微医"],
    },
    {
        "industry_id": "travel_mobility",
        "name": "旅游出行",
        "gics_sector": "consumer_discretionary",
        "archetypes": ["two_sided_platform"],
        "regulated_domains": [],
        "aliases": ["旅游", "出行", "travel", "hotel", "flight", "ota", "booking", "机票", "酒店"],
        "known_competitors": ["booking", "airbnb", "expedia", "trip.com", "携程", "飞猪", "美团旅行"],
    },
    {
        "industry_id": "local_services",
        "name": "本地生活 / 到店到家",
        "gics_sector": "consumer_discretionary",
        "archetypes": ["two_sided_platform", "transaction_fulfillment"],
        "regulated_domains": ["food"],
        "aliases": ["本地生活", "到店", "到家", "外卖", "餐饮平台", "local services", "delivery"],
        "known_competitors": ["美团", "饿了么", "doordash", "uber eats", "大众点评"],
    },
    {
        "industry_id": "gaming_entertainment",
        "name": "游戏 / 娱乐 / 内容平台",
        "gics_sector": "communication_services",
        "archetypes": ["content_media"],
        "regulated_domains": ["content_regulation"],
        "aliases": ["游戏", "娱乐", "内容平台", "视频", "直播", "game", "gaming", "streaming", "ugc"],
        "known_competitors": ["tencent games", "网易游戏", "bilibili", "抖音", "youtube", "netflix", "roblox"],
    },
    {
        "industry_id": "automotive_ev",
        "name": "汽车 / 新能源",
        "gics_sector": "consumer_discretionary",
        "archetypes": ["hardware_manufacturing"],
        "regulated_domains": ["automotive"],
        "aliases": ["汽车", "新能源", "ev", "电动车", "智能座舱", "自动驾驶", "充电", "车企"],
        "known_competitors": ["tesla", "byd", "比亚迪", "蔚来", "小鹏", "理想", "宝马"],
    },
    {
        "industry_id": "enterprise_b2b_software",
        "name": "企业服务 / B2B 软件",
        "gics_sector": "information_technology",
        "archetypes": ["saas_subscription"],
        "regulated_domains": [],
        "aliases": ["企业服务", "b2b", "企业软件", "crm", "erp", "营销自动化", "sales software"],
        "known_competitors": ["salesforce", "hubspot", "servicenow", "workday", "用友", "金蝶"],
    },
    {
        "industry_id": "consumer_food",
        "name": "消费品 / 餐饮",
        "gics_sector": "consumer_staples",
        "archetypes": ["transaction_fulfillment"],
        "regulated_domains": ["food"],
        "aliases": ["消费品", "餐饮", "fmcg", "饮料", "食品", "连锁餐饮", "咖啡", "茶饮"],
        "known_competitors": ["starbucks", "luckin", "瑞幸", "喜茶", "蜜雪冰城", "nike", "lululemon"],
    },
    {
        "industry_id": "real_estate_property",
        "name": "房地产 / 物业 / 租赁",
        "gics_sector": "real_estate",
        "archetypes": ["two_sided_platform"],
        "regulated_domains": ["real_estate"],
        "aliases": ["房地产", "物业", "地产", "租房", "长租", "写字楼", "real estate", "property", "房源"],
        "known_competitors": ["链家", "贝壳", "万科", "碧桂园服务", "绿城服务", "wework", "zillow"],
    },
    {
        "industry_id": "logistics_supply_chain",
        "name": "物流 / 供应链",
        "gics_sector": "industrials",
        "archetypes": ["transaction_fulfillment"],
        "regulated_domains": ["transportation"],
        "aliases": ["物流", "供应链", "快递", "仓储", "货运", "supply chain", "logistics", "履约"],
        "known_competitors": ["顺丰", "京东物流", "菜鸟", "dhl", "fedex", "满帮"],
    },
    {
        "industry_id": "ai_model_platform",
        "name": "AI 模型平台 / 大模型 API",
        "gics_sector": "information_technology",
        "archetypes": ["api_infrastructure"],
        "regulated_domains": [],
        "aliases": ["大模型", "llm", "模型", "模型平台", "基础模型", "模型 api", "api 平台", "openai api", "claude api", "gemini api", "deepseek api"],
        "known_competitors": ["openai", "anthropic", "claude api", "gemini", "deepseek", "通义", "文心"],
    },
    {
        "industry_id": "ai_product_application",
        "name": "AI 产品 / 智能应用",
        "gics_sector": "information_technology",
        "archetypes": ["saas_subscription"],
        "regulated_domains": [],
        "aliases": ["ai产品", "ai 产品", "ai应用", "ai 应用", "ai工具", "ai 工具", "ai助手", "ai 助手", "智能体", "agent", "copilot", "聊天机器人", "搜索引擎", "代码助手", "写作助手"],
        "known_competitors": ["chatgpt", "kimi", "perplexity", "cursor", "windsurf", "midjourney", "copilot", "豆包"],
    },
)


def build_facet_directions(
    archetypes: list[str] | tuple[str, ...],
    regulated_domains: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    directions: list[dict[str, Any]] = [dict(direction) for direction in L0_COMMON_DIRECTIONS]
    for archetype in archetypes:
        directions.extend(dict(direction) for direction in L1_ARCHETYPE_DIRECTIONS.get(archetype, ()))
    for regulated_domain in regulated_domains:
        directions.extend(
            dict(direction)
            for direction in L2_REGULATED_DOMAIN_DIRECTIONS.get(regulated_domain, ())
        )

    deduped: dict[str, dict[str, Any]] = {}
    for direction in directions:
        deduped[str(direction["direction_id"])] = direction
    return list(deduped.values())


INDUSTRY_DIRECTION_TEMPLATES = [
    {
        **template,
        "direction_model": "facet_l0_l1_l2",
        "directions": build_facet_directions(
            template.get("archetypes", []),
            template.get("regulated_domains", []),
        ),
    }
    for template in _INDUSTRY_FACETS
]
