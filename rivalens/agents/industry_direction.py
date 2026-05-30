"""Industry-first planning skill for competitor-analysis search directions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from rivalens.industry_templates import INDUSTRY_DIRECTION_TEMPLATES
from rivalens.schema import (
    AnalysisDirection,
    Competitor,
    IndustryCandidate,
    IndustryDirectionPlan,
    IndustryProfileDirection,
)


DEFAULT_SOURCE_HINTS = ["official_site", "pricing_page", "docs", "news", "review"]
USER_DIRECTION_SOURCE_HINTS = ["official_site", "news", "review"]

PLANNER_COVERAGE_DIRECTIONS: tuple[dict[str, Any], ...] = (
    {
        "direction_id": "strategic_positioning",
        "name": "战略定位",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖战略定位、市场卡位和差异化叙事。",
        "source_hints": ["official_site", "news", "analyst_report", "social"],
        "coverage_terms": ["战略", "定位", "卡位", "竞争格局", "品牌", "positioning", "strategy"],
    },
    {
        "direction_id": "target_users",
        "name": "目标用户",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖目标用户、用户画像和核心使用场景。",
        "source_hints": ["official_site", "review", "social", "news"],
        "coverage_terms": ["目标用户", "用户画像", "使用场景", "persona", "segment", "use case"],
    },
    {
        "direction_id": "business_model",
        "name": "商业模式",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖商业模式、变现路径和收费结构。",
        "source_hints": ["pricing_page", "official_site", "financial_filing", "news"],
        "coverage_terms": ["商业模式", "定价", "套餐", "收费", "费用", "pricing", "fee", "monetization"],
    },
    {
        "direction_id": "operations_strategy",
        "name": "运营策略",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖获客、增长、留存和运营打法。",
        "source_hints": ["official_site", "news", "social", "review"],
        "coverage_terms": ["运营", "增长", "留存", "获客", "复购", "growth", "retention", "loyalty"],
    },
    {
        "direction_id": "product_features",
        "name": "产品功能",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖核心功能矩阵和功能深度对比。",
        "source_hints": ["official_site", "docs", "marketplace", "review"],
        "coverage_terms": ["功能", "能力", "feature", "capability", "matrix"],
    },
    {
        "direction_id": "product_flow",
        "name": "产品流程",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖核心任务流程、转化路径和使用链路。",
        "source_hints": ["official_site", "docs", "review", "social"],
        "coverage_terms": ["流程", "工作流", "链路", "workflow", "journey", "process"],
    },
    {
        "direction_id": "product_structure",
        "name": "产品结构",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖产品模块、信息架构和功能层级。",
        "source_hints": ["official_site", "docs", "review"],
        "coverage_terms": ["产品结构", "信息架构", "模块", "层级", "architecture", "structure", "module"],
    },
    {
        "direction_id": "interaction_design",
        "name": "交互设计",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖界面交互、操作体验和多端体验细节。",
        "source_hints": ["official_site", "review", "marketplace", "social"],
        "coverage_terms": ["交互", "界面", "操作体验", "移动端", "ux", "ui", "interaction", "mobile"],
    },
    {
        "direction_id": "signature_features",
        "name": "特色功能",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖独有功能、差异化能力和竞争亮点。",
        "source_hints": ["official_site", "docs", "news", "review"],
        "coverage_terms": ["特色", "差异", "独有", "亮点", "signature", "differentiation", "unique"],
    },
    {
        "direction_id": "user_reputation",
        "name": "用户口碑",
        "reason": "PlanningAgent 根据通用竞品分析框架补充：现有行业方向未充分覆盖用户评价、口碑、痛点和公开反馈。",
        "source_hints": ["review", "social", "marketplace", "complaint_database"],
        "coverage_terms": ["口碑", "评价", "痛点", "投诉", "review", "sentiment", "complaint"],
    },
)


@dataclass(frozen=True)
class IndustryDirectionTemplate:
    industry: str
    display_name: str
    aliases: tuple[str, ...]
    known_competitors: tuple[str, ...]
    default_directions: tuple[IndustryProfileDirection, ...]


def _load_templates(
    raw_templates: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[IndustryDirectionTemplate, ...]:
    templates = []
    for raw in raw_templates:
        templates.append(
            IndustryDirectionTemplate(
                industry=str(raw.get("industry") or raw["industry_id"]),
                display_name=str(raw.get("display_name") or raw["name"]),
                aliases=tuple(str(item) for item in raw.get("aliases", [])),
                known_competitors=tuple(
                    str(item) for item in raw.get("known_competitors", [])
                ),
                default_directions=tuple(
                    {
                        "direction_id": str(item["direction_id"]),
                        "name": str(item["name"]),
                        "reason": str(item.get("reason", "")),
                        "source_hints": [
                            str(source_hint)
                            for source_hint in item.get("source_hints", [])
                        ],
                        "required": bool(item.get("required", True)),
                    }
                    for item in raw.get("default_directions")
                    or raw.get("directions", [])
                ),
            )
        )
    return tuple(templates)


class IndustryDirectionSkill:
    """Match an industry and return user-maintained default directions.

    Industry-specific directions are deterministic template data from
    rivalens.industry_templates.directions. The skill does not invent them.
    """

    def __init__(
        self,
        templates: tuple[IndustryDirectionTemplate, ...] | None = None,
    ):
        self.templates = templates or _load_templates(INDUSTRY_DIRECTION_TEMPLATES)

    def build_plan(
        self,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]] | None = None,
        user_directions: list[str | dict[str, Any]] | None = None,
        selected_direction_ids: list[str] | None = None,
        user_confirmed: bool = False,
    ) -> IndustryDirectionPlan:
        candidate_industries = self.rank_industries(query, competitors or [])
        selected = candidate_industries[0]
        template = self._template_for(selected["industry_id"]) or self.templates[0]
        detected_competitors = self._detected_competitors(
            query,
            competitors or [],
            template,
        )
        suggested_competitors = self._suggested_competitors(
            template,
            detected_competitors,
        )
        default_directions = [
            self._template_direction_to_payload(direction, index)
            for index, direction in enumerate(template.default_directions, start=1)
        ]
        planner_candidate_directions = self._planner_added_directions(default_directions)
        query_limited_direction_ids = self._query_limited_direction_ids(
            query,
            default_directions + planner_candidate_directions,
        )
        planner_added_directions = (
            []
            if query_limited_direction_ids is not None
            else planner_candidate_directions
        )
        effective_selected_direction_ids = (
            query_limited_direction_ids
            if query_limited_direction_ids is not None
            else selected_direction_ids
        )
        selected_default_directions = self._select_default_directions(
            default_directions,
            effective_selected_direction_ids,
            include_required=query_limited_direction_ids is None,
        )
        selected_planner_directions = self._select_planner_directions(
            planner_candidate_directions
            if query_limited_direction_ids is not None
            else planner_added_directions,
            effective_selected_direction_ids,
        )
        if query_limited_direction_ids is not None:
            selected_planner_directions = [
                self._query_limited_direction(direction)
                for direction in selected_planner_directions
            ]
        user_added_directions = self._normalize_user_directions(user_directions or [])
        final_directions = self._dedupe_directions(
            selected_default_directions
            + selected_planner_directions
            + user_added_directions
        )
        created_at = datetime.now(timezone.utc).isoformat()

        return {
            "id": f"industry_direction_{template.industry}_{created_at}",
            "detected_industry": selected["name"],
            "industry": selected,
            "candidate_industries": candidate_industries,
            "detected_competitors": detected_competitors,
            "suggested_competitors": suggested_competitors,
            "suggested_directions": default_directions,
            "default_directions": default_directions,
            "planner_added_directions": planner_added_directions,
            "user_added_directions": user_added_directions,
            "final_directions": final_directions,
            "final_analysis_plan": {
                "detected_industry": selected["name"],
                "industry_id": selected["industry_id"],
                "industry_name": selected["name"],
                "detected_competitors": detected_competitors,
                "suggested_competitors": suggested_competitors,
                "direction_count": len(final_directions),
                "suggested_directions": default_directions,
                "planner_added_directions": planner_added_directions,
                "planner_coverage_basis": [
                    direction["name"] for direction in PLANNER_COVERAGE_DIRECTIONS
                ]
                if query_limited_direction_ids is None
                else [],
                "scope_limited_by_query": query_limited_direction_ids is not None,
                "auto_selected_directions": query_limited_direction_ids or [],
                "planner_supplement_skipped": query_limited_direction_ids is not None,
                "planner_supplement_skip_reason": (
                    "用户查询包含只看/仅看/只关注等限定词，跳过自动补充方向。"
                    if query_limited_direction_ids is not None
                    else ""
                ),
                "directions": final_directions,
                "final_directions": [
                    direction.get("direction_id", "")
                    for direction in final_directions
                ],
            },
            "user_confirmed": user_confirmed,
            "created_at": created_at,
        }

    def rank_industries(
        self,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]],
    ) -> list[IndustryCandidate]:
        haystack = self._haystack(query, competitors)
        candidates: list[IndustryCandidate] = []
        for template in self.templates:
            signals = [
                signal
                for signal in (*template.aliases, *template.known_competitors)
                if signal.lower() in haystack
            ]
            confidence = min(0.35 + 0.1 * len(signals), 0.95) if signals else 0.2
            candidates.append(
                {
                    "industry_id": template.industry,
                    "name": template.display_name,
                    "confidence": round(confidence, 2),
                    "signals": signals[:8],
                }
            )

        return sorted(
            candidates,
            key=lambda candidate: candidate.get("confidence", 0),
            reverse=True,
        )

    def _template_for(self, industry_id: str) -> IndustryDirectionTemplate | None:
        for template in self.templates:
            if template.industry == industry_id:
                return template
        return None

    def _detected_competitors(
        self,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]],
        template: IndustryDirectionTemplate,
    ) -> list[str]:
        detected = []
        for competitor in competitors:
            if isinstance(competitor, str):
                name = competitor.strip()
            else:
                name = str(competitor.get("name", "")).strip()
            if name:
                detected.append(name)

        haystack = query.lower()
        for competitor in template.known_competitors:
            if competitor.lower() in haystack:
                detected.append(competitor)
        return self._dedupe_text(detected)

    def _suggested_competitors(
        self,
        template: IndustryDirectionTemplate,
        detected_competitors: list[str],
    ) -> list[str]:
        detected = {competitor.lower() for competitor in detected_competitors}
        return [
            competitor
            for competitor in template.known_competitors
            if competitor.lower() not in detected
        ][:8]

    def _haystack(
        self,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]],
    ) -> str:
        parts = [query]
        for competitor in competitors:
            parts.extend(
                str(competitor.get(field, ""))
                for field in ("name", "product", "website", "category", "notes")
            )
        return " ".join(parts).lower()

    def _template_direction_to_payload(
        self,
        direction: IndustryProfileDirection,
        index: int,
    ) -> AnalysisDirection:
        direction_id = direction.get("direction_id") or f"template_direction_{index}"
        name = direction.get("name") or direction_id
        reason = direction.get("reason", "")
        source_hints = direction.get("source_hints") or DEFAULT_SOURCE_HINTS
        return {
            "direction_id": direction_id,
            "name": name,
            "reason": reason,
            "description": reason,
            "search_focus": name,
            "source_hints": list(source_hints),
            "required": bool(direction.get("required", True)),
            "origin": "industry_template",
        }

    def _normalize_user_directions(
        self,
        user_directions: list[str | dict[str, Any]],
    ) -> list[AnalysisDirection]:
        normalized = []
        for index, direction in enumerate(user_directions, start=1):
            if isinstance(direction, str):
                for text in self._split_user_direction_text(direction):
                    direction_id = self._custom_direction_id(text, index)
                    normalized.append(
                        {
                            "direction_id": direction_id,
                            "name": text[:80],
                            "reason": "用户补充的重点分析方向",
                            "description": "用户补充的重点分析方向",
                            "search_focus": text,
                            "source_hints": list(USER_DIRECTION_SOURCE_HINTS),
                            "required": True,
                            "origin": "user_requested",
                        }
                    )
                continue

            name = str(direction.get("name") or direction.get("title") or "").strip()
            description = str(direction.get("description") or name).strip()
            if not name and not description:
                continue
            direction_id = str(
                direction.get("direction_id")
                or f"user_direction_{index}"
            )
            normalized.append(
                {
                    "direction_id": direction_id,
                    "name": name or description[:80],
                    "reason": str(direction.get("reason") or "用户补充的重点分析方向"),
                    "description": description,
                    "search_focus": str(direction.get("search_focus") or description),
                    "source_hints": list(
                        direction.get(
                            "source_hints",
                            USER_DIRECTION_SOURCE_HINTS,
                        )
                    ),
                    "required": bool(direction.get("required", True)),
                    "origin": "user_requested",
                }
            )
        return normalized

    def _dedupe_directions(
        self,
        directions: list[AnalysisDirection],
    ) -> list[AnalysisDirection]:
        deduped: dict[str, AnalysisDirection] = {}
        for direction in directions:
            key = self._slug(
                direction.get("direction_id") or direction.get("name", "")
            )
            if not key:
                continue
            deduped[key] = direction
        return list(deduped.values())

    def _slug(self, value: str) -> str:
        return (
            "".join(
                character.lower() if character.isalnum() else "_"
                for character in value
            ).strip("_")
            or "direction"
        )

    def _dedupe_text(self, values: list[str]) -> list[str]:
        deduped: dict[str, str] = {}
        for value in values:
            cleaned = value.strip()
            if cleaned:
                deduped[cleaned.lower()] = cleaned
        return list(deduped.values())

    def _select_default_directions(
        self,
        default_directions: list[AnalysisDirection],
        selected_direction_ids: list[str] | None,
        include_required: bool = True,
    ) -> list[AnalysisDirection]:
        if selected_direction_ids is None:
            return default_directions

        required_ids = {
            direction.get("direction_id")
            for direction in default_directions
            if include_required and direction.get("required", True)
        }
        selected = set(selected_direction_ids) | required_ids
        return [
            direction
            for direction in default_directions
            if direction.get("direction_id") in selected
        ]

    def _planner_added_directions(
        self,
        default_directions: list[AnalysisDirection],
    ) -> list[AnalysisDirection]:
        existing_direction_ids = {
            direction.get("direction_id", "") for direction in default_directions
        }
        existing_text = "\n".join(
            " ".join(
                str(direction.get(field, ""))
                for field in ("direction_id", "name", "reason", "description")
            )
            for direction in default_directions
        ).lower()

        additions: list[AnalysisDirection] = []
        for coverage_direction in PLANNER_COVERAGE_DIRECTIONS:
            direction_id = str(coverage_direction["direction_id"])
            if direction_id in existing_direction_ids:
                continue
            terms = [
                str(term).lower()
                for term in coverage_direction.get("coverage_terms", [])
            ]
            if any(term and term in existing_text for term in terms):
                continue
            additions.append(
                {
                    "direction_id": direction_id,
                    "name": str(coverage_direction["name"]),
                    "reason": str(coverage_direction["reason"]),
                    "description": str(coverage_direction["reason"]),
                    "search_focus": str(coverage_direction["name"]),
                    "source_hints": list(coverage_direction["source_hints"]),
                    "required": False,
                    "origin": "planner_suggested",
                }
            )
        return additions

    def _select_planner_directions(
        self,
        planner_added_directions: list[AnalysisDirection],
        selected_direction_ids: list[str] | None,
    ) -> list[AnalysisDirection]:
        if selected_direction_ids is None:
            return planner_added_directions

        selected = set(selected_direction_ids)
        return [
            direction
            for direction in planner_added_directions
            if direction.get("direction_id") in selected
        ]

    def _query_has_limited_scope(self, query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in self._limit_terms())

    def _limit_terms(self) -> tuple[str, ...]:
        return (
            "只看",
            "仅看",
            "只关注",
            "仅关注",
            "只分析",
            "仅分析",
            "限定",
            "聚焦",
        )

    def _query_limited_direction(
        self,
        direction: AnalysisDirection,
    ) -> AnalysisDirection:
        limited_direction = dict(direction)
        limited_direction["origin"] = "user_requested"
        limited_direction["required"] = True
        limited_direction["reason"] = (
            "用户限定语义匹配的分析方向，未进行自动 Planner 补充。"
        )
        limited_direction["description"] = (
            limited_direction.get("description")
            or limited_direction.get("reason", "")
        )
        return limited_direction

    def _query_limited_direction_ids(
        self,
        query: str,
        directions: list[AnalysisDirection],
    ) -> list[str] | None:
        lowered = query.lower()
        if not self._query_has_limited_scope(query):
            return None

        direction_aliases = {
            "pricing": (
                "定价",
                "价格",
                "套餐",
                "收费",
                "费用",
                "pricing",
                "price",
                "plan",
                "package",
            ),
            "positioning": (
                "定位",
                "产品定位",
                "战略定位",
                "市场卡位",
                "差异化",
                "positioning",
                "strategy",
            ),
        }
        requested_aliases = {
            group
            for group, aliases in direction_aliases.items()
            if any(alias in lowered for alias in aliases)
        }
        if not requested_aliases:
            return None

        selected_ids = []
        for direction in directions:
            primary_searchable = " ".join(
                str(direction.get(field, ""))
                for field in ("direction_id", "name", "search_focus")
            ).lower()
            searchable = " ".join(
                str(direction.get(field, ""))
                for field in ("direction_id", "name", "reason", "description", "search_focus")
            ).lower()
            if (
                "pricing" in requested_aliases
                and (
                    "pricing" in searchable
                    or "定价" in searchable
                    or "价格" in searchable
                    or "套餐" in searchable
                    or "收费" in searchable
                    or "费用" in searchable
                    or "商业模式" in searchable
                )
            ):
                selected_ids.append(direction["direction_id"])
                continue
            if (
                "positioning" in requested_aliases
                and (
                    "positioning" in primary_searchable
                    or "战略定位" in primary_searchable
                    or "定位" in primary_searchable
                    or "市场卡位" in primary_searchable
                )
            ):
                selected_ids.append(direction["direction_id"])

        return selected_ids or None

    def _custom_direction_id(self, text: str, index: int) -> str:
        lowered = text.lower()
        if "ai" in lowered or "人工智能" in text:
            return "ai_capability"
        if "私有化" in text or "私有部署" in text:
            return "private_deployment"
        slug = self._slug(text)
        if slug and slug != "direction" and slug.isascii():
            return slug[:80]
        return f"user_direction_{index}"

    def _split_user_direction_text(self, text: str) -> list[str]:
        cleaned = text.strip().strip("。.")
        for prefix in (
            "我还想重点看",
            "还想重点看",
            "重点看",
            "补充",
            "我还想看",
        ):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        separators = ["以及", "还有", "和", "与", "、", "，", ",", ";", "；", "\n"]
        parts = [cleaned]
        for separator in separators:
            next_parts = []
            for part in parts:
                next_parts.extend(part.split(separator))
            parts = next_parts
        return [part.strip() for part in parts if part.strip()]
