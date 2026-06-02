"""LLM fallback for low-confidence industry planning."""

from __future__ import annotations

import os
from typing import Any

import json_repair
from pydantic import BaseModel, Field

from rivalens.research.utils.llm import create_chat_completion
from rivalens.schema.competitive import EvidenceType


DEFAULT_XIAOMI_ANTHROPIC_MODEL = "mimo-v2.5-pro"
DEFAULT_FALLBACK_SOURCE_HINTS = ["official_site", "news", "review"]


class IndustryFallbackDirection(BaseModel):
    direction_id: str = ""
    name: str
    reason: str = ""
    search_focus: str = ""
    source_hints: list[str] = Field(default_factory=list)
    required: bool = True


class IndustryFallbackResult(BaseModel):
    industry_id: str
    industry_name: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    suggested_competitors: list[str] = Field(default_factory=list)
    suggested_analysis_directions: list[IndustryFallbackDirection]


class IndustryLLMFallback:
    """Classify ambiguous industry scope with a structured LLM response."""

    max_directions = 8

    def __init__(
        self,
        llm_spec: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ):
        self.llm_spec = llm_spec or self._llm_spec_from_env()
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def provider(self) -> str | None:
        parsed = self._parse_llm_spec(self.llm_spec)
        return parsed[0] if parsed else None

    @property
    def model(self) -> str | None:
        parsed = self._parse_llm_spec(self.llm_spec)
        return parsed[1] if parsed else None

    def is_configured(self) -> bool:
        return bool(self.provider and self.model)

    async def classify(
        self,
        *,
        query: str,
        competitors: list[dict[str, Any]],
        candidate_industries: list[dict[str, Any]],
    ) -> IndustryFallbackResult:
        provider = self.provider
        model = self.model
        if not provider or not model:
            raise ValueError("Industry LLM fallback is not configured.")

        prompt = self._prompt(
            query=query,
            competitors=competitors,
            candidate_industries=candidate_industries,
        )
        response = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        parsed = self._parse_response(response)
        return IndustryFallbackResult(**parsed)

    def _prompt(
        self,
        *,
        query: str,
        competitors: list[dict[str, Any]],
        candidate_industries: list[dict[str, Any]],
    ) -> str:
        competitor_names = [
            str(competitor.get("name", "")).strip()
            for competitor in competitors
            if str(competitor.get("name", "")).strip()
        ]
        candidates = [
            {
                "industry_id": candidate.get("industry_id", ""),
                "name": candidate.get("name", ""),
                "confidence": candidate.get("confidence", 0),
                "signals": candidate.get("signals", []),
            }
            for candidate in candidate_industries[:8]
        ]
        return f"""You classify competitor-analysis requests when deterministic rules are low-confidence.

Return strict JSON only. Do not wrap it in Markdown.

User request:
{query}

Explicit competitors:
{competitor_names}

Low-confidence rule candidates:
{candidates}

Required JSON shape:
{{
  "industry_id": "stable_snake_case_id",
  "industry_name": "human readable industry name",
  "confidence": 0.0,
  "reason": "short reason for the industry selection",
  "suggested_competitors": ["optional public competitors if the user did not name enough"],
  "suggested_analysis_directions": [
    {{
      "direction_id": "stable_snake_case_id",
      "name": "short direction name",
      "reason": "why this direction matters",
      "search_focus": "natural language research focus",
      "source_hints": ["official_site", "news", "review"],
      "required": true
    }}
  ]
}}

Rules:
- Use 4 to {self.max_directions} analysis directions.
- Prefer concrete competitor-analysis directions, not generic report sections.
- source_hints must be chosen from public evidence source types such as official_site, pricing_page, docs, news, review, marketplace, financial_filing, public_registry, analyst_report, social, other.
- If uncertain, choose a broader but honest industry_id and explain the uncertainty in reason."""

    def _parse_response(self, response: str) -> dict[str, Any]:
        parsed = json_repair.loads(response)
        if not isinstance(parsed, dict):
            raise ValueError("Industry fallback response must be a JSON object.")
        return parsed

    def _llm_spec_from_env(self) -> str | None:
        explicit = (
            os.getenv("INDUSTRY_FALLBACK_LLM")
            or os.getenv("RIVALENS_INDUSTRY_FALLBACK_LLM")
        )
        if explicit:
            return explicit

        anthropic_model = os.getenv("ANTHROPIC_MODEL")
        if anthropic_model:
            return f"anthropic:{anthropic_model}"

        if os.getenv("ANTHROPIC_BASE_URL") and os.getenv("ANTHROPIC_AUTH_TOKEN"):
            return f"anthropic:{DEFAULT_XIAOMI_ANTHROPIC_MODEL}"

        return os.getenv("STRATEGIC_LLM")

    def _parse_llm_spec(self, llm_spec: str | None) -> tuple[str, str] | None:
        if not llm_spec or ":" not in llm_spec:
            return None
        provider, model = llm_spec.split(":", 1)
        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            return None
        return provider, model


def normalize_fallback_directions(
    result: IndustryFallbackResult,
) -> list[dict[str, Any]]:
    valid_source_hints = set(EvidenceType.__args__)
    directions = []
    for index, direction in enumerate(
        result.suggested_analysis_directions[: IndustryLLMFallback.max_directions],
        start=1,
    ):
        name = direction.name.strip()
        if not name:
            continue
        direction_id = direction.direction_id or _slug(name) or f"llm_direction_{index}"
        source_hints = [
            source_hint
            for source_hint in direction.source_hints
            if source_hint in valid_source_hints
        ] or list(DEFAULT_FALLBACK_SOURCE_HINTS)
        reason = direction.reason.strip() or result.reason
        search_focus = direction.search_focus.strip() or name
        directions.append(
            {
                "direction_id": _slug(direction_id) or f"llm_direction_{index}",
                "name": name[:80],
                "reason": reason,
                "description": reason,
                "search_focus": search_focus,
                "source_hints": source_hints,
                "required": bool(direction.required),
                "origin": "llm_fallback",
            }
        )
    return directions


def _slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return slug.strip("_")[:80]
