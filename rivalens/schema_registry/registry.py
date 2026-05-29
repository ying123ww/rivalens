"""Industry schema registry used to build task-specific active schemas."""

from dataclasses import dataclass, field

from rivalens.industry_templates import INDUSTRY_DIRECTION_TEMPLATES
from rivalens.schema import IndustryCandidate, SchemaExtension


CORE_SCHEMA_FIELDS = [
    "feature_tree",
    "pricing_model",
    "user_personas",
]


@dataclass(frozen=True)
class IndustryDefinition:
    industry_id: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    example_queries: tuple[str, ...] = ()
    known_competitors: tuple[str, ...] = ()
    extensions: tuple[SchemaExtension, ...] = field(default_factory=tuple)


_CORE_INDUSTRY_DEFINITIONS: tuple[IndustryDefinition, ...] = (
    IndustryDefinition(
        industry_id="saas_collaboration",
        name="Productivity SaaS",
        description="Collaboration, workspace, project management, docs, and knowledge-base software.",
        aliases=(
            "saas",
            "productivity",
            "workspace",
            "collaboration",
            "project management",
            "knowledge base",
            "协作",
            "知识库",
            "项目管理",
            "办公软件",
        ),
        example_queries=(
            "Notion and ClickUp enterprise feature comparison",
            "collaboration software pricing and permissions analysis",
        ),
        known_competitors=("notion", "clickup", "coda", "asana", "monday", "airtable"),
        extensions=(
            {
                "id": "security_compliance",
                "name": "Security and compliance",
                "description": "SSO, SCIM, audit logs, data residency, permissions, and compliance signals.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.9,
                "approved": True,
            },
            {
                "id": "integration_ecosystem",
                "name": "Integration ecosystem",
                "description": "Native integrations, API coverage, marketplace, workflow automation, and import/export.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.86,
                "approved": True,
            },
            {
                "id": "admin_governance",
                "name": "Admin governance",
                "description": "Workspace administration, role control, provisioning, and organization-level policy.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.86,
                "approved": True,
            },
        ),
    ),
    IndustryDefinition(
        industry_id="consumer_food",
        name="Consumer Goods",
        description="Physical consumer products, retail channels, brand positioning, SKUs, and purchase behavior.",
        aliases=("consumer", "retail", "fmcg", "sku", "brand", "渠道", "消费品", "零售"),
        example_queries=(
            "compare two consumer brands by SKU and channel strategy",
            "retail pricing and positioning competitor analysis",
        ),
        known_competitors=("nike", "lululemon", "dyson", "anker"),
        extensions=(
            {
                "id": "channel_strategy",
                "name": "Channel strategy",
                "description": "Direct-to-consumer, marketplaces, offline retail, distribution, and regional coverage.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.88,
                "approved": True,
            },
            {
                "id": "sku_portfolio",
                "name": "SKU portfolio",
                "description": "Product lines, variants, bundles, price ladders, and launch cadence.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.86,
                "approved": True,
            },
        ),
    ),
    IndustryDefinition(
        industry_id="financial_services",
        name="Fintech",
        description="Payments, lending, banking infrastructure, wealth, risk, compliance, and financial operations.",
        aliases=("fintech", "payment", "banking", "risk", "compliance", "金融", "支付", "风控"),
        example_queries=(
            "compare payment platforms compliance and pricing",
            "fintech competitor risk controls and onboarding analysis",
        ),
        known_competitors=("stripe", "paypal", "adyen", "square", "wise"),
        extensions=(
            {
                "id": "regulatory_compliance",
                "name": "Regulatory compliance",
                "description": "Licensing, KYC, AML, PCI, regional compliance, and risk controls.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.9,
                "approved": True,
            },
            {
                "id": "transaction_economics",
                "name": "Transaction economics",
                "description": "Transaction fees, take rate, settlement timing, chargeback cost, and monetization model.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.87,
                "approved": True,
            },
        ),
    ),
    IndustryDefinition(
        industry_id="healthcare",
        name="Healthcare",
        description="Healthcare software, devices, providers, patient workflows, clinical evidence, and compliance.",
        aliases=("healthcare", "medical", "patient", "clinical", "hipaa", "医疗", "健康", "临床"),
        example_queries=(
            "healthcare software competitor compliance and patient workflow analysis",
            "medical product evidence and regulatory comparison",
        ),
        known_competitors=("epic", "cerner", "teladoc", "zocdoc"),
        extensions=(
            {
                "id": "clinical_workflow",
                "name": "Clinical workflow",
                "description": "Provider workflow fit, patient journey, care coordination, and operational integration.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.88,
                "approved": True,
            },
            {
                "id": "clinical_and_privacy_compliance",
                "name": "Clinical and privacy compliance",
                "description": "HIPAA, clinical validation, safety claims, privacy controls, and regulatory signals.",
                "origin": "schema_registry",
                "evidence_ids": [],
                "confidence": 0.9,
                "approved": True,
            },
        ),
    ),
)


def _merge_direction_template_definitions(
    core_definitions: tuple[IndustryDefinition, ...],
) -> tuple[IndustryDefinition, ...]:
    definitions = list(core_definitions)
    defined_ids = {definition.industry_id for definition in definitions}

    for template in INDUSTRY_DIRECTION_TEMPLATES:
        industry_id = template["industry_id"]
        if industry_id in defined_ids:
            continue

        definitions.append(
            IndustryDefinition(
                industry_id=industry_id,
                name=template["name"],
                description=(
                    "Industry direction template used for Rivalens "
                    f"{template['name']} competitor analysis."
                ),
                aliases=tuple(template.get("aliases", [])),
                known_competitors=tuple(template.get("known_competitors", [])),
            )
        )
        defined_ids.add(industry_id)

    return tuple(definitions)


INDUSTRY_REGISTRY: tuple[IndustryDefinition, ...] = (
    _merge_direction_template_definitions(_CORE_INDUSTRY_DEFINITIONS)
)


class SchemaRegistry:
    """Select industry schema extensions using deterministic registry signals."""

    def __init__(self, industries: tuple[IndustryDefinition, ...] = INDUSTRY_REGISTRY):
        self.industries = industries

    def rank_industries(self, query: str, competitors: list[dict]) -> list[IndustryCandidate]:
        haystack = " ".join(
            [
                query,
                " ".join(str(competitor.get("name", "")) for competitor in competitors),
                " ".join(str(competitor.get("category", "")) for competitor in competitors),
                " ".join(str(competitor.get("notes", "")) for competitor in competitors),
            ]
        ).lower()
        candidates = []
        for definition in self.industries:
            signals = [
                signal
                for signal in (
                    list(definition.aliases)
                    + list(definition.known_competitors)
                    + list(definition.example_queries)
                )
                if signal.lower() in haystack
            ]
            score = min(0.35 + 0.11 * len(signals), 0.95) if signals else 0.2
            candidates.append(
                {
                    "industry_id": definition.industry_id,
                    "name": definition.name,
                    "confidence": round(score, 2),
                    "signals": signals[:8],
                }
            )

        return sorted(candidates, key=lambda candidate: candidate.get("confidence", 0), reverse=True)

    def get_definition(self, industry_id: str) -> IndustryDefinition | None:
        for definition in self.industries:
            if definition.industry_id == industry_id:
                return definition
        return None

    def get_extensions(self, industry_id: str) -> list[SchemaExtension]:
        definition = self.get_definition(industry_id)
        if definition is None:
            return []
        return [dict(extension) for extension in definition.extensions]
