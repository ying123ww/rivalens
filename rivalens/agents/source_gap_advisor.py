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
        source_metrics: dict[str, Any] | None = None,
    ) -> SourceGapDecision | dict[str, Any]:
        """Return a structured source coverage decision."""


class LLMSourceGapAdvisor:
    """Decide source coverage gaps with an LLM and no rule fallback."""

    def __init__(
        self,
        llm_spec: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        max_evidence_items: int | None = None,
        max_excerpt_chars: int | None = None,
    ) -> None:
        self.llm_spec = llm_spec or self._llm_spec_from_env()
        self.temperature = temperature
        self.max_tokens = max_tokens or self._env_int(
            "RIVALENS_SOURCE_GAP_LLM_MAX_TOKENS",
            8192,
            minimum=900,
        )
        self.max_evidence_items = max_evidence_items or self._env_int(
            "RIVALENS_SOURCE_GAP_LLM_MAX_EVIDENCE",
            12,
            minimum=1,
        )
        self.max_excerpt_chars = max_excerpt_chars or self._env_int(
            "RIVALENS_SOURCE_GAP_LLM_EXCERPT_CHARS",
            800,
            minimum=120,
        )

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
        source_metrics: dict[str, Any] | None = None,
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
            source_metrics=source_metrics or {},
        )
        response = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            cost_callback=add_cost,
            rivalens_operation="source_gap_advisor",
            rivalens_trace_context={
                "id": branch.get("id", ""),
                "branch_id": branch.get("id", ""),
                "parent_branch_id": branch.get("parent_branch_id"),
                "depth": branch.get("depth", 0),
                "competitor": branch.get("competitor", ""),
                "dimension_id": branch.get("dimension_id", ""),
                "dimension_name": branch.get("dimension_name", ""),
                "search_stage": branch.get("search_stage", ""),
            },
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
                "source_metrics": self._source_metrics_summary(source_metrics or {}),
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
                    "source_domain": evidence.get("source_domain", ""),
                    "source_type": evidence.get("source_type", ""),
                    "excerpt": excerpt[: self.max_excerpt_chars],
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
        source_metrics: dict[str, Any],
    ) -> str:
        allowed_source_types = ", ".join(EvidenceType.__args__)
        branch_context = {
            "competitor": branch.get("competitor", ""),
            "dimension_id": branch.get("dimension_id", ""),
            "dimension_name": branch.get("dimension_name", ""),
            "research_goal": branch.get("research_goal", ""),
            "source_preferences": source_preferences,
            "found_source_types": found_source_types,
            "accepted_count": source_metrics.get(
                "accepted_evidence_count",
                len(accepted_evidence),
            ),
            "minimum_count": minimum_count,
        }
        compact_source_metrics = self._compact_source_metrics(source_metrics)
        branch_json = json.dumps(branch_context, ensure_ascii=False, indent=2)
        source_metrics_json = json.dumps(
            compact_source_metrics,
            ensure_ascii=False,
            indent=2,
        )
        evidence_json = json.dumps(
            self._compact_evidence(accepted_evidence),
            ensure_ascii=False,
            indent=2,
        )
        return f"""Return strict JSON only. Decide if this branch needs source-coverage follow-up.

JSON shape:
{{"open_gap": false, "gap_code": "", "query_focus": "", "target_source_types": [], "blocking": false, "reason": "", "expected_improvement": "", "confidence": 0.0}}

Rules:
- Judge source mix only, not content coverage.
- source_preferences are hints, not hard requirements.
- Open a gap only if accepted sources are materially weak for traceability, authority, independence, or reliability.
- Use blocking=true only when current sources are too weak for downstream analysis.
- target_source_types must be from: {allowed_source_types}
- Keep reason and expected_improvement under 160 chars each.

Branch:
{branch_json}

Metrics:
{source_metrics_json}

Evidence:
{evidence_json}
"""

    def _compact_source_metrics(self, source_metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "accepted_evidence_count": source_metrics.get("accepted_evidence_count", 0),
            "unique_canonical_url_count": source_metrics.get(
                "unique_canonical_url_count",
                0,
            ),
            "unique_domain_count": source_metrics.get("unique_domain_count", 0),
            "independent_source_count": source_metrics.get(
                "independent_source_count",
                0,
            ),
            "primary_source_count": source_metrics.get("primary_source_count", 0),
            "source_type_counts": dict(source_metrics.get("source_type_counts", {})),
            "domain_counts": dict(source_metrics.get("domain_counts", {})),
            "duplicate_source_groups": list(
                source_metrics.get("duplicate_source_groups", []),
            )[:6],
            "canonical_sources": list(source_metrics.get("canonical_sources", []))[:8],
        }

    def _source_metrics_summary(self, source_metrics: dict[str, Any]) -> dict[str, Any]:
        compact = self._compact_source_metrics(source_metrics)
        compact.pop("duplicate_source_groups", None)
        compact.pop("canonical_sources", None)
        return compact

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

    def _env_int(self, env_name: str, default: int, minimum: int = 0) -> int:
        raw_value = os.getenv(env_name)
        if raw_value in (None, ""):
            return default
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed)

    def _slug(self, value: str) -> str:
        slug = "".join(
            character.lower() if character.isalnum() else "_"
            for character in value
        )
        return slug.strip("_")
