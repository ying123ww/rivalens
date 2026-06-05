"""LLM advisor for collection-stage source coverage gaps."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import json_repair
from pydantic import BaseModel, Field

from rivalens.research.utils.llm import create_chat_completion
from rivalens.schema.competitive import EvidenceType
from rivalens.text_quality import clean_text


class SourceGapDecision(BaseModel):
    """Structured decision about whether collection needs a source coverage gap."""

    open_gap: bool = False
    gap_code: str = ""
    query_focus: str = ""
    target_source_types: list[str] = Field(default_factory=list)
    blocking: bool = False
    reason: str = ""
    expected_improvement: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceGapAdvisor(Protocol):
    provider: str | None
    model: str | None

    async def decide(
        self,
        *,
        branch: dict[str, Any],
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
        source_preferences: list[str],
        minimum_count: int,
    ) -> SourceGapDecision | dict[str, Any]:
        """Return a structured source coverage decision."""


class LLMSourceGapAdvisor:
    """Decide source coverage gaps with an LLM and no rule fallback."""

    def __init__(
        self,
        llm_spec: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 900,
        max_evidence_items: int = 8,
        max_excerpt_chars: int = 700,
    ) -> None:
        self.llm_spec = llm_spec or self._llm_spec_from_env()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_evidence_items = max_evidence_items
        self.max_excerpt_chars = max_excerpt_chars

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

    async def decide(
        self,
        *,
        branch: dict[str, Any],
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
        source_preferences: list[str],
        minimum_count: int,
    ) -> SourceGapDecision:
        provider = self.provider
        model = self.model
        if not provider or not model:
            raise ValueError("Source gap LLM advisor is not configured.")

        compact_evidence = self._compact_evidence(accepted_evidence)
        llm_cost = 0.0

        def add_cost(cost: float) -> None:
            nonlocal llm_cost
            llm_cost += float(cost)

        prompt = self._prompt(
            branch=branch,
            accepted_evidence=compact_evidence,
            found_source_types=found_source_types,
            source_preferences=source_preferences,
            minimum_count=minimum_count,
        )
        response = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            cost_callback=add_cost,
        )
        parsed = json_repair.loads(response)
        decision = SourceGapDecision.model_validate(parsed)
        decision.target_source_types = self._valid_source_types(decision.target_source_types)
        decision.gap_code = self._slug(decision.gap_code)[:80]
        decision.metadata = {
            "llm_prompt_id": "source_gap_advisor_v1",
            "llm_prompt_chars": len(prompt),
            "llm_provider": provider,
            "llm_model": model,
            "llm_cost": round(llm_cost, 6),
            "llm_max_tokens": self.max_tokens,
            "llm_temperature": self.temperature,
            "llm_raw_response": response[:4000],
            "llm_input": {
                "branch_id": branch.get("id", ""),
                "dimension_id": branch.get("dimension_id", ""),
                "source_preferences": source_preferences,
                "found_source_types": found_source_types,
                "minimum_count": minimum_count,
            },
            "llm_input_evidence_count": len(compact_evidence),
            "llm_input_evidence_ids": [
                evidence.get("id", "")
                for evidence in compact_evidence
                if evidence.get("id")
            ],
        }
        return decision

    def _compact_evidence(
        self,
        accepted_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        compact = []
        for evidence in accepted_evidence[: self.max_evidence_items]:
            evidence_id = evidence.get("id", "")
            if not evidence_id:
                continue
            excerpt = clean_text(evidence.get("excerpt") or evidence.get("title") or "")
            compact.append(
                {
                    "id": evidence_id,
                    "title": evidence.get("title", ""),
                    "url": evidence.get("url", ""),
                    "source_type": evidence.get("source_type", ""),
                    "excerpt": excerpt[: self.max_excerpt_chars],
                    "confidence": evidence.get("confidence", 0.5),
                }
            )
        return compact

    def _prompt(
        self,
        *,
        branch: dict[str, Any],
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
        source_preferences: list[str],
        minimum_count: int,
    ) -> str:
        allowed_source_types = ", ".join(EvidenceType.__args__)
        branch_context = {
            "competitor": branch.get("competitor", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "research_goal": branch.get("research_goal", ""),
            "guiding_questions": list(branch.get("guiding_questions", []))[:6],
            "success_criteria": list(branch.get("success_criteria", []))[:8],
            "source_preferences": source_preferences,
            "found_source_types": found_source_types,
            "accepted_count": len(accepted_evidence),
            "minimum_count": minimum_count,
        }
        branch_json = json.dumps(branch_context, ensure_ascii=False, indent=2)
        evidence_json = json.dumps(accepted_evidence, ensure_ascii=False, indent=2)
        return f"""Decide whether this competitor-analysis branch needs an additional source coverage gap.

Return strict JSON only. Do not wrap it in Markdown.

You are not judging whether content success criteria are satisfied. CoverageReviewer handles content coverage separately.
Your job is only to decide whether the accepted evidence source mix needs a targeted follow-up collection because another public source type would materially improve traceability, authority, or reliability.

Allowed target_source_types:
{allowed_source_types}

Required JSON shape:
{{
  "open_gap": false,
  "gap_code": "stable_snake_case_code_when_open",
  "query_focus": "specific follow-up collection focus when open",
  "target_source_types": ["one_or_more_allowed_source_types_when_open"],
  "blocking": false,
  "reason": "short reason grounded in the accepted evidence and branch context",
  "expected_improvement": "what the follow-up source would improve",
  "confidence": 0.0
}}

Decision rules:
- source_preferences are hints, not requirements. Do not open a gap just because a preferred source type is absent.
- Open a gap only when the current accepted evidence source mix is materially weak for this branch.
- Use blocking=true only when the current source mix is too weak to support downstream analysis without targeted collection.
- If the accepted source mix is good enough, return open_gap=false even if another source type might be nice to have.
- If open_gap=true, choose concise target_source_types from the allowed list and write a query_focus a collector can act on.
- Do not invent evidence. Base the decision only on the branch context and accepted evidence below.

Branch context:
{branch_json}

Accepted evidence:
{evidence_json}
"""

    def _valid_source_types(self, source_types: list[str]) -> list[str]:
        allowed = set(EvidenceType.__args__)
        return list(
            dict.fromkeys(
                source_type
                for source_type in source_types
                if source_type in allowed
            )
        )

    def _llm_spec_from_env(self) -> str | None:
        return (
            os.getenv("RIVALENS_SOURCE_GAP_LLM")
            or os.getenv("SOURCE_GAP_LLM")
            or os.getenv("STRATEGIC_LLM")
            or os.getenv("SMART_LLM")
        )

    def _parse_llm_spec(self, llm_spec: str | None) -> tuple[str, str] | None:
        if not llm_spec or ":" not in llm_spec:
            return None
        provider, model = llm_spec.split(":", 1)
        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            return None
        return provider, model

    def _slug(self, value: str) -> str:
        slug = "".join(
            character.lower() if character.isalnum() else "_"
            for character in value
        )
        return slug.strip("_")
