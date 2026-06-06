"""Structure collected evidence into the active competitor knowledge schema."""

from collections import defaultdict
import json
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import json_repair
from pydantic import BaseModel, Field

from rivalens.agents.evidence_snippets import EvidenceSnippetBuilder
from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState, CompetitorKnowledge, KnowledgeFact
from rivalens.research.utils.llm import create_chat_completion
from rivalens.text_quality import clean_text, is_low_quality_text


FACT_TYPES = {
    "pricing_signal",
    "feature_presence",
    "target_user_signal",
    "trust_compliance_signal",
    "integration_signal",
    "market_signal",
    "public_evidence_signal",
}


PRICING_ATOM_PREDICATES = {
    "free_tier": "exists",
    "published_plan_price": "publishes_price",
    "quote_only": "requires_quote",
    "usage_based_billing": "uses_billing_model",
    "annual_discount": "offers_discount",
}
PRICING_PREDICATE_ATOM_KINDS = {
    predicate: atom_kind
    for atom_kind, predicate in PRICING_ATOM_PREDICATES.items()
}


class LLMKnowledgeFactCandidate(BaseModel):
    competitor: str = ""
    analysis_dimension_id: str = ""
    schema_field_id: str = ""
    fact_type: str = "public_evidence_signal"
    subject: str = ""
    predicate: str = "indicates"
    object: str = ""
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    normalized_key: str = ""
    statement: str = ""
    value: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    report_section_id: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class LLMKnowledgeFactResponse(BaseModel):
    facts: list[LLMKnowledgeFactCandidate] = Field(default_factory=list)


class KnowledgeFactLLMExtractor:
    """Extract KnowledgeFact candidates with an LLM, leaving validation to the agent."""

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
            "RIVALENS_KNOWLEDGE_FACT_LLM_MAX_TOKENS",
            2200,
            minimum=900,
        )
        self.max_evidence_items = max_evidence_items or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_MAX_EVIDENCE",
            4,
            minimum=1,
        )
        self.max_excerpt_chars = max_excerpt_chars or self._env_int(
            "RIVALENS_KNOWLEDGE_FACT_LLM_EXCERPT_CHARS",
            360,
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

    async def extract(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        provider = self.provider
        model = self.model
        if not provider or not model:
            raise ValueError("KnowledgeFact LLM extractor is not configured.")

        batches = self._scoped_batches(evidence_items)
        if not batches:
            return [], {
                "llm_prompt": "knowledge_fact_atom_extraction_v2",
                "llm_provider": provider,
                "llm_model": model,
                "llm_cost": 0.0,
                "llm_input_evidence_count": 0,
                "llm_input_evidence_ids": [],
                "llm_batch_count": 0,
                "llm_failed_batch_count": 0,
            }

        llm_cost = 0.0

        def add_cost(cost: float) -> None:
            nonlocal llm_cost
            llm_cost += float(cost)

        extracted_facts: list[dict[str, Any]] = []
        input_evidence_ids: list[str] = []
        input_evidence_count = 0
        failed_batch_count = 0
        batch_errors: list[dict[str, Any]] = []

        for batch_index, batch in enumerate(batches, start=1):
            compact_evidence = self._compact_evidence(batch)
            if not compact_evidence:
                continue
            input_evidence_count += len(compact_evidence)
            input_evidence_ids.extend(
                evidence.get("id", "")
                for evidence in compact_evidence
                if evidence.get("id")
            )
            scope_context = self._scope_context(batch)
            try:
                response = await create_chat_completion(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": self._prompt(
                                compact_evidence,
                                scope_context,
                            ),
                        }
                    ],
                    llm_provider=provider,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    cost_callback=add_cost,
                    rivalens_operation="knowledge_fact_extraction",
                    rivalens_branch_ids=[
                        scope_context["branch_id"]
                    ]
                    if scope_context.get("branch_id")
                    else [],
                    rivalens_evidence_count=len(compact_evidence),
                    rivalens_trace_context=self._trace_context_from_evidence(batch),
                    rivalens_batch_index=batch_index,
                    rivalens_batch_count=len(batches),
                )
                parsed = json_repair.loads(response)
                validated = LLMKnowledgeFactResponse.model_validate(parsed)
                extracted_facts.extend(
                    fact.model_dump()
                    for fact in validated.facts
                )
            except Exception as exc:
                failed_batch_count += 1
                if len(batch_errors) < 8:
                    batch_errors.append(
                        {
                            "batch_index": batch_index,
                            "branch_id": scope_context.get("branch_id", ""),
                            "competitor": scope_context.get("competitor", ""),
                            "analysis_dimension_id": scope_context.get(
                                "analysis_dimension_id",
                                "",
                            ),
                            "evidence_ids": [
                                evidence.get("id", "")
                                for evidence in compact_evidence
                                if evidence.get("id")
                            ],
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                        }
                    )
                continue

        return extracted_facts, {
            "llm_prompt": "knowledge_fact_atom_extraction_v2",
            "llm_provider": provider,
            "llm_model": model,
            "llm_cost": round(llm_cost, 6),
            "llm_input_evidence_count": input_evidence_count,
            "llm_input_evidence_ids": list(dict.fromkeys(input_evidence_ids)),
            "llm_batch_count": len(batches),
            "llm_failed_batch_count": failed_batch_count,
            "llm_batch_errors": batch_errors,
            "llm_max_tokens": self.max_tokens,
            "llm_max_evidence_items": self.max_evidence_items,
            "llm_max_excerpt_chars": self.max_excerpt_chars,
            "llm_scope": "competitor+analysis_dimension+report_section+branch",
        }

    def _scoped_batches(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        group_order: list[tuple[str, str, str, str]] = []
        for evidence in evidence_items:
            evidence_id = evidence.get("id", "")
            analysis_dimension_id = self._evidence_analysis_dimension_id(evidence)
            if not evidence_id or not analysis_dimension_id:
                continue
            key = (
                str(evidence.get("competitor", "") or ""),
                analysis_dimension_id,
                str(evidence.get("report_section_id", "") or ""),
                str(evidence.get("branch_id", "") or ""),
            )
            if key not in grouped:
                grouped[key] = []
                group_order.append(key)
            grouped[key].append(evidence)

        batches: list[list[dict[str, Any]]] = []
        for key in group_order:
            scoped_evidence = grouped[key]
            for index in range(0, len(scoped_evidence), self.max_evidence_items):
                batches.append(scoped_evidence[index : index + self.max_evidence_items])
        return batches

    def _compact_evidence(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        compact = []
        for evidence in evidence_items[: self.max_evidence_items]:
            evidence_id = evidence.get("id", "")
            if not evidence_id:
                continue
            excerpt = clean_text(evidence.get("excerpt") or evidence.get("title") or "")
            compact.append(
                {
                    "id": evidence_id,
                    "competitor": evidence.get("competitor", ""),
                    "analysis_dimension_id": evidence.get("analysis_dimension_id", ""),
                    "schema_field_ids": list(evidence.get("schema_field_ids", []) or []),
                    "report_section_id": evidence.get("report_section_id", ""),
                    "dimension_name": evidence.get("dimension_name", ""),
                    "source_type": evidence.get("source_type", ""),
                    "title": evidence.get("title", ""),
                    "excerpt": excerpt[: self.max_excerpt_chars],
                    "support_snippets": self._compact_snippets(
                        evidence.get("evidence_snippets", []),
                    )[:2],
                    "confidence": evidence.get("confidence", 0.5),
                }
            )
        return compact

    def _scope_context(self, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
        for evidence in evidence_items:
            if not evidence.get("id"):
                continue
            return {
                "competitor": evidence.get("competitor", ""),
                "analysis_dimension_id": self._evidence_analysis_dimension_id(evidence),
                "dimension_name": evidence.get("dimension_name", ""),
                "report_section_id": evidence.get("report_section_id", ""),
                "branch_id": evidence.get("branch_id", ""),
            }
        return {
            "competitor": "",
            "analysis_dimension_id": "",
            "dimension_name": "",
            "report_section_id": "",
            "branch_id": "",
        }

    def _trace_context_from_evidence(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for evidence in evidence_items:
            if not evidence.get("id"):
                continue
            return {
                "id": evidence.get("collection_task_id", "") or evidence.get("id", ""),
                "branch_id": evidence.get("branch_id", ""),
                "parent_branch_id": evidence.get("parent_branch_id"),
                "research_task_id": evidence.get("research_task_id", ""),
                "competitor": evidence.get("competitor", ""),
                "dimension_id": (
                    evidence.get("dimension_id", "")
                    or evidence.get("analysis_dimension_id", "")
                ),
                "dimension_name": evidence.get("dimension_name", ""),
            }
        return {}

    def _compact_snippets(
        self,
        snippets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        compact = []
        for snippet in snippets[:3]:
            text = clean_text(snippet.get("text", ""))
            if not text:
                continue
            compact.append(
                {
                    "id": snippet.get("id", ""),
                    "text": text[:220],
                    "success_criterion_id": snippet.get("success_criterion_id", ""),
                    "rank": snippet.get("rank", 0),
                    "confidence": snippet.get("confidence", 0.0),
                }
            )
        return compact

    def _prompt(
        self,
        compact_evidence: list[dict[str, Any]],
        scope_context: dict[str, Any],
    ) -> str:
        allowed_fact_types = ", ".join(sorted(FACT_TYPES))
        scope_json = json.dumps(scope_context, ensure_ascii=False, indent=2)
        evidence_json = json.dumps(compact_evidence, ensure_ascii=False, indent=2)
        return f"""Return strict JSON only. Extract atomic KnowledgeFact candidates for this scoped analysis title.

Scope:
{scope_json}

Allowed fact_type values:
{allowed_fact_types}

Required JSON shape:
{{
  "facts": [
    {{
      "competitor": "same competitor as cited evidence",
      "analysis_dimension_id": "same dimension as cited evidence",
      "schema_field_id": "optional first schema field",
      "fact_type": "one allowed value",
      "subject": "specific public source or entity",
      "predicate": "exists|publishes_price|requires_quote|uses_billing_model|offers_discount|publishes|describes|signals|documents|reports|indicates",
      "object": "atomic factual object, <= 240 chars",
      "qualifiers": {{"source_type": "official_site"}},
      "normalized_key": "stable dedupe key if obvious, else empty",
      "statement": "short fact statement grounded in cited evidence",
      "value": {{"object": "same atomic object or structured value"}},
      "evidence_ids": ["must cite one or more input evidence ids"],
      "report_section_id": "same report_section_id when available",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Use only the scoped evidence below.
- Do not classify or reassign evidence to another topic.
- Facts must stay inside Scope.analysis_dimension_id and Scope.report_section_id.
- Do not infer market leadership, superiority, causality, or strategy unless directly stated.
- Every fact must cite evidence_ids from the input.
- Prefer 1 to 2 facts per evidence item. Merge obvious duplicates by using the same normalized_key.
- Keep facts atomic: one subject, one predicate, one factual object.
- Split pricing evidence into separate atoms for free tier, plan price, quote-only pricing, usage-based billing, and annual discount when those signals are present.
- Skip vague, low-quality, or unsupported evidence.

Scoped accepted evidence:
{evidence_json}
"""

    def _llm_spec_from_env(self) -> str | None:
        return (
            os.getenv("RIVALENS_KNOWLEDGE_STRUCTURING_LLM")
            or os.getenv("KNOWLEDGE_STRUCTURING_LLM")
        )

    def _evidence_analysis_dimension_id(self, evidence: dict[str, Any]) -> str:
        return str(
            evidence.get("analysis_dimension_id")
            or evidence.get("dimension_id")
            or ""
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
        fact_extractor: KnowledgeFactLLMExtractor | None = None,
        snippet_builder: EvidenceSnippetBuilder | None = None,
    ) -> None:
        self.fact_extractor = fact_extractor or KnowledgeFactLLMExtractor()
        self.snippet_builder = snippet_builder or EvidenceSnippetBuilder()

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

        knowledge_facts, fact_extraction = await self._build_knowledge_facts_with_llm(
            evidence_items,
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
                        "evidence_snippet_enriched_count": snippet_stats.get(
                            "evidence_snippet_enriched_count",
                            0,
                        ),
                        "evidence_snippet_count": snippet_stats.get(
                            "evidence_snippet_count",
                            0,
                        ),
                        "knowledge_fact_source": fact_extraction.get("source", ""),
                        "llm_configured": bool(fact_extraction.get("llm_configured")),
                        "llm_prompt": fact_extraction.get("llm_prompt", ""),
                        "llm_provider": fact_extraction.get("llm_provider", ""),
                        "llm_model": fact_extraction.get("llm_model", ""),
                        "llm_input_evidence_count": fact_extraction.get(
                            "llm_input_evidence_count",
                            0,
                        ),
                        "llm_batch_count": fact_extraction.get("llm_batch_count", 0),
                        "llm_failed_batch_count": fact_extraction.get(
                            "llm_failed_batch_count",
                            0,
                        ),
                        "llm_scope": fact_extraction.get("llm_scope", ""),
                        "llm_max_tokens": fact_extraction.get("llm_max_tokens", 0),
                        "llm_max_evidence_items": fact_extraction.get(
                            "llm_max_evidence_items",
                            0,
                        ),
                        "llm_max_excerpt_chars": fact_extraction.get(
                            "llm_max_excerpt_chars",
                            0,
                        ),
                        "llm_fact_count": fact_extraction.get("llm_fact_count", 0),
                        "llm_fallback_reason": fact_extraction.get("fallback_reason", ""),
                        "llm_cost": fact_extraction.get("llm_cost", 0.0),
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

    async def _build_knowledge_facts_with_llm(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, Any]]:
        llm_configured = bool(
            self.fact_extractor
            and getattr(self.fact_extractor, "is_configured", lambda: False)()
        )
        metadata: dict[str, Any] = {
            "source": "rule_fallback",
            "llm_configured": llm_configured,
            "llm_fact_count": 0,
            "llm_cost": 0.0,
            "fallback_reason": "",
        }
        if llm_configured:
            try:
                extraction_result = await self.fact_extractor.extract(evidence_items)
                if isinstance(extraction_result, tuple):
                    llm_facts, llm_metadata = extraction_result
                else:
                    llm_facts = extraction_result
                    llm_metadata = {}
                metadata.update(llm_metadata or {})
                metadata["llm_fact_count"] = len(llm_facts)
                normalized, atomization_stats = self._normalize_llm_facts_with_stats(
                    llm_facts,
                    evidence_items,
                )
                metadata.update(atomization_stats)
                if normalized:
                    metadata["source"] = "llm"
                    metadata["knowledge_fact_count"] = len(normalized)
                    return normalized, metadata
                metadata["fallback_reason"] = "llm_returned_no_valid_facts"
            except Exception as exc:
                metadata["fallback_reason"] = f"llm_error:{type(exc).__name__}"

        fallback_facts, atomization_stats = self._build_knowledge_facts_with_stats(
            evidence_items,
        )
        metadata.update(atomization_stats)
        metadata["knowledge_fact_count"] = len(fallback_facts)
        return fallback_facts, metadata

    def _normalize_llm_facts(
        self,
        llm_facts: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> list[KnowledgeFact]:
        facts, _stats = self._normalize_llm_facts_with_stats(llm_facts, evidence_items)
        return facts

    def _normalize_llm_facts_with_stats(
        self,
        llm_facts: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, int]]:
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }
        stats = self._empty_atomization_stats()
        facts_by_key: dict[str, KnowledgeFact] = {}
        seen_pricing_atoms: set[tuple[str, str]] = set()

        def add_fact(fact: KnowledgeFact) -> bool:
            key = fact.get("normalized_key", "")
            if not key:
                return False
            self._mark_seen_pricing_atoms(fact, seen_pricing_atoms)
            if key in facts_by_key:
                facts_by_key[key] = self._merge_fact(facts_by_key[key], fact)
                return False
            facts_by_key[key] = fact
            return True

        for raw_fact in llm_facts:
            fact = self._normalize_llm_fact(raw_fact, evidence_by_id)
            if not fact:
                continue
            replacements, finding = self._atomize_normalized_fact(
                fact,
                evidence_by_id,
            )
            self._add_atomization_finding(stats, finding)
            if finding.get("status") == "too_broad" and not replacements:
                stats["atomization_rejected_count"] += 1
                continue
            if replacements:
                stats["atomization_split_count"] += sum(
                    1 for replacement in replacements if add_fact(replacement)
                )
                continue
            add_fact(fact)

        for evidence in evidence_items:
            for pricing_fact in self._pricing_fact_candidates_from_evidence(evidence):
                pricing_atom_key = self._pricing_atom_seen_key(pricing_fact)
                if pricing_atom_key in seen_pricing_atoms:
                    continue
                if add_fact(pricing_fact):
                    stats["atomization_split_count"] += 1

        facts = list(facts_by_key.values())
        for index, fact in enumerate(facts, start=1):
            fact["id"] = f"fact_{index}"
        return facts, stats

    def _normalize_llm_fact(
        self,
        raw_fact: dict[str, Any],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> KnowledgeFact | None:
        evidence_ids = [
            evidence_id
            for evidence_id in raw_fact.get("evidence_ids", [])
            if evidence_id in evidence_by_id
        ]
        if not evidence_ids:
            return None
        primary_evidence = evidence_by_id[evidence_ids[0]]
        primary_dimension_id = self._evidence_analysis_dimension_id(primary_evidence)
        primary_report_section_id = str(primary_evidence.get("report_section_id", "") or "")
        primary_competitor = str(primary_evidence.get("competitor", "") or "")
        evidence_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if self._same_evidence_scope(
                primary_evidence,
                evidence_by_id[evidence_id],
            )
        ]
        if not evidence_ids:
            return None
        competitor = (
            primary_competitor
            or clean_text(raw_fact.get("competitor", ""))
        )
        analysis_dimension_id = primary_dimension_id
        if not analysis_dimension_id or analysis_dimension_id == "competitor_profile":
            return None

        fact_type = str(raw_fact.get("fact_type", "") or "").strip()
        if fact_type not in FACT_TYPES:
            fact_type = self._fact_type_for_evidence(
                primary_evidence,
                analysis_dimension_id,
                self._evidence_text(primary_evidence),
            )
        predicate = clean_text(raw_fact.get("predicate", "")) or self._predicate_for_fact_type(fact_type)
        subject = clean_text(raw_fact.get("subject", "")) or self._fact_subject(primary_evidence)
        fact_object = clean_text(raw_fact.get("object", ""))
        if not fact_object:
            fact_object = self._fact_object(
                primary_evidence,
                self._evidence_text(primary_evidence),
            )
        if not fact_object or is_low_quality_text(fact_object):
            return None

        statement = clean_text(raw_fact.get("statement", ""))
        if not statement:
            statement = self._fact_statement(subject, predicate, fact_object)
        if is_low_quality_text(statement):
            return None

        schema_field_ids = list(primary_evidence.get("schema_field_ids", []) or [])
        schema_field_id = (
            schema_field_ids[0]
            if schema_field_ids
            else clean_text(raw_fact.get("schema_field_id", ""))
        )
        normalized_key = self._fact_normalized_key(
            competitor=str(competitor),
            dimension=analysis_dimension_id,
            fact_type=fact_type,
            predicate=predicate,
            fact_object=fact_object,
        )
        confidence = self._bounded_confidence(raw_fact.get("confidence", primary_evidence.get("confidence", 0.5)))
        qualifiers = dict(raw_fact.get("qualifiers", {}) or {})
        qualifiers.setdefault("source_type", primary_evidence.get("source_type", ""))
        qualifiers.setdefault("title", primary_evidence.get("title", ""))
        qualifiers.setdefault("url", primary_evidence.get("url", ""))
        qualifiers.setdefault("dimension_name", primary_evidence.get("dimension_name", ""))
        if fact_type == "pricing_signal":
            pricing_atom_kind = self._pricing_atom_kind_from_parts(
                predicate=predicate,
                subject=subject,
                fact_object=fact_object,
                statement=statement,
            )
            if pricing_atom_kind:
                qualifiers.setdefault("pricing_atom_kind", pricing_atom_kind)
        return {
            "id": "",
            "competitor": competitor,
            "analysis_dimension_id": analysis_dimension_id,
            "schema_field_id": schema_field_id,
            "fact_type": fact_type,
            "subject": subject,
            "predicate": predicate,
            "object": fact_object[:240],
            "qualifiers": qualifiers,
            "normalized_key": normalized_key,
            "statement": statement[:500],
            "value": {
                **dict(raw_fact.get("value", {}) or {}),
                "object": fact_object[:240],
            },
            "evidence_ids": evidence_ids,
            "report_section_id": primary_report_section_id,
            "confidence": confidence,
        }

    def _same_evidence_scope(
        self,
        primary_evidence: dict[str, Any],
        candidate_evidence: dict[str, Any],
    ) -> bool:
        return (
            str(primary_evidence.get("competitor", "") or "")
            == str(candidate_evidence.get("competitor", "") or "")
            and self._evidence_analysis_dimension_id(primary_evidence)
            == self._evidence_analysis_dimension_id(candidate_evidence)
            and str(primary_evidence.get("report_section_id", "") or "")
            == str(candidate_evidence.get("report_section_id", "") or "")
        )

    def _build_knowledge_facts(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> list[KnowledgeFact]:
        facts, _stats = self._build_knowledge_facts_with_stats(evidence_items)
        return facts

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

    def _bounded_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.5
        return round(max(0.0, min(1.0, confidence)), 2)

    def _empty_atomization_stats(self) -> dict[str, int]:
        return {
            "atomization_too_broad_count": 0,
            "atomization_split_count": 0,
            "atomization_rejected_count": 0,
        }

    def _add_atomization_finding(
        self,
        stats: dict[str, int],
        finding: dict[str, Any],
    ) -> None:
        if finding.get("status") == "too_broad":
            stats["atomization_too_broad_count"] += 1

    def _mark_seen_pricing_atoms(
        self,
        fact: KnowledgeFact,
        seen_pricing_atoms: set[tuple[str, str]],
    ) -> None:
        atom_kind = self._pricing_atom_kind_for_fact(fact)
        if not atom_kind:
            return
        for evidence_id in fact.get("evidence_ids", []) or []:
            if evidence_id:
                seen_pricing_atoms.add((evidence_id, atom_kind))

    def _pricing_atom_seen_key(self, fact: KnowledgeFact) -> tuple[str, str] | None:
        atom_kind = self._pricing_atom_kind_for_fact(fact)
        evidence_ids = list(fact.get("evidence_ids", []) or [])
        evidence_id = evidence_ids[0] if evidence_ids else ""
        if not atom_kind or not evidence_id:
            return None
        return (evidence_id, atom_kind)

    def _pricing_atom_kind_for_fact(self, fact: KnowledgeFact) -> str:
        qualifiers = fact.get("qualifiers", {}) or {}
        atom_kind = str(qualifiers.get("pricing_atom_kind", "") or "")
        if atom_kind in PRICING_ATOM_PREDICATES:
            return atom_kind
        return self._pricing_atom_kind_from_parts(
            predicate=str(fact.get("predicate", "") or ""),
            subject=str(fact.get("subject", "") or ""),
            fact_object=str(fact.get("object", "") or ""),
            statement=str(fact.get("statement", "") or ""),
        )

    def _pricing_atom_kind_from_parts(
        self,
        predicate: str,
        subject: str,
        fact_object: str,
        statement: str,
    ) -> str:
        atom_kind = PRICING_PREDICATE_ATOM_KINDS.get(predicate)
        if atom_kind:
            return atom_kind
        combined = " ".join([subject, fact_object, statement])
        if self._text_has_broad_pricing_phrase(combined):
            return ""
        detected = self._detected_pricing_atom_kinds(combined)
        return detected[0] if len(detected) == 1 else ""

    def _atomize_normalized_fact(
        self,
        fact: KnowledgeFact,
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> tuple[list[KnowledgeFact], dict[str, Any]]:
        finding = self._atomization_finding(fact, evidence_by_id)
        if finding.get("recommended_action") != "split":
            return [], finding

        replacements: list[KnowledgeFact] = []
        for evidence_id in fact.get("evidence_ids", []):
            evidence = evidence_by_id.get(evidence_id, {})
            replacements.extend(self._pricing_fact_candidates_from_evidence(evidence))
        return replacements, finding

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

    def _text_has_broad_pricing_phrase(self, text: str) -> bool:
        normalized = text.lower()
        return any(
            phrase in normalized
            for phrase in [
                "multiple pricing signals",
                "various pricing signals",
                "pricing signals across",
                "pricing details across",
                "多个定价信号",
                "多种定价",
            ]
        )

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
        if not analysis_dimension_id or analysis_dimension_id == "competitor_profile":
            return [], {"status": "skipped"}

        text = self._evidence_text(evidence)
        if not text or is_low_quality_text(text):
            return [], {"status": "skipped"}

        evidence_id = evidence.get("id", "")
        schema_field_ids = list(evidence.get("schema_field_ids", []) or [])
        fact_type = self._fact_type_for_evidence(evidence, analysis_dimension_id, text)
        if fact_type == "pricing_signal":
            pricing_facts = self._pricing_fact_candidates_from_evidence(evidence)
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
        fact_object = self._fact_object(evidence, text)
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
            return [], finding
        return [generic_fact], {"status": "atomic"}

    def _pricing_fact_candidates_from_evidence(
        self,
        evidence: dict[str, Any],
    ) -> list[KnowledgeFact]:
        analysis_dimension_id = self._evidence_analysis_dimension_id(evidence)
        text = self._evidence_text(evidence)
        if not analysis_dimension_id or not text:
            return []
        kinds = self._detected_pricing_atom_kinds(text)
        facts = [
            self._pricing_fact_for_kind(evidence, kind, text)
            for kind in kinds
        ]
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
        ) or any(term in text for term in ["企业版询价", "联系销售", "定制报价"]):
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
    ) -> KnowledgeFact | None:
        predicate = PRICING_ATOM_PREDICATES.get(kind, "publishes")
        subject = self._pricing_subject(kind, text)
        fact_object = self._pricing_object(kind, text)
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
        patterns = [
            r"\b(?P<plan>[A-Z][A-Za-z0-9+ -]{1,40})\s+(?:plan\s+)?(?:is|starts at|from|costs|priced at)\s+(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/\s*(?:user|seat|month|mo|year|yr))*)",
            r"\b(?P<plan>[A-Z][A-Za-z0-9+ -]{1,40})\s+(?:plan\s+)?(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/\s*(?:user|seat|month|mo|year|yr))*)",
            r"(?P<plan>[A-Za-z0-9+ -]{1,40})\s*版[^。；;,.]{0,30}(?P<price>[¥$]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:月|年|人|用户))?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return {
                    "plan": " ".join(match.group("plan").split()),
                    "price": " ".join(match.group("price").split()),
                }
        return {}

    def _pricing_subject(self, kind: str, text: str) -> str:
        if kind == "free_tier":
            return "Free plan"
        if kind == "published_plan_price":
            price = self._published_plan_price(text)
            plan = price.get("plan", "").strip()
            return f"{plan} plan" if plan else "Paid plan"
        if kind == "quote_only":
            return "Enterprise plan"
        if kind == "usage_based_billing":
            return "Usage-based billing"
        if kind == "annual_discount":
            return "Annual billing"
        return ""

    def _pricing_object(self, kind: str, text: str) -> str:
        if kind == "free_tier":
            return "free tier available"
        if kind == "published_plan_price":
            price = self._published_plan_price(text)
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
        title = clean_text(evidence.get("title", ""))
        if title and not is_low_quality_text(title):
            return f"{competitor} source: {title[:120]}"
        dimension_name = evidence.get("dimension_name") or evidence.get("analysis_dimension_id", "")
        return f"{competitor} {dimension_name}".strip()

    def _fact_object(self, evidence: dict[str, Any], text: str) -> str:
        title = clean_text(evidence.get("title", ""))
        if title and title.lower() not in text.lower() and not is_low_quality_text(title):
            combined = f"{title}: {text}"
        else:
            combined = text
        return " ".join(combined.split())[:240]

    def _fact_statement(self, subject: str, predicate: str, fact_object: str) -> str:
        return f"{subject} {predicate} {fact_object}".strip()[:500]

    def _fact_normalized_key(
        self,
        competitor: str,
        dimension: str,
        fact_type: str,
        predicate: str,
        fact_object: str,
    ) -> str:
        object_signature = "_".join(self._key_terms(fact_object)[:8]) or "signal"
        parts = [
            self._slug(competitor or "unknown"),
            self._slug(dimension or "unknown"),
            self._slug(fact_type or "signal"),
            self._slug(predicate or "indicates"),
            object_signature,
        ]
        return "|".join(parts)

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
        return str(evidence.get("analysis_dimension_id") or "")

    def _average_confidence(self, items: list[dict[str, Any]]) -> float:
        confidences = [float(item.get("confidence", 0.5)) for item in items]
        if not confidences:
            return 0.5
        return round(sum(confidences) / len(confidences), 2)

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
