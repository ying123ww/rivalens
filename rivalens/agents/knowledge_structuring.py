"""Structure collected evidence into the active competitor knowledge schema."""

import asyncio
from collections import defaultdict
import hashlib
import json
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import json_repair

from rivalens.agents.evidence_snippets import EvidenceSnippetBuilder
from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.research.utils.llm import create_chat_completion
from rivalens.schema import (
    CompetitorAnalysisState,
    CompetitorKnowledge,
    KnowledgeFact,
    KnowledgeFactPackage,
)
from rivalens.text_quality import clean_source_text, clean_text, is_low_quality_text


FACT_TYPES = {
    "pricing_signal",
    "feature_presence",
    "target_user_signal",
    "trust_compliance_signal",
    "integration_signal",
    "market_signal",
    "public_evidence_signal",
}


GENERIC_FACT_OBJECT_CHARS = 520


PRICING_ATOM_PREDICATES = {
    "free_tier": "exists",
    "published_plan_price": "publishes_price",
    "quote_only": "requires_quote",
    "usage_based_billing": "uses_billing_model",
    "annual_discount": "offers_discount",
}


class KnowledgeFactLLMExtractor:
    prompt_id = "knowledge_fact_llm_extraction_v1"

    def __init__(
        self,
        llm_spec: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        batch_size: int | None = None,
        max_batches: int | None = None,
        concurrency: int | None = None,
        timeout_seconds: int | None = None,
        max_evidence_chars: int | None = None,
    ) -> None:
        self.llm_spec = llm_spec or self._llm_spec_from_env()
        self.temperature = temperature
        self.max_tokens = max_tokens or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_MAX_TOKENS",
            900,
            minimum=300,
        )
        self.batch_size = batch_size or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_BATCH_SIZE",
            4,
            minimum=1,
        )
        self.max_batches = max_batches or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_MAX_BATCHES",
            12,
            minimum=1,
        )
        self.concurrency = concurrency or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_CONCURRENCY",
            4,
            minimum=1,
        )
        self.timeout_seconds = timeout_seconds or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_TIMEOUT_SECONDS",
            45,
            minimum=5,
        )
        self.max_evidence_chars = max_evidence_chars or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_EVIDENCE_CHARS",
            1600,
            minimum=300,
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

    async def extract_facts(
        self,
        evidence_items: list[dict[str, Any]],
        rule_facts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        provider = self.provider
        model = self.model
        if not provider or not model:
            raise ValueError("Knowledge fact LLM is not configured.")

        eligible = [
            evidence
            for evidence in evidence_items
            if evidence.get("id")
            and (
                evidence.get("analysis_dimension_id")
                or evidence.get("dimension_id")
            )
            and (
                evidence.get("analysis_dimension_id")
                or evidence.get("dimension_id")
            )
            != "competitor_profile"
        ]
        batches = [
            eligible[index : index + self.batch_size]
            for index in range(0, len(eligible), self.batch_size)
        ][: self.max_batches]
        metadata: dict[str, Any] = {
            "llm_prompt_id": self.prompt_id,
            "llm_provider": provider,
            "llm_model": model,
            "llm_concurrency": self.concurrency,
            "llm_timeout_seconds": self.timeout_seconds,
            "llm_batch_size": self.batch_size,
            "llm_batch_cap": self.max_batches,
            "llm_batch_count": len(batches),
            "llm_input_evidence_count": len(eligible),
            "llm_rule_fact_count": len(rule_facts or []),
            "llm_success_count": 0,
            "llm_failed_count": 0,
            "llm_fallback_count": 0,
            "llm_generated_fact_count": 0,
            "llm_cost": 0.0,
            "llm_prompt_chars": 0,
        }
        if not batches:
            return {"facts": [], "metadata": metadata}

        semaphore = asyncio.Semaphore(self.concurrency)
        results = await asyncio.gather(
            *[
                self._extract_batch_with_guard(
                    semaphore,
                    batch,
                    batch_index=batch_index,
                    provider=provider,
                    model=model,
                )
                for batch_index, batch in enumerate(batches, start=1)
            ]
        )
        facts: list[dict[str, Any]] = []
        for result in results:
            result_metadata = result.get("metadata", {}) or {}
            facts.extend(result.get("facts", []) or [])
            if result_metadata.get("llm_success"):
                metadata["llm_success_count"] += 1
            if result_metadata.get("llm_failed"):
                metadata["llm_failed_count"] += 1
            if result_metadata.get("llm_fallback"):
                metadata["llm_fallback_count"] += 1
            metadata["llm_cost"] += float(result_metadata.get("llm_cost", 0.0))
            metadata["llm_prompt_chars"] += int(
                result_metadata.get("llm_prompt_chars", 0)
            )
        metadata["llm_cost"] = round(metadata["llm_cost"], 6)
        metadata["llm_generated_fact_count"] = len(facts)
        return {"facts": facts, "metadata": metadata}

    async def _extract_batch_with_guard(
        self,
        semaphore: asyncio.Semaphore,
        evidence_batch: list[dict[str, Any]],
        *,
        batch_index: int,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    self._extract_batch(
                        evidence_batch,
                        batch_index=batch_index,
                        provider=provider,
                        model=model,
                    ),
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:
                return {
                    "facts": [],
                    "metadata": {
                        "llm_failed": True,
                        "llm_fallback": True,
                        "llm_failure_type": type(exc).__name__,
                    },
                }

    async def _extract_batch(
        self,
        evidence_batch: list[dict[str, Any]],
        *,
        batch_index: int,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        llm_cost = 0.0

        def add_cost(cost: float) -> None:
            nonlocal llm_cost
            llm_cost += float(cost)

        prompt = self._prompt(evidence_batch)
        response = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            cost_callback=add_cost,
            rivalens_operation="knowledge_fact_extraction",
            rivalens_trace_context={
                "batch_index": batch_index,
                "evidence_ids": [
                    evidence.get("id", "") for evidence in evidence_batch
                ],
            },
            rivalens_evidence_count=len(evidence_batch),
        )
        parsed = json_repair.loads(response)
        facts = parsed.get("facts", []) if isinstance(parsed, dict) else parsed
        if not isinstance(facts, list):
            raise ValueError("Knowledge fact LLM response must include a facts list.")
        return {
            "facts": facts,
            "metadata": {
                "llm_success": True,
                "llm_cost": round(llm_cost, 6),
                "llm_prompt_chars": len(prompt),
            },
        }

    def _prompt(self, evidence_batch: list[dict[str, Any]]) -> str:
        payload = {
            "evidence_items": [
                {
                    "id": evidence.get("id", ""),
                    "competitor": evidence.get("competitor", ""),
                    "analysis_dimension_id": evidence.get("analysis_dimension_id")
                    or evidence.get("dimension_id")
                    or "",
                    "dimension_name": evidence.get("dimension_name", ""),
                    "source_type": evidence.get("source_type", ""),
                    "title": clean_text(evidence.get("title", ""))[:180],
                    "text": self._evidence_text_for_prompt(evidence),
                }
                for evidence in evidence_batch
            ],
            "allowed_fact_types": sorted(FACT_TYPES),
        }
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        return f"""Return strict JSON only.

Extract concise atomic KnowledgeFact candidates from the provided public evidence.

Required JSON shape:
{{"facts": [{{"evidence_ids": ["ev_id"], "competitor": "name", "analysis_dimension_id": "dimension_id", "fact_type": "feature_presence", "subject": "short subject", "predicate": "describes", "object": "atomic evidence-bound object", "statement": "one evidence-bound sentence", "confidence": 0.0}}]}}

Rules:
- Use only evidence IDs shown in evidence_items. Every fact must include at least one evidence_id.
- Do not generate competitor_profile facts.
- Do not write strategy, SWOT, TOWS, recommendations, rankings, or superiority claims unless directly stated in evidence.
- Do not generate gap placeholders such as "public evidence is insufficient".
- Keep each fact atomic; split pricing, feature, target user, compliance, integration, and market signals when they are distinct.

Input:
{payload_json}
"""

    def _evidence_text_for_prompt(self, evidence: dict[str, Any]) -> str:
        snippets = evidence.get("evidence_snippets", []) or []
        snippet_text = " ".join(
            str(snippet.get("text", "") or "").strip()
            for snippet in snippets[:4]
            if str(snippet.get("text", "") or "").strip()
        )
        text = " ".join(
            str(value or "")
            for value in (
                snippet_text,
                evidence.get("summary", ""),
                evidence.get("excerpt", ""),
                evidence.get("text", ""),
            )
        )
        return clean_source_text(text)[: self.max_evidence_chars]

    def _llm_spec_from_env(self) -> str | None:
        return os.getenv("RIVALENS_KNOWLEDGE_FACT_LLM") or os.getenv(
            "KNOWLEDGE_FACT_LLM"
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


class KnowledgeStructuringAgent:
    def __init__(
        self,
        snippet_builder: EvidenceSnippetBuilder | None = None,
        fact_extractor: KnowledgeFactLLMExtractor | None = None,
    ) -> None:
        self.snippet_builder = snippet_builder or EvidenceSnippetBuilder()
        self.fact_extractor = (
            fact_extractor
            if fact_extractor is not None
            else KnowledgeFactLLMExtractor()
        )

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        evidence_message = latest_message_for(
            state,
            receiver="knowledge_structuring",
            message_type="evidence",
            sender="collection",
        )
        industry_direction_plan = state.get("industry_direction_plan", {})
        evidence_items = self._accepted_evidence_items(state)
        snippet_stats = self.snippet_builder.enrich(
            evidence_items,
            state.get("research_branches", []),
        )

        knowledge_facts, fact_extraction = await self._build_knowledge_facts_with_metadata_async(
            evidence_items,
        )
        knowledge_fact_packages = self._build_knowledge_fact_packages(
            knowledge_facts,
        )
        knowledge = self._build_competitor_knowledge(evidence_items)
        competitors = self._enrich_competitors(
            state.get("competitors") or task.get("competitors", []),
            evidence_items,
            industry_direction_plan,
        )
        message = create_agent_message(
            sender="knowledge_structuring",
            receiver="analysis",
            message_type="schema",
            payload={
                "knowledge_count": len(knowledge),
                "competitor_knowledge": knowledge,
                "knowledge_facts": knowledge_facts,
                "knowledge_fact_packages": knowledge_fact_packages,
            },
            evidence_ids=[
                evidence_id
                for item in knowledge
                for evidence_id in item.get("evidence_ids", [])
            ],
        )

        return {
            "evidence_items": state.get("evidence_items", []),
            "competitors": competitors,
            "knowledge_facts": knowledge_facts,
            "knowledge_fact_packages": knowledge_fact_packages,
            "competitor_knowledge": knowledge,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "knowledge_structuring",
                    "action": "extract_competitor_knowledge",
                    "input": {
                        "query": task.get("query", ""),
                        "evidence_count": len(evidence_items),
                        "selected_industry": (
                            industry_direction_plan.get("industry") or {}
                        ).get("industry_id"),
                        "message_id": evidence_message.get("id") if evidence_message else None,
                    },
                    "output": {
                        "knowledge_count": len(knowledge),
                        "knowledge_fact_count": len(knowledge_facts),
                        "knowledge_fact_package_count": len(knowledge_fact_packages),
                        "evidence_snippet_enriched_count": snippet_stats.get(
                            "evidence_snippet_enriched_count",
                            0,
                        ),
                        "evidence_snippet_count": snippet_stats.get(
                            "evidence_snippet_count",
                            0,
                        ),
                        "knowledge_fact_source": fact_extraction.get("source", ""),
                        "knowledge_fact_llm_configured": fact_extraction.get(
                            "llm_configured",
                            False,
                        ),
                        "knowledge_fact_llm_concurrency": fact_extraction.get(
                            "llm_concurrency",
                            0,
                        ),
                        "knowledge_fact_llm_timeout_seconds": fact_extraction.get(
                            "llm_timeout_seconds",
                            0,
                        ),
                        "knowledge_fact_llm_batch_size": fact_extraction.get(
                            "llm_batch_size",
                            0,
                        ),
                        "knowledge_fact_llm_batch_cap": fact_extraction.get(
                            "llm_batch_cap",
                            0,
                        ),
                        "knowledge_fact_llm_success_count": fact_extraction.get(
                            "llm_success_count",
                            0,
                        ),
                        "knowledge_fact_llm_failed_count": fact_extraction.get(
                            "llm_failed_count",
                            0,
                        ),
                        "knowledge_fact_llm_fallback_count": fact_extraction.get(
                            "llm_fallback_count",
                            0,
                        ),
                        "knowledge_fact_llm_generated_fact_count": fact_extraction.get(
                            "llm_generated_fact_count",
                            0,
                        ),
                        "knowledge_fact_llm_cost": fact_extraction.get(
                            "llm_cost",
                            0.0,
                        ),
                        "knowledge_fact_llm_prompt_chars": fact_extraction.get(
                            "llm_prompt_chars",
                            0,
                        ),
                        "rule_input_evidence_count": fact_extraction.get(
                            "rule_input_evidence_count",
                            0,
                        ),
                        "rule_skipped_evidence_count": fact_extraction.get(
                            "rule_skipped_evidence_count",
                            0,
                        ),
                        "rule_semantic_noise_count": fact_extraction.get(
                            "rule_semantic_noise_count",
                            0,
                        ),
                        "rule_context_trimmed_count": fact_extraction.get(
                            "rule_context_trimmed_count",
                            0,
                        ),
                        "atomization_too_broad_count": fact_extraction.get(
                            "atomization_too_broad_count",
                            0,
                        ),
                        "atomization_split_count": fact_extraction.get(
                            "atomization_split_count",
                            0,
                        ),
                        "atomization_rejected_count": fact_extraction.get(
                            "atomization_rejected_count",
                            0,
                        ),
                        "profile_count": len(
                            [
                                competitor
                                for competitor in competitors
                                if competitor.get("evidence_ids")
                            ]
                        ),
                        "profile_website_count": len(
                            [
                                competitor
                                for competitor in competitors
                                if competitor.get("website")
                            ]
                        ),
                    },
                }
            ],
        }

    def _build_competitor_knowledge(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> list[CompetitorKnowledge]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for evidence in evidence_items:
            competitor = evidence.get("competitor") or "unknown"
            grouped[competitor].append(evidence)

        if not grouped and evidence_items:
            grouped["unknown"] = list(evidence_items)

        knowledge_items: list[CompetitorKnowledge] = []
        for index, (competitor, competitor_evidence) in enumerate(grouped.items(), start=1):
            evidence_ids = [item.get("id", "") for item in competitor_evidence if item.get("id")]
            feature_tree = []
            pricing_plans = []
            persona_signals = []

            for feature_index, evidence in enumerate(competitor_evidence, start=1):
                if self._evidence_analysis_dimension_id(evidence) == "competitor_profile":
                    continue
                evidence_id = evidence.get("id", "")
                text = (
                    evidence.get("excerpt")
                    or evidence.get("title")
                    or ""
                )
                text = clean_text(text)
                if not text:
                    continue
                if is_low_quality_text(text):
                    continue
                source_type = evidence.get("source_type", "other")
                confidence = evidence.get("confidence", 0.5)
                title = clean_text(evidence.get("title", ""))
                if title and is_low_quality_text(title):
                    title = ""
                normalized_text = f"{title} {text}".lower()

                if (
                    source_type == "pricing_page"
                    or "pricing" in normalized_text
                    or "price" in normalized_text
                ):
                    pricing_plans.append(
                        {
                            "id": f"plan_{index}_{len(pricing_plans) + 1}",
                            "name": title or "Observed pricing signal",
                            "billing_unit": "unknown",
                            "price": None,
                            "currency": None,
                            "pricing_visibility": "observed_public_signal",
                            "included_features": [],
                            "evidence_ids": [evidence_id] if evidence_id else [],
                            "confidence": confidence,
                        }
                    )
                    continue

                if any(
                    keyword in normalized_text
                    for keyword in ["customer", "user", "persona", "segment", "用户", "客户"]
                ):
                    persona_signals.append(
                        {
                            "id": f"persona_{index}_{len(persona_signals) + 1}",
                            "segment": title or "Observed user segment",
                            "needs": [text[:220]],
                            "jobs_to_be_done": [],
                            "buying_triggers": [],
                            "evidence_ids": [evidence_id] if evidence_id else [],
                            "confidence": confidence,
                        }
                    )
                    continue

                feature_tree.append(
                    {
                        "id": f"feature_{index}_{feature_index}",
                        "category": "core_feature",
                        "name": title or text[:80],
                        "description": text[:500],
                        "availability": "unknown",
                        "evidence_ids": [evidence_id] if evidence_id else [],
                        "confidence": confidence,
                    }
                )

            knowledge_items.append(
                {
                    "id": f"knowledge_{index}",
                    "competitor": competitor,
                    "feature_tree": feature_tree,
                    "pricing_model": {
                        "plans": pricing_plans,
                        "notes": "Pricing signals extracted from public evidence.",
                        "evidence_ids": [
                            evidence_id
                            for plan in pricing_plans
                            for evidence_id in plan.get("evidence_ids", [])
                        ],
                        "confidence": self._average_confidence(pricing_plans),
                    },
                    "user_personas": persona_signals,
                    "evidence_ids": evidence_ids,
                    "confidence": self._average_confidence(competitor_evidence),
                }
            )

        return knowledge_items

    def _build_knowledge_facts_with_metadata(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, Any]]:
        facts, stats = self._build_knowledge_facts_with_stats(
            evidence_items,
        )
        stats["source"] = "rule"
        stats["knowledge_fact_count"] = len(facts)
        stats["rule_input_evidence_count"] = len(evidence_items)
        return facts, stats

    async def _build_knowledge_facts_with_metadata_async(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, Any]]:
        rule_facts, stats = self._build_knowledge_facts_with_metadata(
            evidence_items,
        )
        extractor = self.fact_extractor
        configured = self._fact_extractor_configured(extractor)
        stats.update(
            {
                "llm_configured": configured,
                "llm_provider": getattr(extractor, "provider", None) or "",
                "llm_model": getattr(extractor, "model", None) or "",
                "llm_concurrency": (
                    int(getattr(extractor, "concurrency", 0) or 0)
                    if configured
                    else 0
                ),
                "llm_timeout_seconds": (
                    int(getattr(extractor, "timeout_seconds", 0) or 0)
                    if configured
                    else 0
                ),
                "llm_batch_size": (
                    int(getattr(extractor, "batch_size", 0) or 0)
                    if configured
                    else 0
                ),
                "llm_batch_cap": (
                    int(getattr(extractor, "max_batches", 0) or 0)
                    if configured
                    else 0
                ),
                "llm_batch_count": 0,
                "llm_success_count": 0,
                "llm_failed_count": 0,
                "llm_fallback_count": 0,
                "llm_generated_fact_count": 0,
                "llm_valid_fact_count": 0,
                "llm_invalid_fact_count": 0,
                "llm_invalid_evidence_id_count": 0,
                "llm_cost": 0.0,
                "llm_prompt_chars": 0,
            }
        )
        if not configured:
            return rule_facts, stats

        try:
            result = await extractor.extract_facts(
                evidence_items=evidence_items,
                rule_facts=rule_facts,
            )
        except Exception as exc:
            stats.update(
                {
                    "llm_failed_count": 1,
                    "llm_fallback_count": 1,
                    "llm_failure_type": type(exc).__name__,
                    "knowledge_fact_count": len(rule_facts),
                }
            )
            return rule_facts, stats

        llm_metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
        if isinstance(llm_metadata, dict):
            stats.update(llm_metadata)

        candidates = result.get("facts", []) if isinstance(result, dict) else []
        llm_facts, validation = self._validated_llm_facts(candidates, evidence_items)
        stats.update(validation)
        if not llm_facts:
            stats["source"] = "rule"
            stats["knowledge_fact_count"] = len(rule_facts)
            if stats.get("llm_batch_count", 0):
                stats["llm_fallback_count"] = max(
                    1,
                    int(stats.get("llm_fallback_count", 0) or 0),
                )
            return rule_facts, stats

        facts = self._merge_rule_and_llm_facts(rule_facts, llm_facts)
        stats["source"] = "rule+llm"
        stats["knowledge_fact_count"] = len(facts)
        stats["llm_valid_fact_count"] = len(llm_facts)
        return facts, stats

    def _build_knowledge_facts(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> list[KnowledgeFact]:
        facts, _stats = self._build_knowledge_facts_with_stats(evidence_items)
        return facts

    def _fact_extractor_configured(self, extractor: Any) -> bool:
        if extractor is None:
            return False
        is_configured = getattr(extractor, "is_configured", None)
        if callable(is_configured):
            return bool(is_configured())
        return True

    def _validated_llm_facts(
        self,
        candidates: Any,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, int]]:
        if not isinstance(candidates, list):
            return [], {
                "llm_invalid_fact_count": 1,
                "llm_invalid_evidence_id_count": 0,
            }

        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }
        facts: list[KnowledgeFact] = []
        invalid_fact_count = 0
        invalid_evidence_id_count = 0
        for candidate in candidates:
            fact, invalid_evidence_ids = self._llm_fact_from_candidate(
                candidate,
                evidence_by_id,
            )
            invalid_evidence_id_count += invalid_evidence_ids
            if not fact:
                invalid_fact_count += 1
                continue
            finding = self._atomization_finding(fact, evidence_by_id)
            if finding.get("status") == "too_broad":
                invalid_fact_count += 1
                continue
            facts.append(fact)
        return facts, {
            "llm_invalid_fact_count": invalid_fact_count,
            "llm_invalid_evidence_id_count": invalid_evidence_id_count,
        }

    def _llm_fact_from_candidate(
        self,
        candidate: Any,
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> tuple[KnowledgeFact | None, int]:
        if not isinstance(candidate, dict):
            return None, 0
        raw_ids = candidate.get("evidence_ids", [])
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, list):
            return None, 0
        evidence_ids = self._dedupe(
            str(evidence_id)
            for evidence_id in raw_ids
            if str(evidence_id) in evidence_by_id
        )
        invalid_evidence_ids = len(
            [
                evidence_id
                for evidence_id in raw_ids
                if str(evidence_id) not in evidence_by_id
            ]
        )
        if not evidence_ids:
            return None, invalid_evidence_ids

        primary_evidence = evidence_by_id[evidence_ids[0]]
        analysis_dimension_id = str(
            candidate.get("analysis_dimension_id")
            or self._evidence_analysis_dimension_id(primary_evidence)
            or ""
        )
        if not analysis_dimension_id or analysis_dimension_id == "competitor_profile":
            return None, invalid_evidence_ids

        statement = clean_text(candidate.get("statement", ""))
        fact_object = clean_text(candidate.get("object", "") or statement)
        if not fact_object or is_low_quality_text(fact_object):
            return None, invalid_evidence_ids
        fact_type = str(candidate.get("fact_type", "") or "")
        if fact_type not in FACT_TYPES:
            fact_type = self._fact_type_for_evidence(
                primary_evidence,
                analysis_dimension_id,
                fact_object,
            )
        subject = clean_text(candidate.get("subject", "")) or self._fact_subject(
            primary_evidence,
        )
        predicate = clean_text(candidate.get("predicate", "")) or self._predicate_for_fact_type(
            fact_type,
        )
        fact_object = fact_object[:GENERIC_FACT_OBJECT_CHARS]
        if not statement:
            statement = self._fact_statement(subject, predicate, fact_object)
        else:
            statement = statement[:700]

        competitor = clean_text(candidate.get("competitor", "")) or str(
            primary_evidence.get("competitor", "")
        )
        qualifiers = (
            dict(candidate.get("qualifiers", {}))
            if isinstance(candidate.get("qualifiers"), dict)
            else {}
        )
        qualifiers.update(
            {
                "source": "llm_fact_extraction",
                "source_type": primary_evidence.get("source_type", ""),
                "title": primary_evidence.get("title", ""),
                "url": primary_evidence.get("url", ""),
                "dimension_name": primary_evidence.get("dimension_name", ""),
            }
        )
        normalized_key = clean_text(candidate.get("normalized_key", "")) or self._fact_normalized_key(
            competitor=competitor,
            dimension=analysis_dimension_id,
            fact_type=fact_type,
            predicate=predicate,
            fact_object=fact_object,
        )
        evidence_confidence = self._average_confidence(
            [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
        )
        confidence = min(
            evidence_confidence,
            self._bounded_confidence(candidate.get("confidence", evidence_confidence)),
        )
        value = (
            dict(candidate.get("value", {}))
            if isinstance(candidate.get("value"), dict)
            else {}
        )
        value.setdefault("object", fact_object)
        return {
            "id": "",
            "competitor": competitor,
            "analysis_dimension_id": analysis_dimension_id,
            "schema_field_id": "",
            "fact_type": fact_type,
            "subject": subject[:180],
            "predicate": predicate[:80],
            "object": fact_object,
            "qualifiers": qualifiers,
            "normalized_key": normalized_key,
            "statement": statement,
            "value": value,
            "evidence_ids": evidence_ids,
            "report_section_id": primary_evidence.get("report_section_id", ""),
            "confidence": round(confidence, 2),
        }, invalid_evidence_ids

    def _merge_rule_and_llm_facts(
        self,
        rule_facts: list[KnowledgeFact],
        llm_facts: list[KnowledgeFact],
    ) -> list[KnowledgeFact]:
        facts_by_key: dict[str, KnowledgeFact] = {}
        for fact in [*rule_facts, *llm_facts]:
            fact_copy = dict(fact)
            fact_copy["id"] = ""
            key = fact_copy.get("normalized_key", "")
            if not key:
                continue
            if key in facts_by_key:
                facts_by_key[key] = self._merge_fact(facts_by_key[key], fact_copy)
            else:
                facts_by_key[key] = fact_copy

        facts = list(facts_by_key.values())
        for index, fact in enumerate(facts, start=1):
            fact["id"] = f"fact_{index}"
        return facts

    def _build_knowledge_fact_packages(
        self,
        knowledge_facts: list[KnowledgeFact],
    ) -> list[KnowledgeFactPackage]:
        grouped: dict[tuple[str, str], list[KnowledgeFact]] = defaultdict(list)
        for fact in knowledge_facts:
            if not self._usable_package_fact(fact):
                continue
            key = (
                str(fact.get("competitor", "") or "the target competitor"),
                str(fact.get("analysis_dimension_id", "")),
            )
            grouped[key].append(fact)

        packages: list[KnowledgeFactPackage] = []
        for index, ((competitor, analysis_dimension_id), facts) in enumerate(
            grouped.items(),
            start=1,
        ):
            knowledge_fact_ids = self._dedupe(
                fact.get("id", "")
                for fact in facts
                if fact.get("id")
            )
            evidence_ids = self._dedupe(
                evidence_id
                for fact in facts
                for evidence_id in fact.get("evidence_ids", [])
                if evidence_id
            )
            packages.append(
                {
                    "id": f"fact_package_{index}",
                    "competitor": competitor,
                    "analysis_dimension_id": analysis_dimension_id,
                    "report_section_id": next(
                        (
                            str(fact.get("report_section_id", ""))
                            for fact in facts
                            if fact.get("report_section_id")
                        ),
                        "",
                    ),
                    "knowledge_fact_ids": knowledge_fact_ids,
                    "evidence_ids": evidence_ids,
                    "fact_type_hints": self._dedupe(
                        fact.get("fact_type", "")
                        for fact in facts
                        if fact.get("fact_type")
                    ),
                    "normalized_key": self._package_normalized_key(
                        competitor,
                        analysis_dimension_id,
                    ),
                    "fact_count": len(knowledge_fact_ids),
                    "confidence": self._average_confidence(facts),
                }
            )
        return packages

    def _build_knowledge_facts_with_stats(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, int]]:
        facts_by_key: dict[str, KnowledgeFact] = {}
        stats = self._empty_atomization_stats()
        for evidence in evidence_items:
            facts, finding = self._fact_candidates_from_evidence_with_finding(evidence)
            self._add_atomization_finding(stats, finding)
            if finding.get("status") == "too_broad" and not facts:
                stats["atomization_rejected_count"] += 1
            for fact in facts:
                key = fact.get("normalized_key", "")
                if not key:
                    continue
                if key in facts_by_key:
                    facts_by_key[key] = self._merge_fact(facts_by_key[key], fact)
                else:
                    facts_by_key[key] = fact
                    if finding.get("status") == "split":
                        stats["atomization_split_count"] += 1

        facts = list(facts_by_key.values())
        for index, fact in enumerate(facts, start=1):
            fact["id"] = f"fact_{index}"
        return facts, stats

    def _empty_atomization_stats(self) -> dict[str, int]:
        return {
            "rule_skipped_evidence_count": 0,
            "rule_semantic_noise_count": 0,
            "rule_context_trimmed_count": 0,
            "atomization_too_broad_count": 0,
            "atomization_split_count": 0,
            "atomization_rejected_count": 0,
        }

    def _add_atomization_finding(
        self,
        stats: dict[str, int],
        finding: dict[str, Any],
    ) -> None:
        if finding.get("status") == "skipped":
            stats["rule_skipped_evidence_count"] += 1
        if finding.get("reason") == "semantic_noise":
            stats["rule_semantic_noise_count"] += 1
        if finding.get("context_trimmed"):
            stats["rule_context_trimmed_count"] += 1
        if finding.get("status") == "too_broad":
            stats["atomization_too_broad_count"] += 1

    def _atomization_finding(
        self,
        fact: KnowledgeFact,
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if fact.get("fact_type") == "pricing_signal":
            qualifiers = fact.get("qualifiers", {}) or {}
            if qualifiers.get("pricing_atom_kind"):
                return {"status": "atomic"}

            detected_kinds = []
            for evidence_id in fact.get("evidence_ids", []):
                evidence = evidence_by_id.get(evidence_id, {})
                detected_kinds.extend(
                    self._detected_pricing_atom_kinds(self._evidence_text(evidence))
                )
            detected_kinds = list(dict.fromkeys(detected_kinds))
            if len(detected_kinds) > 1:
                return {
                    "status": "too_broad",
                    "reason": "multiple_pricing_atom_kinds",
                    "detected_atom_kinds": detected_kinds,
                    "recommended_action": "split",
                }

        if self._generic_too_broad_fact(fact):
            return {
                "status": "too_broad",
                "reason": "generic_multi_signal_object",
                "recommended_action": "reject",
            }
        return {"status": "atomic"}

    def _generic_too_broad_fact(self, fact: KnowledgeFact) -> bool:
        text = " ".join(
            [
                str(fact.get("subject", "")),
                str(fact.get("predicate", "")),
                str(fact.get("object", "")),
                str(fact.get("statement", "")),
            ]
        ).lower()
        broad_phrases = [
            "multiple pricing signals",
            "multiple feature signals",
            "various features",
            "various capabilities",
            "comprehensive platform capabilities",
            "多个定价信号",
            "多个功能",
            "多种功能",
        ]
        return any(phrase in text for phrase in broad_phrases)

    def _fact_candidates_from_evidence(
        self,
        evidence: dict[str, Any],
    ) -> list[KnowledgeFact]:
        facts, _finding = self._fact_candidates_from_evidence_with_finding(evidence)
        return facts

    def _fact_candidates_from_evidence_with_finding(
        self,
        evidence: dict[str, Any],
    ) -> tuple[list[KnowledgeFact], dict[str, Any]]:
        analysis_dimension_id = self._evidence_analysis_dimension_id(evidence)
        if not analysis_dimension_id:
            return [], {"status": "skipped", "reason": "missing_analysis_dimension"}
        if analysis_dimension_id == "competitor_profile":
            return [], {"status": "skipped", "reason": "competitor_profile"}

        raw_text = self._evidence_text(evidence)
        text = self._clean_evidence_text(raw_text)
        if not text or is_low_quality_text(text):
            reason = (
                "semantic_noise"
                if self._semantic_boilerplate_reason(raw_text)
                else "low_quality_text"
            )
            return [], {"status": "skipped", "reason": reason}

        semantic_noise_reason = self._semantic_boilerplate_reason(text)
        if semantic_noise_reason:
            return [], {
                "status": "skipped",
                "reason": "semantic_noise",
                "noise_reason": semantic_noise_reason,
            }

        evidence_id = evidence.get("id", "")
        schema_field_ids = list(evidence.get("schema_field_ids", []) or [])
        fact_type = self._fact_type_for_evidence(evidence, analysis_dimension_id, text)
        if fact_type == "pricing_signal":
            pricing_facts = self._pricing_fact_candidates_from_evidence(evidence, text)
            if pricing_facts:
                detected_kinds = [
                    (fact.get("qualifiers", {}) or {}).get("pricing_atom_kind", "")
                    for fact in pricing_facts
                ]
                return pricing_facts, {
                    "status": "split",
                    "reason": "pricing_atom_split",
                    "detected_atom_kinds": [
                        kind for kind in detected_kinds if kind
                    ],
                }

        predicate = self._predicate_for_fact_type(fact_type)
        subject = self._fact_subject(evidence)
        fact_object, context_trimmed = self._fact_object_with_metadata(text)
        if not fact_object:
            return [], {"status": "skipped", "reason": "semantic_noise"}
        normalized_key = self._fact_normalized_key(
            competitor=str(evidence.get("competitor", "")),
            dimension=analysis_dimension_id,
            fact_type=fact_type,
            predicate=predicate,
            fact_object=fact_object,
        )
        statement = self._fact_statement(
            subject=subject,
            predicate=predicate,
            fact_object=fact_object,
        )
        generic_fact = {
            "id": "",
            "competitor": evidence.get("competitor", ""),
            "analysis_dimension_id": analysis_dimension_id,
            "schema_field_id": schema_field_ids[0] if schema_field_ids else "",
            "fact_type": fact_type,
            "subject": subject,
            "predicate": predicate,
            "object": fact_object,
            "qualifiers": {
                "source_type": evidence.get("source_type", ""),
                "title": evidence.get("title", ""),
                "url": evidence.get("url", ""),
                "dimension_name": evidence.get("dimension_name", ""),
            },
            "normalized_key": normalized_key,
            "statement": statement,
            "value": {
                "title": evidence.get("title", ""),
                "source_type": evidence.get("source_type", ""),
                "url": evidence.get("url", ""),
                "object": fact_object,
            },
            "evidence_ids": [evidence_id] if evidence_id else [],
            "report_section_id": evidence.get("report_section_id", ""),
            "confidence": evidence.get("confidence", 0.5),
        }
        finding = self._atomization_finding(
            generic_fact,
            {evidence_id: evidence} if evidence_id else {},
        )
        if finding.get("status") == "too_broad":
            finding["context_trimmed"] = context_trimmed
            return [], finding
        return [generic_fact], {
            "status": "atomic",
            "context_trimmed": context_trimmed,
        }

    def _pricing_fact_candidates_from_evidence(
        self,
        evidence: dict[str, Any],
        text: str | None = None,
    ) -> list[KnowledgeFact]:
        analysis_dimension_id = self._evidence_analysis_dimension_id(evidence)
        text = text if text is not None else self._clean_evidence_text(
            self._evidence_text(evidence)
        )
        if not analysis_dimension_id or not text:
            return []
        kinds = self._detected_pricing_atom_kinds(text)
        facts = []
        for kind in kinds:
            if kind == "published_plan_price":
                price_details = self._published_plan_prices(text)
                if price_details:
                    facts.extend(
                        self._pricing_fact_for_kind(evidence, kind, text, price_detail)
                        for price_detail in price_details
                    )
                    continue
            facts.append(self._pricing_fact_for_kind(evidence, kind, text))
        return [fact for fact in facts if fact]

    def _detected_pricing_atom_kinds(self, text: str) -> list[str]:
        normalized = text.lower()
        kinds: list[str] = []
        if re.search(r"\bfree(?:\s+(?:plan|tier|version))?\b", normalized) or any(
            term in text for term in ["免费版", "免费套餐", "免费计划"]
        ):
            kinds.append("free_tier")
        if self._published_plan_price(text):
            kinds.append("published_plan_price")
        if (
            re.search(r"\benterprise\b", normalized)
            and re.search(r"\b(quote|quote-only|contact sales|custom pricing)\b", normalized)
        ) or any(term in text for term in ["企业版询价", "定制报价"]):
            kinds.append("quote_only")
        elif re.search(
            r"(企业版|企业|定制|报价|价格|定价|套餐|plan|enterprise).{0,24}联系销售"
            r"|联系销售.{0,24}(企业版|企业|定制|报价|价格|定价|套餐|plan|enterprise)",
            text,
            flags=re.IGNORECASE,
        ):
            kinds.append("quote_only")
        if re.search(
            r"\b(usage-based|usage based|metered|pay as you go|pay-as-you-go)\b",
            normalized,
        ) or any(term in text for term in ["按量", "按使用量", "用量计费"]):
            kinds.append("usage_based_billing")
        if (
            re.search(r"\b(annual|annually|yearly)\b", normalized)
            and re.search(r"\b(discount|save|off)\b", normalized)
        ) or any(term in text for term in ["年付优惠", "年度折扣", "包年优惠"]):
            kinds.append("annual_discount")
        return list(dict.fromkeys(kinds))

    def _pricing_fact_for_kind(
        self,
        evidence: dict[str, Any],
        kind: str,
        text: str,
        price_detail: dict[str, str] | None = None,
    ) -> KnowledgeFact | None:
        predicate = PRICING_ATOM_PREDICATES.get(kind, "publishes")
        subject = self._pricing_subject(kind, text, price_detail)
        fact_object = self._pricing_object(kind, text, price_detail)
        if not subject or not fact_object:
            return None
        schema_field_ids = list(evidence.get("schema_field_ids", []) or [])
        competitor = str(evidence.get("competitor", ""))
        analysis_dimension_id = self._evidence_analysis_dimension_id(evidence)
        normalized_key = self._fact_normalized_key(
            competitor=competitor,
            dimension=analysis_dimension_id,
            fact_type="pricing_signal",
            predicate=predicate,
            fact_object=f"{kind} {subject} {fact_object}",
        )
        return {
            "id": "",
            "competitor": evidence.get("competitor", ""),
            "analysis_dimension_id": analysis_dimension_id,
            "schema_field_id": schema_field_ids[0] if schema_field_ids else "",
            "fact_type": "pricing_signal",
            "subject": subject,
            "predicate": predicate,
            "object": fact_object,
            "qualifiers": {
                "pricing_atom_kind": kind,
                "source_type": evidence.get("source_type", ""),
                "title": evidence.get("title", ""),
                "url": evidence.get("url", ""),
                "dimension_name": evidence.get("dimension_name", ""),
            },
            "normalized_key": normalized_key,
            "statement": self._fact_statement(subject, predicate, fact_object),
            "value": {
                "pricing_atom_kind": kind,
                "subject": subject,
                "object": fact_object,
                "source_type": evidence.get("source_type", ""),
                "url": evidence.get("url", ""),
            },
            "evidence_ids": [evidence.get("id", "")] if evidence.get("id") else [],
            "report_section_id": evidence.get("report_section_id", ""),
            "confidence": evidence.get("confidence", 0.5),
        }

    def _published_plan_price(self, text: str) -> dict[str, str]:
        prices = self._published_plan_prices(text)
        return prices[0] if prices else {}

    def _published_plan_prices(self, text: str) -> list[dict[str, str]]:
        patterns = [
            r"\b(?P<plan>[A-Z][A-Za-z0-9+ -]{1,40})\s+(?:plan\s+)?(?:is|starts at|from|costs|priced at)\s+(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/\s*(?:user|seat|month|mo|year|yr))*)",
            r"\b(?P<plan>[A-Z][A-Za-z0-9+ -]{1,40})\s+(?:plan\s+)?(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/\s*(?:user|seat|month|mo|year|yr))*)",
            r"(?P<plan>[A-Za-z0-9+ -]{1,40})\s*版[^。；;,.]{0,30}(?P<price>[¥$]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:月|年|人|用户))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{1,24})\s*版\s*(?P<price>[¥$]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{1,24})\s*(?:定价为|价格为|收费为|每人每月)\s*(?P<price>\d+(?:[.,]\d+)?\s*元(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?)",
        ]
        prices = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                price = {
                    "plan": self._clean_pricing_plan(match.group("plan")),
                    "price": " ".join(match.group("price").split()),
                }
                if not self._valid_pricing_plan(price["plan"]):
                    continue
                if price not in prices:
                    prices.append(price)
        return prices

    def _clean_pricing_plan(self, value: str) -> str:
        plan = " ".join(str(value or "").split()).strip(" ：:-")
        if " " in plan:
            plan = plan.split()[-1]
        if (
            plan
            and re.fullmatch(r"[\u4e00-\u9fff]{1,8}", plan)
            and not plan.endswith(("版", "套餐", "计划"))
        ):
            plan = f"{plan}版"
        return plan

    def _valid_pricing_plan(self, plan: str) -> bool:
        if not plan:
            return True
        return plan.lower() not in {
            "at",
            "costs",
            "from",
            "is",
            "plan",
            "priced",
            "starts",
        }

    def _pricing_subject(
        self,
        kind: str,
        text: str,
        price_detail: dict[str, str] | None = None,
    ) -> str:
        if kind == "free_tier":
            return "Free plan"
        if kind == "published_plan_price":
            price = price_detail or self._published_plan_price(text)
            plan = price.get("plan", "").strip()
            return f"{plan} plan" if plan else "Paid plan"
        if kind == "quote_only":
            return "Enterprise plan"
        if kind == "usage_based_billing":
            return "Usage-based billing"
        if kind == "annual_discount":
            return "Annual billing"
        return ""

    def _pricing_object(
        self,
        kind: str,
        text: str,
        price_detail: dict[str, str] | None = None,
    ) -> str:
        if kind == "free_tier":
            return "free tier available"
        if kind == "published_plan_price":
            price = price_detail or self._published_plan_price(text)
            plan = price.get("plan", "paid plan").strip()
            amount = price.get("price", "public price").strip()
            return f"{plan} pricing is {amount}"
        if kind == "quote_only":
            return "Enterprise pricing requires a quote or sales contact"
        if kind == "usage_based_billing":
            return "usage-based billing is available"
        if kind == "annual_discount":
            return "annual billing discount is available"
        return ""

    def _evidence_text(self, evidence: dict[str, Any]) -> str:
        return clean_text(
            evidence.get("excerpt")
            or evidence.get("title")
            or evidence.get("url")
            or ""
        )

    def _clean_evidence_text(self, text: Any) -> str:
        return clean_source_text(text)

    def _semantic_boilerplate_reason(self, text: Any) -> str:
        value = self._clean_evidence_text(text)
        if not value:
            return "empty_after_cleaning"
        lower = value.lower()
        compact = re.sub(r"\s+", "", lower)
        if (
            "youneedtoenablejavascripttorunthisapp" in compact
            or "pleaseenablejavascript" in compact
        ):
            return "javascript_fallback"
        if re.fullmatch(r"(?:nan[-/\s]*){2,}nan", lower):
            return "invalid_date_noise"
        download_directory_reason = self._download_directory_noise_reason(value)
        if download_directory_reason:
            return download_directory_reason

        nav_hits = self._navigation_noise_hits(value)
        page_list_hits = self._page_list_noise_hits(value)
        if not self._has_concrete_signal(value):
            if nav_hits >= 4:
                return "navigation_chrome"
            if page_list_hits >= 3:
                return "page_index"
            if nav_hits >= 2 and page_list_hits >= 2:
                return "navigation_index"
        return ""

    def _has_concrete_signal(self, text: str) -> bool:
        value = str(text or "")
        lower = value.lower()
        if re.search(r"[$¥€£]\s?\d|\d+(?:[.,]\d+)?\s*(?:%|元|人|用户|月|年|gb|tb)", value):
            return True
        if re.search(r"\b(api|sdk|sso|iso\s?\d+|soc\s?2|gdpr|hipaa|enterprise|pro)\b", lower):
            return True
        if any(
            term in value
            for term in [
                "支持",
                "提供",
                "采用",
                "包括",
                "集成",
                "认证",
                "定价",
                "价格",
                "版本",
                "套餐",
                "计费",
                "额度",
                "权限",
                "项目",
                "文档",
                "会议",
                "安全",
            ]
        ):
            return True
        return any(
            term in lower
            for term in [
                "supports",
                "offers",
                "provides",
                "includes",
                "integrates",
                "certified",
                "pricing",
                "billing",
                "workflow",
                "automation",
                "security",
                "compliance",
            ]
        )

    def _navigation_noise_hits(self, text: str) -> int:
        lower = str(text or "").lower()
        chinese_terms = [
            "登录",
            "注册",
            "下载",
            "免费试用",
            "联系我们",
            "联系销售",
            "立即咨询",
            "开始使用",
            "立即体验",
        ]
        english_terms = [
            "login",
            "log in",
            "sign up",
            "download",
            "free trial",
            "contact us",
            "contact sales",
            "get started",
        ]
        return sum(term in text for term in chinese_terms) + sum(
            term in lower for term in english_terms
        )

    def _page_list_noise_hits(self, text: str) -> int:
        lower = str(text or "").lower()
        chinese_terms = [
            "热门推荐",
            "案例与方案",
            "产品功能",
            "本文目录",
            "目录",
            "相关推荐",
            "相关产品",
        ]
        english_terms = [
            "table of contents",
            "related articles",
            "recommended",
            "popular",
            "resources",
            "product features",
        ]
        return sum(term in text for term in chinese_terms) + sum(
            term in lower for term in english_terms
        )

    def _download_directory_noise_reason(self, text: str) -> str:
        value = str(text or "")
        lower = value.lower()
        directory_markers = [
            "app下载",
            "最新版下载",
            "资源下载",
            "下载价格",
            "仅限svip下载",
            "升级svip",
            "请先登录",
            "手机应用",
            "安卓系统",
            "应用类型",
            "辅助工具",
            "当前位置",
            "app内打开",
            "下载客户端",
        ]
        if not any(marker in lower or marker in value for marker in directory_markers):
            return ""
        business_markers = [
            "注册用户数",
            "企业组织数",
            "营收",
            "同比增长",
            "战略级",
            "安全合规",
            "自主可控",
            "定价",
            "计费",
            "认证",
            "api",
            "sdk",
        ]
        if any(marker in lower or marker in value for marker in business_markers):
            return ""
        return "download_directory_noise"

    def _fact_type_for_evidence(
        self,
        evidence: dict[str, Any],
        analysis_dimension_id: str,
        text: str,
    ) -> str:
        dimension = analysis_dimension_id.lower()
        source_type = str(evidence.get("source_type", "")).lower()
        corpus = " ".join(
            [
                dimension,
                source_type,
                str(evidence.get("title", "")),
                text,
            ]
        ).lower()

        if (
            "pricing" in dimension
            or "price" in corpus
            or "pricing" in corpus
            or source_type == "pricing_page"
        ):
            return "pricing_signal"
        if any(term in dimension for term in ["persona", "target_user", "user"]):
            return "target_user_signal"
        if source_type in {"review", "case_study"}:
            return "target_user_signal"
        if any(term in dimension for term in ["security", "compliance", "trust", "risk"]):
            return "trust_compliance_signal"
        if any(term in dimension for term in ["integration", "ecosystem", "api"]):
            return "integration_signal"
        if source_type in {"docs", "marketplace"}:
            return "feature_presence"
        if source_type in {"news", "analyst_report", "financial_filing"}:
            return "market_signal"
        return "public_evidence_signal"

    def _predicate_for_fact_type(self, fact_type: str) -> str:
        return {
            "pricing_signal": "publishes",
            "feature_presence": "describes",
            "target_user_signal": "signals",
            "trust_compliance_signal": "documents",
            "integration_signal": "documents",
            "market_signal": "reports",
            "public_evidence_signal": "indicates",
        }.get(fact_type, "indicates")

    def _fact_subject(self, evidence: dict[str, Any]) -> str:
        competitor = str(evidence.get("competitor", "") or "the competitor")
        dimension_name = clean_text(
            evidence.get("dimension_name") or evidence.get("analysis_dimension_id", "")
        )
        if dimension_name and not is_low_quality_text(dimension_name):
            return f"{competitor} {dimension_name}".strip()
        title = clean_text(evidence.get("title", ""))
        if title and not is_low_quality_text(title):
            title_subject = self._concise_title(title)
            if title_subject:
                if competitor.lower() in title_subject.lower():
                    return title_subject[:120]
                return f"{competitor} {title_subject[:100]}".strip()
        return competitor.strip() or "the competitor"

    def _fact_object(self, evidence: dict[str, Any], text: str) -> str:
        fact_object, _context_trimmed = self._fact_object_with_metadata(text)
        return fact_object

    def _fact_object_with_metadata(
        self,
        text: str,
    ) -> tuple[str, bool]:
        cleaned_text = self._clean_evidence_text(text)
        fact_context = self._trim_fact_boilerplate(cleaned_text)
        if not fact_context:
            return "", False
        context_trimmed = len(fact_context) < len(" ".join(cleaned_text.split()))
        return fact_context, context_trimmed

    def _concise_title(self, title: Any) -> str:
        value = " ".join(clean_text(title).split())
        value = re.split(r"\s*[|｜]\s*", value)[0]
        value = re.split(r"\s+-\s+", value)[0]
        value = value.strip(" -_：:|")
        return value[:120]

    def _trim_fact_boilerplate(self, text: str) -> str:
        value = " ".join(str(text or "").split()).strip()
        if not value:
            return ""
        if self._download_directory_noise_reason(value):
            return ""

        if len(value) > 120 and (
            self._navigation_noise_hits(value) or self._page_list_noise_hits(value)
        ):
            marker = re.search(
                r"[\u4e00-\u9fffA-Za-z0-9 xX-]{0,32}"
                r"(?:支持|提供|采用|包括|包含|集成|认证|定价|计费|突破|超过|"
                r"同比增长|宣布|发布|定位|覆盖|提升|打造|实现|面向|围绕|"
                r"适用范围|随着|战略级|安全合规|自主可控|supports|offers|"
                r"provides|includes|integrates|certified|pricing|billing)",
                value,
                flags=re.IGNORECASE,
            )
            if marker and marker.start() > 0:
                value = value[marker.start() :].strip(" ,，。；;:-")
        value = self._trim_trailing_boilerplate(value)
        return value[:GENERIC_FACT_OBJECT_CHARS]

    def _trim_trailing_boilerplate(self, text: str) -> str:
        value = str(text or "")
        trailing_markers = [
            "热门推荐",
            "案例与方案",
            "本文目录",
            "相关推荐",
            "相关产品",
            "table of contents",
            "related articles",
            "recommended",
        ]
        marker_positions = [
            value.lower().find(marker.lower())
            for marker in trailing_markers
            if value.lower().find(marker.lower()) > 40
        ]
        if marker_positions:
            value = value[: min(marker_positions)].strip(" ,，。；;:-")
        return value

    def _fact_statement(self, subject: str, predicate: str, fact_object: str) -> str:
        return f"{subject} {predicate} {fact_object}".strip()[:700]

    def _fact_normalized_key(
        self,
        competitor: str,
        dimension: str,
        fact_type: str,
        predicate: str,
        fact_object: str,
    ) -> str:
        object_signature = self._fact_object_signature(fact_type, fact_object)
        parts = [
            self._slug(competitor or "unknown"),
            self._slug(dimension or "unknown"),
            self._slug(fact_type or "signal"),
            self._slug(predicate or "indicates"),
            object_signature,
        ]
        return "|".join(parts)

    def _fact_object_signature(self, fact_type: str, fact_object: str) -> str:
        normalized = " ".join(clean_text(fact_object).lower().split())
        if not normalized:
            return "signal"
        prefix = "_".join(self._key_terms(normalized)[:8]) or "signal"
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
        return f"{prefix}_{digest}"

    def _key_terms(self, text: str) -> list[str]:
        stopwords = {
            "about",
            "and",
            "are",
            "for",
            "from",
            "has",
            "have",
            "into",
            "its",
            "the",
            "their",
            "this",
            "that",
            "with",
        }
        normalized = str(text or "").lower()
        terms = [
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) > 2 and token not in stopwords
        ]
        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
            terms.extend(
                segment[index : index + 2]
                for index in range(0, max(1, len(segment) - 1))
            )
        return list(dict.fromkeys(terms))

    def _slug(self, value: str) -> str:
        return (
            "_".join(self._key_terms(value)[:6])
            or re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", str(value).lower()).strip("_")
            or "unknown"
        )

    def _merge_fact(
        self,
        existing: KnowledgeFact,
        incoming: KnowledgeFact,
    ) -> KnowledgeFact:
        evidence_ids = list(
            dict.fromkeys(
                list(existing.get("evidence_ids", []) or [])
                + list(incoming.get("evidence_ids", []) or [])
            )
        )
        confidences = [
            float(value)
            for value in [existing.get("confidence"), incoming.get("confidence")]
            if value is not None
        ]
        qualifiers = dict(existing.get("qualifiers", {}) or {})
        source_urls = list(qualifiers.get("source_urls", []) or [])
        for fact in [existing, incoming]:
            url = (fact.get("qualifiers", {}) or {}).get("url")
            if url and url not in source_urls:
                source_urls.append(url)
        if source_urls:
            qualifiers["source_urls"] = source_urls
        return {
            **existing,
            "evidence_ids": evidence_ids,
            "qualifiers": qualifiers,
            "confidence": round(sum(confidences) / len(confidences), 2)
            if confidences
            else existing.get("confidence", 0.5),
        }

    def _enrich_competitors(
        self,
        competitors: list[Any],
        evidence_items: list[dict[str, Any]],
        industry_direction_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        profiles_by_competitor: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for evidence in evidence_items:
            if self._evidence_analysis_dimension_id(evidence) != "competitor_profile":
                continue
            competitor = self._profile_key(evidence.get("competitor", ""))
            if competitor:
                profiles_by_competitor[competitor].append(evidence)

        normalized = self._normalize_competitors(competitors)
        if not normalized:
            normalized = [
                {"name": evidence.get("competitor", "")}
                for evidence in evidence_items
                if self._evidence_analysis_dimension_id(evidence) == "competitor_profile"
                and evidence.get("competitor")
            ]

        selected_industry = (industry_direction_plan.get("industry") or {}).get("name", "")
        enriched = []
        for competitor in normalized:
            profile = dict(competitor)
            name = str(profile.get("name", "")).strip()
            related = profiles_by_competitor.get(self._profile_key(name), [])
            best_evidence = self._best_profile_evidence(related)
            evidence_ids = [item.get("id", "") for item in related if item.get("id")]

            if name and not profile.get("product"):
                profile["product"] = name
            if best_evidence and not profile.get("website"):
                website = self._profile_website(best_evidence)
                if website:
                    profile["website"] = website
            if selected_industry and not profile.get("category"):
                profile["category"] = selected_industry
            if best_evidence and not profile.get("notes"):
                profile["notes"] = self._profile_note(best_evidence)
            if evidence_ids:
                profile["evidence_ids"] = list(dict.fromkeys(evidence_ids))
                profile["confidence"] = self._average_confidence(related)

            enriched.append(profile)

        return enriched

    def _normalize_competitors(self, competitors: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for competitor in competitors:
            if isinstance(competitor, str):
                name = competitor.strip()
                if name:
                    normalized.append({"name": name})
                continue
            name = str(competitor.get("name", "")).strip()
            if not name:
                continue
            normalized.append(
                {
                    "name": name,
                    "product": competitor.get("product", ""),
                    "website": competitor.get("website", ""),
                    "category": competitor.get("category", ""),
                    "notes": competitor.get("notes", ""),
                    "evidence_ids": list(competitor.get("evidence_ids", []) or []),
                    "confidence": competitor.get("confidence", 0.5),
                }
            )
        return normalized

    def _profile_key(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _best_profile_evidence(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not evidence_items:
            return None
        return sorted(
            evidence_items,
            key=lambda evidence: (
                -self._profile_evidence_score(evidence),
                -float(evidence.get("confidence", 0.5)),
            ),
        )[0]

    def _profile_evidence_score(self, evidence: dict[str, Any]) -> int:
        text = self._profile_evidence_text(evidence)
        marker_text = self._profile_evidence_marker_text(evidence)
        score = 0
        if evidence.get("source_type") == "official_site":
            score += 4
        if evidence.get("is_primary_source"):
            score += 1
        if self._has_official_profile_marker(marker_text):
            score += 3
        if any(marker in text for marker in ("homepage", "website", "canonical")):
            score += 1
        return score

    def _profile_website(self, evidence: dict[str, Any]) -> str:
        url = str(evidence.get("url") or "").strip()
        if not url:
            return ""
        if not self._looks_like_official_profile_evidence(evidence):
            return ""

        parsed = urlsplit(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        hostname = (parsed.hostname or "").lower()
        netloc = parsed.netloc.lower()
        if self._has_official_profile_marker(
            self._profile_evidence_marker_text(evidence)
        ):
            netloc = self._profile_site_host(hostname) or netloc
        return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))

    def _profile_site_host(self, hostname: str) -> str:
        labels = [label for label in hostname.split(".") if label]
        if len(labels) < 3:
            return hostname
        if labels[0] not in {
            "act",
            "content",
            "landing",
            "m",
            "page",
            "pages",
            "promo",
        }:
            return hostname

        public_suffix_size = 2 if tuple(labels[-2:]) in {
            ("ac", "uk"),
            ("co", "jp"),
            ("co", "kr"),
            ("co", "uk"),
            ("com", "au"),
            ("com", "cn"),
            ("com", "hk"),
            ("com", "sg"),
            ("com", "tw"),
            ("net", "cn"),
            ("org", "cn"),
        } else 1
        return ".".join(labels[-(public_suffix_size + 1):])

    def _looks_like_official_profile_evidence(self, evidence: dict[str, Any]) -> bool:
        if evidence.get("source_type") == "official_site":
            return True
        return self._has_official_profile_marker(
            self._profile_evidence_marker_text(evidence)
        )

    def _profile_evidence_text(self, evidence: dict[str, Any]) -> str:
        return " ".join(
            str(evidence.get(field) or "")
            for field in ("title", "excerpt", "summary", "url", "source_type")
        ).lower()

    def _profile_evidence_marker_text(self, evidence: dict[str, Any]) -> str:
        return " ".join(
            str(evidence.get(field) or "")
            for field in ("title", "url", "source_type")
        ).lower()

    def _has_official_profile_marker(self, text: str) -> bool:
        if any(marker in text for marker in ("非官网", "非官方", "unofficial")):
            return False
        return any(
            marker in text
            for marker in (
                "官网",
                "官方网站",
                "官方主页",
                "官方页面",
                "official site",
                "official website",
            )
        )

    def _profile_note(self, evidence: dict[str, Any]) -> str:
        text = evidence.get("excerpt") or evidence.get("title") or ""
        text = clean_text(text)
        if is_low_quality_text(text):
            return ""
        return " ".join(str(text).split())[:220]

    def _evidence_analysis_dimension_id(self, evidence: dict[str, Any]) -> str:
        return str(
            evidence.get("analysis_dimension_id")
            or evidence.get("dimension_id")
            or ""
        )

    def _usable_package_fact(self, fact: dict[str, Any]) -> bool:
        if not fact.get("id"):
            return False
        if not fact.get("analysis_dimension_id"):
            return False
        if not [evidence_id for evidence_id in fact.get("evidence_ids", []) if evidence_id]:
            return False
        statement = clean_text(fact.get("statement", ""))
        return bool(statement) and not is_low_quality_text(statement)

    def _package_normalized_key(
        self,
        competitor: str,
        analysis_dimension_id: str,
    ) -> str:
        return "|".join(
            [
                self._normalize_key_part(competitor or "unknown"),
                self._normalize_key_part(analysis_dimension_id or "unknown"),
                "knowledge_fact_package",
            ]
        )

    def _normalize_key_part(self, value: str) -> str:
        return (
            re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", str(value).lower()).strip("_")
            or "unknown"
        )

    def _dedupe(self, values: Any) -> list[Any]:
        return list(dict.fromkeys(value for value in values if value))

    def _average_confidence(self, items: list[dict[str, Any]]) -> float:
        confidences = [float(item.get("confidence", 0.5)) for item in items]
        if not confidences:
            return 0.5
        return round(sum(confidences) / len(confidences), 2)

    def _bounded_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, confidence))

    def _accepted_evidence_items(
        self,
        state: CompetitorAnalysisState,
    ) -> list[dict[str, Any]]:
        evidence_items = state.get("evidence_items", [])
        evidence_reviews = state.get("evidence_reviews", [])
        if not evidence_reviews:
            return evidence_items

        accepted_ids = {
            evidence_id
            for review in evidence_reviews
            for evidence_id in review.get("accepted_evidence_ids", [])
        }
        return [
            evidence
            for evidence in evidence_items
            if evidence.get("id") in accepted_ids
        ]
