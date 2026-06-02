"""Industry-first planning skill for competitor-analysis search directions."""

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from typing import Any

from rivalens.agents.industry_llm_fallback import (
    IndustryLLMFallback,
    normalize_fallback_directions,
)
from rivalens.industry_templates import INDUSTRY_DIRECTION_TEMPLATES
from rivalens.schema import (
    AnalysisDirection,
    Competitor,
    IndustryCandidate,
    IndustryDirectionPlan,
    IndustryProfileDirection,
)

# ── Query direction-limit validation ──────────────────────────────────────

_CONSTRAINT_TERMS: tuple[str, ...] = (
    "只看",
    "仅看",
    "只需要",
    "只用",
    "只关注",
    "仅关注",
    "只分析",
    "仅分析",
)

_DIRECTION_KEYWORDS: tuple[str, ...] = (
    # Pricing & business model
    "定价", "价格", "套餐", "收费", "费用", "商业模式", "变现",
    "pricing", "price", "plan", "package",
    # Strategic positioning
    "定位", "产品定位", "战略定位", "市场卡位", "差异化", "竞争格局",
    "positioning", "strategy",
    # Product features & UX
    "功能", "产品功能", "核心功能", "特色功能", "产品结构",
    "交互", "交互设计", "界面", "操作体验", "产品流程",
    "feature", "capability", "ux", "ui", "interaction",
    # Users & reputation
    "目标用户", "用户画像", "用户口碑", "使用场景", "用户体验",
    "persona", "segment", "use case", "review",
    # Operations & growth
    "运营", "运营策略", "增长", "留存", "获客",
    "growth", "retention", "operation",
)

# Characters that signal clause boundaries for proximity checking
_CLAUSE_BOUNDARY = re.compile(r"[。，,；;！!\n]")

_PROXIMITY_WINDOW = 25


def validate_query_no_direction_limits(
    query: str,
    competitor_names: list[str] | None = None,
) -> str | None:
    """Return an error message if *query* tries to limit analysis *directions*.

    Constraints on *competitors* (e.g. "只看钉钉和飞书") are allowed.
    Constraints on analysis *directions* (e.g. "只看产品定位和定价") are
    rejected because competitive analysis requires comprehensive coverage.
    """
    lowered = query.lower()
    if not any(term in lowered for term in _CONSTRAINT_TERMS):
        return None

    # Remove competitor names so they don't interfere with direction detection
    text = lowered
    for name in (competitor_names or []):
        text = text.replace(name.lower(), "")

    # Extract the clause containing the constraint term — the object being
    # constrained should be nearby, not in a different sentence.
    for term in _CONSTRAINT_TERMS:
        idx = text.find(term)
        if idx == -1:
            continue
        # Search in a window after the constraint term
        window = text[idx:idx + _PROXIMITY_WINDOW]
        if any(kw in window for kw in _DIRECTION_KEYWORDS):
            return (
                "竞品分析需要完整性和全面性，不支持限定特定分析方向。"
                "请移除'只看/仅看/只关注/只需要'等方向限定词，重新输入一个开放式的分析请求。"
            )

    return None


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
        llm_fallback: IndustryLLMFallback | None = None,
        fallback_threshold: float | None = None,
    ):
        self.templates = templates or _load_templates(INDUSTRY_DIRECTION_TEMPLATES)
        self.llm_fallback = llm_fallback or IndustryLLMFallback()
        self.fallback_threshold = (
            fallback_threshold
            if fallback_threshold is not None
            else _float_env("RIVALENS_INDUSTRY_RULE_CONFIDENCE_THRESHOLD", 0.35)
        )

    def build_plan(
        self,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]] | None = None,
        user_directions: list[str | dict[str, Any]] | None = None,
        selected_direction_ids: list[str] | None = None,
        user_confirmed: bool = False,
    ) -> IndustryDirectionPlan:
        candidate_industries = self.rank_industries(query, competitors or [])
        return self._build_template_plan(
            query=query,
            competitors=competitors or [],
            user_directions=user_directions or [],
            selected_direction_ids=selected_direction_ids,
            user_confirmed=user_confirmed,
            candidate_industries=candidate_industries,
            selection_method="rule_template",
        )

    async def build_plan_with_fallback(
        self,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]] | None = None,
        user_directions: list[str | dict[str, Any]] | None = None,
        selected_direction_ids: list[str] | None = None,
        user_confirmed: bool = False,
    ) -> IndustryDirectionPlan:
        candidate_industries = self.rank_industries(query, competitors or [])
        top_confidence = (
            candidate_industries[0].get("confidence", 0)
            if candidate_industries
            else 0
        )
        if top_confidence >= self.fallback_threshold:
            return self._build_template_plan(
                query=query,
                competitors=competitors or [],
                user_directions=user_directions or [],
                selected_direction_ids=selected_direction_ids,
                user_confirmed=user_confirmed,
                candidate_industries=candidate_industries,
                selection_method="rule_template",
            )

        if self.llm_fallback and self.llm_fallback.is_configured():
            try:
                fallback_result = await self.llm_fallback.classify(
                    query=query,
                    competitors=list(competitors or []),
                    candidate_industries=candidate_industries,
                )
                fallback_directions = normalize_fallback_directions(fallback_result)
                if fallback_directions:
                    return self._build_llm_fallback_plan(
                        query=query,
                        competitors=competitors or [],
                        user_directions=user_directions or [],
                        selected_direction_ids=selected_direction_ids,
                        user_confirmed=user_confirmed,
                        candidate_industries=candidate_industries,
                        fallback_result=fallback_result,
                        fallback_directions=fallback_directions,
                    )
            except Exception as exc:
                return self._build_template_plan(
                    query=query,
                    competitors=competitors or [],
                    user_directions=user_directions or [],
                    selected_direction_ids=selected_direction_ids,
                    user_confirmed=user_confirmed,
                    candidate_industries=candidate_industries,
                    selection_method="rule_template_after_llm_fallback_error",
                    fallback_reason=f"LLM fallback failed: {exc}",
                    fallback_model=self.llm_fallback.llm_spec,
                )

        return self._build_template_plan(
            query=query,
            competitors=competitors or [],
            user_directions=user_directions or [],
            selected_direction_ids=selected_direction_ids,
            user_confirmed=user_confirmed,
            candidate_industries=candidate_industries,
            selection_method="rule_template_fallback_unavailable",
            fallback_reason=(
                "Rule confidence was below threshold, but no industry LLM fallback "
                "model was configured."
            ),
            fallback_model=getattr(self.llm_fallback, "llm_spec", "") or "",
        )

    def _build_template_plan(
        self,
        *,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]],
        user_directions: list[str | dict[str, Any]],
        selected_direction_ids: list[str] | None,
        user_confirmed: bool,
        candidate_industries: list[IndustryCandidate],
        selection_method: str,
        fallback_reason: str = "",
        fallback_model: str = "",
    ) -> IndustryDirectionPlan:
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
        planner_added_directions = planner_candidate_directions
        selected_default_directions = self._select_default_directions(
            default_directions,
            selected_direction_ids,
            include_required=True,
        )
        selected_planner_directions = self._select_planner_directions(
            planner_added_directions,
            selected_direction_ids,
        )
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
                ],
                "scope_limited_by_query": False,
                "auto_selected_directions": [],
                "planner_supplement_skipped": False,
                "planner_supplement_skip_reason": "",
                "selection_method": selection_method,
                "fallback_reason": fallback_reason,
                "fallback_model": fallback_model,
                "rule_confidence_threshold": self.fallback_threshold,
                "directions": final_directions,
                "final_directions": [
                    direction.get("direction_id", "")
                    for direction in final_directions
                ],
            },
            "selection_method": selection_method,
            "fallback_reason": fallback_reason,
            "fallback_model": fallback_model,
            "user_confirmed": user_confirmed,
            "created_at": created_at,
        }

    def _build_llm_fallback_plan(
        self,
        *,
        query: str,
        competitors: list[Competitor] | list[dict[str, Any]],
        user_directions: list[str | dict[str, Any]],
        selected_direction_ids: list[str] | None,
        user_confirmed: bool,
        candidate_industries: list[IndustryCandidate],
        fallback_result: Any,
        fallback_directions: list[AnalysisDirection],
    ) -> IndustryDirectionPlan:
        selected = {
            "industry_id": self._slug(fallback_result.industry_id)
            or "llm_inferred_industry",
            "name": fallback_result.industry_name,
            "confidence": round(float(fallback_result.confidence), 2),
            "signals": ["llm_fallback", fallback_result.reason],
        }
        detected_competitors = self._explicit_competitor_names(competitors)
        suggested_competitors = [
            competitor
            for competitor in self._dedupe_text(fallback_result.suggested_competitors)
            if competitor.lower() not in {item.lower() for item in detected_competitors}
        ][:8]
        planner_candidate_directions = self._planner_added_directions(
            fallback_directions,
        )
        planner_added_directions = planner_candidate_directions
        selected_default_directions = self._select_default_directions(
            fallback_directions,
            selected_direction_ids,
            include_required=True,
        )
        selected_planner_directions = self._select_planner_directions(
            planner_added_directions,
            selected_direction_ids,
        )
        user_added_directions = self._normalize_user_directions(user_directions or [])
        final_directions = self._dedupe_directions(
            selected_default_directions
            + selected_planner_directions
            + user_added_directions
        )
        created_at = datetime.now(timezone.utc).isoformat()
        fallback_model = getattr(self.llm_fallback, "llm_spec", "") or ""
        return {
            "id": f"industry_direction_{selected['industry_id']}_{created_at}",
            "detected_industry": selected["name"],
            "industry": selected,
            "candidate_industries": self._merge_candidate_industries(
                selected,
                candidate_industries,
            ),
            "detected_competitors": detected_competitors,
            "suggested_competitors": suggested_competitors,
            "suggested_directions": fallback_directions,
            "default_directions": fallback_directions,
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
                "suggested_directions": fallback_directions,
                "planner_added_directions": planner_added_directions,
                "planner_coverage_basis": [
                    direction["name"] for direction in PLANNER_COVERAGE_DIRECTIONS
                ],
                "scope_limited_by_query": False,
                "auto_selected_directions": [],
                "planner_supplement_skipped": False,
                "planner_supplement_skip_reason": "",
                "selection_method": "llm_fallback",
                "fallback_reason": fallback_result.reason,
                "fallback_model": fallback_model,
                "rule_confidence_threshold": self.fallback_threshold,
                "directions": final_directions,
                "final_directions": [
                    direction.get("direction_id", "")
                    for direction in final_directions
                ],
            },
            "selection_method": "llm_fallback",
            "fallback_reason": fallback_result.reason,
            "fallback_model": fallback_model,
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

    def _explicit_competitor_names(
        self,
        competitors: list[Competitor] | list[dict[str, Any]],
    ) -> list[str]:
        detected = []
        for competitor in competitors:
            if isinstance(competitor, str):
                name = competitor.strip()
            else:
                name = str(competitor.get("name", "")).strip()
            if name:
                detected.append(name)
        return self._dedupe_text(detected)

    def _merge_candidate_industries(
        self,
        selected_industry: IndustryCandidate,
        candidates: list[IndustryCandidate],
    ) -> list[IndustryCandidate]:
        merged = [selected_industry]
        selected_id = selected_industry.get("industry_id")
        merged.extend(
            candidate
            for candidate in candidates
            if candidate.get("industry_id") != selected_id
        )
        return merged

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


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
