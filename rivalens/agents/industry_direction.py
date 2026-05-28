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
        default_directions = [
            self._template_direction_to_payload(direction, index)
            for index, direction in enumerate(template.default_directions, start=1)
        ]
        selected_default_directions = self._select_default_directions(
            default_directions,
            selected_direction_ids,
        )
        user_added_directions = self._normalize_user_directions(user_directions or [])
        final_directions = self._dedupe_directions(
            selected_default_directions + user_added_directions
        )
        created_at = datetime.now(timezone.utc).isoformat()

        return {
            "id": f"industry_direction_{template.industry}_{created_at}",
            "detected_industry": selected["name"],
            "industry": selected,
            "candidate_industries": candidate_industries,
            "suggested_directions": default_directions,
            "default_directions": default_directions,
            "user_added_directions": user_added_directions,
            "final_directions": final_directions,
            "final_analysis_plan": {
                "detected_industry": selected["name"],
                "industry_id": selected["industry_id"],
                "industry_name": selected["name"],
                "direction_count": len(final_directions),
                "suggested_directions": default_directions,
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

    def _select_default_directions(
        self,
        default_directions: list[AnalysisDirection],
        selected_direction_ids: list[str] | None,
    ) -> list[AnalysisDirection]:
        if selected_direction_ids is None:
            return default_directions

        required_ids = {
            direction.get("direction_id")
            for direction in default_directions
            if direction.get("required", True)
        }
        selected = set(selected_direction_ids) | required_ids
        return [
            direction
            for direction in default_directions
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
