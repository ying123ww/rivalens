"""Planning agent for competitor-analysis tasks."""

from datetime import datetime, timezone
from typing import Any

from rivalens.agents.messages import create_agent_message
from rivalens.file_context import (
    build_file_context,
    file_context_summary,
    get_task_file_references,
)
from rivalens.schema import (
    ActiveKnowledgeSchema,
    AnalysisDimension,
    Competitor,
    CompetitorAnalysisState,
    SchemaExtension,
)
from rivalens.schema_registry import CORE_SCHEMA_FIELDS, SchemaRegistry


DEFAULT_ANALYSIS_DIMENSIONS: list[dict[str, Any]] = [
    {
        "id": "strategic_positioning",
        "name": "战略定位",
        "description": "品牌定位声明、市场细分选择、差异化主张、发展阶段。",
        "priority": "P0",
        "guiding_questions": [
            "各竞品官方的产品定位是什么？",
            "各竞品瞄准的是哪个细分市场？",
            "各竞品强调的核心差异化点是什么？",
            "各竞品目前处于什么发展阶段？",
        ],
    },
    {
        "id": "target_users",
        "name": "目标用户",
        "description": "核心用户群体、典型使用场景、用户规模、购买/使用动机。",
        "priority": "P0",
        "guiding_questions": [
            "产品主要面向哪类用户？",
            "用户在什么场景下使用该产品？",
            "各竞品公开用户量、客户量或装机量是多少？",
            "用户选择该产品的主要动机是什么？",
        ],
    },
    {
        "id": "product_capabilities",
        "name": "产品能力",
        "description": "核心功能、能力边界、体验路径、成熟度和可用性。",
        "priority": "P0",
        "guiding_questions": [
            "核心功能集合分别是什么？",
            "哪些能力是差异化能力？",
            "产品体验路径和使用门槛如何？",
            "功能成熟度和可用性有哪些公开证据？",
        ],
    },
    {
        "id": "pricing_business_model",
        "name": "定价与商业模式",
        "description": "价格、套餐、计费单位、免费层、企业销售和收入模式。",
        "priority": "P0",
        "guiding_questions": [
            "各竞品的公开定价和套餐结构是什么？",
            "计费单位、免费层和企业版策略如何？",
            "商业模式和主要变现路径是什么？",
            "定价差异会如何影响用户选择？",
        ],
    },
    {
        "id": "market_growth",
        "name": "市场与增长",
        "description": "市场覆盖、增长信号、融资/客户扩张、区域布局和增长阶段。",
        "priority": "P1",
        "guiding_questions": [
            "各竞品的市场覆盖和主要区域是什么？",
            "是否有融资、营收、客户增长或下载量等增长信号？",
            "近期增长策略和市场动作是什么？",
            "增长阶段之间有什么差异？",
        ],
    },
    {
        "id": "distribution_channels",
        "name": "渠道与分发",
        "description": "官网、应用商店、合作伙伴、销售渠道、生态入口和获客方式。",
        "priority": "P1",
        "guiding_questions": [
            "各竞品通过哪些渠道触达用户？",
            "是否依赖应用商店、官网、生态市场或合作伙伴？",
            "自助式增长和销售驱动的占比如何？",
            "渠道策略的差异和效果信号是什么？",
        ],
    },
    {
        "id": "customer_proof",
        "name": "客户案例与口碑",
        "description": "客户案例、评价、评论、媒体报道、社区反馈和典型负面反馈。",
        "priority": "P1",
        "guiding_questions": [
            "有哪些公开客户案例或标杆客户？",
            "用户评价中的高频正面反馈是什么？",
            "用户评价中的高频负面反馈是什么？",
            "口碑信号如何支持或削弱其定位？",
        ],
    },
    {
        "id": "technology_integrations",
        "name": "技术与集成",
        "description": "技术架构信号、API、集成生态、数据能力、自动化和平台能力。",
        "priority": "P1",
        "guiding_questions": [
            "是否提供 API、插件、集成或开放平台？",
            "技术能力如何支撑核心产品体验？",
            "数据、自动化或 AI 能力有哪些公开证据？",
            "技术生态和集成覆盖有什么差异？",
        ],
    },
    {
        "id": "compliance_risk",
        "name": "合规与风险",
        "description": "安全合规、隐私、可靠性、监管风险、业务风险和信任建设。",
        "priority": "P1",
        "guiding_questions": [
            "有哪些公开安全、隐私或合规承诺？",
            "是否披露认证、审计、数据保护或可靠性信息？",
            "各竞品面临的主要业务或合规风险是什么？",
            "信任建设能力如何影响竞争位置？",
        ],
    },
    {
        "id": "competitive_moat",
        "name": "竞争壁垒",
        "description": "护城河、替代风险、迁移成本、生态依赖、品牌资产和长期优势。",
        "priority": "P1",
        "guiding_questions": [
            "各竞品的核心壁垒是什么？",
            "用户迁移成本和替代风险如何？",
            "生态、数据、品牌或规模是否形成护城河？",
            "长期竞争优势和短板分别是什么？",
        ],
    },
]


class PlanningAgent:
    def __init__(
        self,
        schema_registry: SchemaRegistry | None = None,
    ):
        self.schema_registry = schema_registry or SchemaRegistry()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        query = task.get("query", "")
        competitors = state.get("competitors") or task.get("competitors") or []

        file_context = state.get("file_context") or build_file_context(
            get_task_file_references(task)
        )
        planning_query = self._planning_query(query, file_context)
        normalized = self._normalize_competitors(competitors)
        active_schema = self._select_active_schema(
            planning_query,
            normalized,
            file_context,
        )
        analysis_dimensions = self._build_analysis_dimensions(
            query,
            normalized,
            active_schema,
        )
        candidate_industries = active_schema.get("candidate_industries", [])
        industry_extensions = active_schema.get("industry_extensions", [])

        research_artifacts = state.get("research_artifacts", []) + [
            {
                "id": "artifact_planning_schema_1",
                "agent": "planner",
                "mode": "schema_selection",
                "query": query,
                "report": (
                    "Selected active knowledge schema "
                    f"{active_schema.get('id', '')} for "
                    f"{active_schema.get('selected_industry', {}).get('name', 'unknown industry')}."
                ),
                "context": {
                    "planning_query": planning_query,
                    "candidate_industries": candidate_industries,
                    "industry_extensions": industry_extensions,
                    "file_context_summary": file_context.get("summary", ""),
                },
                "costs": 0.0,
            },
            {
                "id": "artifact_planning_dimensions_1",
                "agent": "planner",
                "mode": "dimension_confirmation",
                "query": query,
                "report": self._dimension_confirmation_report(analysis_dimensions),
                "context": {
                    "analysis_dimensions": analysis_dimensions,
                    "competitors": normalized,
                    "selected_industry": active_schema.get("selected_industry", {}),
                },
                "costs": 0.0,
            }
        ]
        message = create_agent_message(
            sender="planner",
            receiver="collection",
            message_type="schema_selection",
            payload={
                "active_schema": active_schema,
                "candidate_count": len(candidate_industries),
            },
        )

        return {
            "competitors": normalized,
            "active_knowledge_schema": active_schema,
            "analysis_dimensions": analysis_dimensions,
            "file_context": file_context,
            "research_artifacts": research_artifacts,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "planner",
                    "action": "normalize_scope_and_select_schema",
                    "input": {"query": query, "competitors": competitors},
                    "output": {
                        "competitor_count": len(normalized),
                        "file_count": len(file_context.get("sources", [])),
                        "file_chunk_count": len(file_context.get("chunks", [])),
                        "selected_industry": active_schema.get(
                            "selected_industry",
                            {},
                        ).get("industry_id"),
                        "confidence": active_schema.get("selected_industry", {}).get(
                            "confidence",
                        ),
                        "extension_count": len(industry_extensions),
                        "analysis_dimension_count": len(analysis_dimensions),
                    },
                }
            ],
        }

    def _build_analysis_dimensions(
        self,
        query: str,
        competitors: list[Competitor],
        active_schema: ActiveKnowledgeSchema,
    ) -> list[AnalysisDimension]:
        competitor_names = ", ".join(
            competitor.get("name", "")
            for competitor in competitors
            if competitor.get("name")
        ) or "the target competitors"
        selected_industry = active_schema.get("selected_industry", {}).get(
            "name",
            "unknown industry",
        )
        dimensions: list[AnalysisDimension] = []
        for index, template in enumerate(DEFAULT_ANALYSIS_DIMENSIONS, start=1):
            questions = list(template["guiding_questions"])
            dimensions.append(
                {
                    "id": str(template["id"]),
                    "name": str(template["name"]),
                    "description": str(template["description"]),
                    "priority": str(template["priority"]),
                    "guiding_questions": questions,
                    "search_intent": (
                        f"围绕用户需求“{query}”，比较 {competitor_names} 在"
                        f"“{template['name']}”维度的公开证据。行业背景：{selected_industry}。"
                        f"重点回答：{'；'.join(questions)}"
                    ),
                    **self._dimension_source_policy(str(template["id"])),
                    "rank": index,
                }
            )
        return dimensions

    def _dimension_source_policy(self, dimension_id: str) -> dict[str, Any]:
        policies: dict[str, dict[str, Any]] = {
            "strategic_positioning": {
                "expected_source_types": ["official_site", "blog", "news"],
                "minimum_coverage": ["At least one official positioning or product page when available."],
                "risk_level": "medium",
                "expected_claim_types": ["positioning", "differentiation", "market_segment"],
            },
            "target_users": {
                "expected_source_types": ["official_site", "review", "marketplace"],
                "minimum_coverage": ["At least one user, customer, review, or marketplace signal."],
                "risk_level": "medium",
                "expected_claim_types": ["user_segment", "use_case", "adoption_signal"],
            },
            "product_capabilities": {
                "expected_source_types": ["official_site", "docs", "marketplace"],
                "minimum_coverage": ["At least one official product or documentation source."],
                "risk_level": "medium",
                "expected_claim_types": ["feature", "capability", "maturity_signal"],
            },
            "pricing_business_model": {
                "expected_source_types": ["pricing_page", "official_site", "docs"],
                "minimum_coverage": ["Official pricing, packaging, or billing source required when available."],
                "risk_level": "high",
                "expected_claim_types": ["pricing", "packaging", "billing_unit", "business_model"],
            },
            "market_growth": {
                "expected_source_types": ["news", "blog", "official_site"],
                "minimum_coverage": ["At least one dated growth, customer, funding, or market signal."],
                "risk_level": "high",
                "expected_claim_types": ["growth_signal", "market_presence", "regional_signal"],
            },
            "distribution_channels": {
                "expected_source_types": ["official_site", "marketplace", "docs"],
                "minimum_coverage": ["At least one public distribution, marketplace, or partner-channel source."],
                "risk_level": "medium",
                "expected_claim_types": ["channel", "distribution", "ecosystem"],
            },
            "customer_proof": {
                "expected_source_types": ["review", "official_site", "news"],
                "minimum_coverage": ["At least one customer, review, case-study, or reputation source."],
                "risk_level": "medium",
                "expected_claim_types": ["customer_proof", "review_signal", "case_study"],
            },
            "technology_integrations": {
                "expected_source_types": ["docs", "marketplace", "official_site"],
                "minimum_coverage": ["Documentation, API, integration, or marketplace source required when available."],
                "risk_level": "high",
                "expected_claim_types": ["api", "integration", "platform_capability"],
            },
            "compliance_risk": {
                "expected_source_types": ["docs", "official_site", "news"],
                "minimum_coverage": ["Trust, security, privacy, compliance, or reliability source required when available."],
                "risk_level": "high",
                "expected_claim_types": ["security", "privacy", "compliance", "risk"],
            },
            "competitive_moat": {
                "expected_source_types": ["official_site", "review", "news"],
                "minimum_coverage": ["Multiple source types preferred because moat claims are interpretive."],
                "risk_level": "high",
                "expected_claim_types": ["moat", "switching_cost", "differentiation", "substitution_risk"],
            },
        }
        return policies.get(
            dimension_id,
            {
                "expected_source_types": ["official_site", "news", "other"],
                "minimum_coverage": ["At least two source-backed public evidence items."],
                "risk_level": "medium",
                "expected_claim_types": ["evidence_backed_signal"],
            },
        )

    def _dimension_confirmation_report(
        self,
        dimensions: list[AnalysisDimension],
    ) -> str:
        lines = [
            "═══════════════════════════════════════════════",
            "  维度确认 — 请审阅以下分析维度",
            "═══════════════════════════════════════════════",
            "",
        ]
        for index, dimension in enumerate(dimensions, start=1):
            lines.append(f"3.{index} {dimension.get('name', '')}")
            for question in dimension.get("guiding_questions", []):
                lines.append(f"  ✅ [{dimension.get('priority', 'P1')}] {question}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _normalize_competitors(self, competitors: list[Any]) -> list[Competitor]:
        normalized: list[Competitor] = []
        for competitor in competitors:
            if isinstance(competitor, str):
                normalized.append({"name": competitor})
            else:
                normalized.append(
                    {
                        "name": competitor.get("name", ""),
                        "product": competitor.get("product", ""),
                        "website": competitor.get("website", ""),
                        "category": competitor.get("category", ""),
                        "notes": competitor.get("notes", ""),
                    }
                )
        return normalized

    def _select_active_schema(
        self,
        query: str,
        competitors: list[Competitor],
        file_context: dict[str, Any],
    ) -> ActiveKnowledgeSchema:
        candidate_industries = self.schema_registry.rank_industries(
            query,
            competitors,
        )
        selected_industry = candidate_industries[0]
        industry_extensions = self.schema_registry.get_extensions(
            selected_industry["industry_id"],
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        return {
            "id": f"active_schema_{selected_industry['industry_id']}_{timestamp}",
            "version": "task_schema_v1",
            "core_fields": list(CORE_SCHEMA_FIELDS),
            "selected_industry": selected_industry,
            "candidate_industries": candidate_industries,
            "industry_extensions": industry_extensions,
            "candidate_extensions": self._file_candidate_extensions(file_context),
            "rationale": (
                "Selected from the schema registry during planning using query, competitor, "
                "alias, example-query, known-competitor, and local file-context signals."
            ),
        }

    def _planning_query(self, query: str, file_context: dict[str, Any]) -> str:
        summary = file_context_summary(file_context)
        search_hints = file_context.get("search_hints", [])
        if not summary and not search_hints:
            return query

        return "\n".join(
            [
                query,
                "",
                "User-provided local file context for planning and schema selection:",
                summary,
                "Search/schema hints:",
                "\n".join(f"- {hint}" for hint in search_hints[:10]),
            ]
        )

    def _file_candidate_extensions(
        self,
        file_context: dict[str, Any],
    ) -> list[SchemaExtension]:
        extensions = []
        for index, hint in enumerate(
            file_context.get("search_hints", [])[:6],
            start=1,
        ):
            extensions.append(
                {
                    "id": f"file_signal_{index}",
                    "name": f"File signal {index}",
                    "description": hint[:400],
                    "origin": "user_requested",
                    "evidence_ids": [],
                    "confidence": 0.55,
                    "approved": False,
                }
            )
        return extensions
