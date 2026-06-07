"""Analysis agent that turns evidence into traceable claims."""

import asyncio
from collections import defaultdict
import json
import os
import re
from typing import Any

import json_repair

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.report_routing import primary_report_section_id
from rivalens.research.utils.llm import create_chat_completion
from rivalens.schema import AnalysisClaim, CompetitorAnalysisState, KnowledgeFactPackage
from rivalens.text_quality import clean_text, is_low_quality_text


class AnalysisClaimLLMWriter:
    """Organize claim candidates from structured facts without changing trace IDs."""

    prompt_id = "analysis_claim_organizer_v1"
    wording_prompt_id = "analysis_claim_writer_v1"

    def __init__(
        self,
        llm_spec: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        max_fact_chars: int | None = None,
    ) -> None:
        self.llm_spec = llm_spec or self._llm_spec_from_env()
        self.temperature = temperature
        self.max_tokens = max_tokens or self._env_int(
            "RIVALENS_ANALYSIS_LLM_MAX_TOKENS",
            900,
            minimum=300,
        )
        self.max_fact_chars = max_fact_chars or self._env_int(
            "RIVALENS_ANALYSIS_LLM_FACT_CHARS",
            520,
            minimum=160,
        )
        self.max_package_facts = self._env_int(
            "RIVALENS_ANALYSIS_LLM_FACTS_PER_PACKAGE",
            18,
            minimum=4,
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

    async def organize_claims(
        self,
        *,
        facts: list[dict[str, Any]],
        dimension: dict[str, Any],
        competitor: str,
        rule_claims: list[AnalysisClaim],
    ) -> dict[str, Any]:
        provider = self.provider
        model = self.model
        if not provider or not model:
            raise ValueError("Analysis LLM is not configured.")

        llm_cost = 0.0

        def add_cost(cost: float) -> None:
            nonlocal llm_cost
            llm_cost += float(cost)

        prompt = self._organization_prompt(
            facts=facts,
            dimension=dimension,
            competitor=competitor,
            rule_claims=rule_claims,
        )
        response = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            cost_callback=add_cost,
            rivalens_operation="analysis_claim_organization",
            rivalens_trace_context={
                "competitor": competitor,
                "dimension_id": dimension.get("id", ""),
                "dimension_name": dimension.get("name", ""),
                "fact_count": len(facts),
                "rule_claim_count": len(rule_claims),
            },
            rivalens_evidence_count=len(
                {
                    evidence_id
                    for fact in facts
                    for evidence_id in fact.get("evidence_ids", [])
                    if evidence_id
                }
            ),
        )
        parsed = json_repair.loads(response)
        if not isinstance(parsed, dict):
            raise ValueError("Analysis claim organizer response must be a JSON object.")
        claims = parsed.get("claims", [])
        if not isinstance(claims, list):
            raise ValueError("Analysis claim organizer response must include claims list.")
        return {
            "claims": claims[:8],
            "metadata": {
                "llm_prompt_id": self.prompt_id,
                "llm_prompt_chars": len(prompt),
                "llm_provider": provider,
                "llm_model": model,
                "llm_cost": round(llm_cost, 6),
                "llm_raw_response_chars": len(response),
            },
        }

    async def write_claim(
        self,
        *,
        base_claim: AnalysisClaim,
        facts: list[dict[str, Any]],
        dimension: dict[str, Any],
    ) -> dict[str, Any]:
        provider = self.provider
        model = self.model
        if not provider or not model:
            raise ValueError("Analysis LLM is not configured.")

        llm_cost = 0.0

        def add_cost(cost: float) -> None:
            nonlocal llm_cost
            llm_cost += float(cost)

        prompt = self._prompt(
            base_claim=base_claim,
            facts=facts,
            dimension=dimension,
        )
        response = await create_chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            cost_callback=add_cost,
            rivalens_operation="analysis_claim_generation",
            rivalens_trace_context={
                "id": base_claim.get("id", ""),
                "competitor": (base_claim.get("competitors") or [""])[0],
                "dimension_id": base_claim.get("analysis_dimension_id", ""),
                "dimension_name": dimension.get("name", ""),
            },
            rivalens_evidence_count=len(base_claim.get("evidence_ids", []) or []),
        )
        parsed = json_repair.loads(response)
        if not isinstance(parsed, dict):
            raise ValueError("Analysis claim LLM response must be a JSON object.")
        claim = clean_text(parsed.get("claim", ""))
        if not claim or is_low_quality_text(claim):
            raise ValueError("Analysis claim LLM returned an empty or low-quality claim.")
        confidence = self._bounded_confidence(parsed.get("confidence", 0.6))
        reasoning = clean_text(parsed.get("reasoning", ""))
        return {
            "claim": claim[:700],
            "confidence": confidence,
            "reasoning": reasoning[:360],
            "metadata": {
                "llm_prompt_id": self.wording_prompt_id,
                "llm_prompt_chars": len(prompt),
                "llm_provider": provider,
                "llm_model": model,
                "llm_cost": round(llm_cost, 6),
                "llm_raw_response_chars": len(response),
            },
        }

    def _organization_prompt(
        self,
        *,
        facts: list[dict[str, Any]],
        dimension: dict[str, Any],
        competitor: str,
        rule_claims: list[AnalysisClaim],
    ) -> str:
        fact_payload = []
        for fact in facts[: self.max_package_facts]:
            fact_payload.append(
                {
                    "id": fact.get("id", ""),
                    "fact_type": fact.get("fact_type", ""),
                    "subject": clean_text(fact.get("subject", ""))[:160],
                    "predicate": fact.get("predicate", ""),
                    "object": clean_text(fact.get("object", ""))[: self.max_fact_chars],
                    "statement": clean_text(fact.get("statement", ""))[: self.max_fact_chars],
                    "confidence": fact.get("confidence", 0.5),
                }
            )
        rule_payload = [
            {
                "claim": clean_text(claim.get("claim", ""))[:420],
                "knowledge_fact_ids": list(claim.get("knowledge_fact_ids", []) or []),
                "claim_type": claim.get("claim_type", ""),
            }
            for claim in rule_claims[:8]
        ]
        payload = {
            "competitor": competitor,
            "analysis_dimension_id": dimension.get("id", ""),
            "dimension_name": dimension.get("name") or dimension.get("id", ""),
            "facts": fact_payload,
            "rule_claim_hints": rule_payload,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        return f"""Return strict JSON only.

Organize the structured KnowledgeFact records into concise competitor-analysis claim candidates.

Required JSON shape:
{{"claims": [{{"claim": "one claim sentence", "knowledge_fact_ids": ["fact_id"], "confidence": 0.0, "reasoning": "short why these facts belong together"}}]}}

Rules:
- Use only the KnowledgeFact IDs shown in facts. Every claim must cite one or more knowledge_fact_ids.
- Do not include evidence_ids; the system will map evidence locally from KnowledgeFact records.
- Prefer merging facts that support the same analytical point; split facts when they describe separate prices, capabilities, risks, segments, or evidence themes.
- Skip background facts that do not support a useful analysis claim.
- Do not infer leadership, superiority, market share, price comparisons, or causality unless explicitly present.
- Preserve concrete names, modules, prices, counts, dates, certifications, quotas, and scenarios when present.
- Keep each claim under 110 Chinese characters or 70 English words when possible.
- If facts are broad, write cautious descriptive claims rather than strategic conclusions.

Input:
{payload_json}
"""

    def _prompt(
        self,
        *,
        base_claim: AnalysisClaim,
        facts: list[dict[str, Any]],
        dimension: dict[str, Any],
    ) -> str:
        fact_payload = []
        for fact in facts[:6]:
            fact_payload.append(
                {
                    "id": fact.get("id", ""),
                    "fact_type": fact.get("fact_type", ""),
                    "subject": clean_text(fact.get("subject", ""))[:160],
                    "predicate": fact.get("predicate", ""),
                    "object": clean_text(fact.get("object", ""))[: self.max_fact_chars],
                    "statement": clean_text(fact.get("statement", ""))[: self.max_fact_chars],
                    "evidence_ids": list(fact.get("evidence_ids", []) or []),
                }
            )
        payload = {
            "competitors": base_claim.get("competitors", []),
            "analysis_dimension_id": base_claim.get("analysis_dimension_id", ""),
            "dimension_name": dimension.get("name") or dimension.get("id", ""),
            "claim_type": base_claim.get("claim_type", ""),
            "risk_level": base_claim.get("claim_risk_level", ""),
            "rule_claim": base_claim.get("claim", ""),
            "facts": fact_payload,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        return f"""Return strict JSON only.

Write one concise, evidence-bound competitor-analysis claim from the structured facts.

Required JSON shape:
{{"claim": "one claim sentence", "confidence": 0.0, "reasoning": "short why this wording is supported"}}

Rules:
- Use only the facts shown below. Do not infer leadership, superiority, market share, price comparisons, or causality unless explicitly present.
- Preserve concrete names, modules, prices, counts, dates, certifications, quotas, and scenarios when present.
- Do not mention uncited sources, unavailable competitors, or evidence IDs in the claim text.
- Keep claim under 90 Chinese characters or 55 English words when possible.
- If facts are broad, write a cautious descriptive claim rather than a strategic conclusion.

Input:
{payload_json}
"""

    def _llm_spec_from_env(self) -> str | None:
        return os.getenv("RIVALENS_ANALYSIS_LLM") or os.getenv("ANALYSIS_LLM")

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
        except ValueError:
            return default
        return max(minimum, parsed)

    def _bounded_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.6
        return round(max(0.0, min(1.0, confidence)), 2)


class AnalysisAgent:
    def __init__(
        self,
        claim_writer: AnalysisClaimLLMWriter | None = None,
        max_concurrent_llm_claims: int | None = None,
    ) -> None:
        self.claim_writer = claim_writer or AnalysisClaimLLMWriter()
        self.max_concurrent_llm_claims = self._env_int(
            max_concurrent_llm_claims,
            "RIVALENS_ANALYSIS_LLM_CONCURRENCY",
            4,
            minimum=1,
        )

    def _env_int(
        self,
        value: int | None,
        env_name: str,
        default: int,
        minimum: int = 0,
    ) -> int:
        raw_value = value if value is not None else os.getenv(env_name)
        if raw_value in (None, ""):
            return default
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed)

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        evidence_message = latest_message_for(
            state,
            receiver="analysis",
            message_type="evidence",
            sender="collection",
        )
        knowledge_message = latest_message_for(
            state,
            receiver="analysis",
            message_type="schema",
            sender="knowledge_structuring",
        )
        schema_payload = knowledge_message.get("payload", {}) if knowledge_message else {}
        competitor_knowledge = state.get("competitor_knowledge") or schema_payload.get("competitor_knowledge", [])
        knowledge_facts = state.get("knowledge_facts") or schema_payload.get("knowledge_facts", [])
        knowledge_fact_packages = (
            state.get("knowledge_fact_packages")
            or schema_payload.get("knowledge_fact_packages", [])
        )
        previous_claims = state.get("analysis_claims", [])
        claim_support_reviews = state.get("claim_support_reviews", [])
        claim_generation: dict[str, Any] = {"source": "none"}
        claims = self._revised_claims_from_support_reviews(
            previous_claims,
            claim_support_reviews,
        )
        claim_source = "claim_support_revision" if claims else "knowledge_facts"

        if not claims:
            claims, claim_generation = await self._claims_from_knowledge_facts_with_metadata(
                state,
                knowledge_facts,
                knowledge_fact_packages,
            )
            claim_source = "knowledge_facts" if claims else "accepted_evidence_reviews"

        if not claims:
            claims = self._claims_from_quality_accepted_evidence(state)

        if not claims:
            claim_source = "competitor_knowledge"
            for knowledge in competitor_knowledge:
                self._append_feature_claims(claims, knowledge)
                self._append_pricing_claims(claims, knowledge)
                self._append_persona_claims(claims, knowledge)

        message = create_agent_message(
            sender="analysis",
            receiver="claim_support",
            message_type="analysis",
            payload={"claim_count": len(claims), "claims": claims},
            evidence_ids=[evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", [])],
        )

        return {
            "analysis_claims": claims,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "analysis",
                    "action": "derive_traceable_claims",
                    "input": {
                        "source": claim_source,
                        "evidence_message_id": evidence_message.get("id") if evidence_message else None,
                        "knowledge_count": len(competitor_knowledge),
                        "knowledge_fact_count": len(knowledge_facts),
                        "knowledge_fact_package_count": len(knowledge_fact_packages),
                        "message_id": knowledge_message.get("id") if knowledge_message else None,
                        "evidence_review_count": len(state.get("evidence_reviews", [])),
                    },
                    "output": {
                        "claim_count": len(claims),
                        "claim_granularity": (
                            "claim_support_revision"
                            if claim_source == "claim_support_revision"
                            else (
                                "knowledge_fact"
                                if claim_source == "knowledge_facts"
                                else (
                                    "accepted_evidence_cluster"
                                    if claim_source == "accepted_evidence_reviews"
                                    else "competitor_knowledge"
                                )
                            )
                        ),
                        "analysis_llm_configured": claim_generation.get(
                            "llm_configured",
                            False,
                        ),
                        "analysis_llm_provider": claim_generation.get("llm_provider", ""),
                        "analysis_llm_model": claim_generation.get("llm_model", ""),
                        "analysis_llm_mode": claim_generation.get("llm_mode", ""),
                        "analysis_llm_concurrency": claim_generation.get(
                            "llm_concurrency",
                            0,
                        ),
                        "analysis_llm_group_count": claim_generation.get(
                            "llm_group_count",
                            0,
                        ),
                        "analysis_llm_fact_group_count": claim_generation.get(
                            "llm_fact_group_count",
                            0,
                        ),
                        "knowledge_fact_package_source": claim_generation.get(
                            "knowledge_fact_package_source",
                            "",
                        ),
                        "analysis_llm_success_count": claim_generation.get(
                            "llm_success_count",
                            0,
                        ),
                        "analysis_llm_failed_count": claim_generation.get(
                            "llm_failed_count",
                            0,
                        ),
                        "analysis_llm_fallback_count": claim_generation.get(
                            "llm_fallback_count",
                            0,
                        ),
                        "analysis_llm_generated_claim_count": claim_generation.get(
                            "llm_generated_claim_count",
                            0,
                        ),
                        "analysis_llm_invalid_fact_id_count": claim_generation.get(
                            "llm_invalid_fact_id_count",
                            0,
                        ),
                        "analysis_llm_cost": claim_generation.get("llm_cost", 0.0),
                        "analysis_llm_prompt_chars": claim_generation.get(
                            "llm_prompt_chars",
                            0,
                        ),
                    },
                }
            ],
        }

    async def _claims_from_knowledge_facts_with_metadata(
        self,
        state: CompetitorAnalysisState,
        knowledge_facts: list[dict[str, Any]],
        knowledge_fact_packages: list[KnowledgeFactPackage] | None = None,
    ) -> tuple[list[AnalysisClaim], dict[str, Any]]:
        dimensions_by_id = self._analysis_dimension_lookup(state)
        groups = list(self._group_knowledge_facts(knowledge_facts).values())
        packages = self._knowledge_fact_packages_with_facts(
            knowledge_facts,
            knowledge_fact_packages or [],
        )
        writer_configured = bool(
            self.claim_writer and self.claim_writer.is_configured()
        )
        organizer_configured = bool(
            writer_configured and hasattr(self.claim_writer, "organize_claims")
        )
        metadata: dict[str, Any] = {
            "source": "knowledge_facts",
            "llm_configured": writer_configured,
            "llm_mode": "dimension_claim_organizer"
            if organizer_configured
            else ("claim_wording" if writer_configured else "rules"),
            "llm_provider": getattr(self.claim_writer, "provider", None) or "",
            "llm_model": getattr(self.claim_writer, "model", None) or "",
            "llm_concurrency": self.max_concurrent_llm_claims if writer_configured else 0,
            "llm_group_count": len(packages) if organizer_configured else len(groups),
            "llm_fact_group_count": len(groups),
            "knowledge_fact_package_source": "knowledge_structuring"
            if knowledge_fact_packages
            else "analysis_fallback",
            "llm_success_count": 0,
            "llm_failed_count": 0,
            "llm_fallback_count": 0,
            "llm_generated_claim_count": 0,
            "llm_invalid_fact_id_count": 0,
            "llm_cost": 0.0,
            "llm_prompt_chars": 0,
        }
        if not groups:
            return [], metadata

        if not writer_configured:
            return self._rule_claims_for_fact_groups(groups, dimensions_by_id), metadata

        semaphore = asyncio.Semaphore(self.max_concurrent_llm_claims)
        if not organizer_configured:
            results = await asyncio.gather(
                *[
                    self._claim_from_fact_group_with_llm(
                        semaphore,
                        group,
                        dimensions_by_id,
                        claim_id=f"claim_{index}",
                    )
                    for index, group in enumerate(groups, start=1)
                ]
            )
            claims: list[AnalysisClaim] = []
            for claim, item_metadata in results:
                if claim:
                    claims.append(claim)
                self._add_llm_item_metadata(metadata, item_metadata)
            metadata["llm_cost"] = round(metadata["llm_cost"], 6)
            metadata["llm_generated_claim_count"] = len(claims)
            return claims, metadata

        results = await asyncio.gather(
            *[
                self._claims_from_fact_package_with_llm(
                    semaphore,
                    package["facts"],
                    package["package"],
                    dimensions_by_id,
                )
                for package in packages
            ]
        )
        claims: list[AnalysisClaim] = []
        for package_claims, item_metadata in results:
            claims.extend(package_claims)
            self._add_llm_item_metadata(metadata, item_metadata)
        metadata["llm_cost"] = round(metadata["llm_cost"], 6)
        metadata["llm_generated_claim_count"] = len(
            [
                claim
                for claim in claims
                if claim.get("claim_source") == "knowledge_fact_dimension_llm"
            ]
        )
        return self._renumber_claims(claims), metadata

    async def _claims_from_fact_package_with_llm(
        self,
        semaphore: asyncio.Semaphore,
        facts: list[dict[str, Any]],
        package: dict[str, Any],
        dimensions_by_id: dict[str, dict[str, Any]],
    ) -> tuple[list[AnalysisClaim], dict[str, Any]]:
        if not facts:
            return [], {}
        rule_claims = self._rule_claims_for_fact_groups(
            list(self._group_knowledge_facts(facts).values()),
            dimensions_by_id,
        )
        if not rule_claims:
            return [], {}

        seed = facts[0]
        competitor = str(
            package.get("competitor")
            or seed.get("competitor", "")
            or "the target competitor"
        )
        analysis_dimension_id = str(
            package.get("analysis_dimension_id")
            or seed.get("analysis_dimension_id", "")
        )
        dimension = dimensions_by_id.get(
            analysis_dimension_id,
            {"id": analysis_dimension_id},
        )
        async with semaphore:
            try:
                result = await self.claim_writer.organize_claims(
                    facts=facts,
                    dimension=dimension,
                    competitor=competitor,
                    rule_claims=rule_claims,
                )
            except Exception as exc:
                return self._fallback_claims_with_llm_reason(rule_claims, exc), {
                    "llm_failed": True,
                    "llm_fallback": True,
                }

        claims, validation_metadata = self._claims_from_llm_organized_candidates(
            result.get("claims", []),
            facts,
            dimensions_by_id,
        )
        if validation_metadata.get("llm_invalid_fact_id_count", 0):
            claims = []
        metadata = {
            "llm_success": bool(claims),
            "llm_failed": not bool(claims),
            "llm_fallback": not bool(claims),
            "llm_cost": float((result.get("metadata", {}) or {}).get("llm_cost", 0.0)),
            "llm_prompt_chars": int(
                (result.get("metadata", {}) or {}).get("llm_prompt_chars", 0),
            ),
            **validation_metadata,
        }
        if claims:
            return claims, metadata
        return self._fallback_claims_with_llm_reason(
            rule_claims,
            ValueError("no valid organizer claims"),
        ), metadata

    def _claims_from_llm_organized_candidates(
        self,
        candidates: Any,
        facts: list[dict[str, Any]],
        dimensions_by_id: dict[str, dict[str, Any]],
    ) -> tuple[list[AnalysisClaim], dict[str, Any]]:
        if not isinstance(candidates, list) or not facts:
            return [], {"llm_invalid_fact_id_count": 0}

        fact_by_id = {
            fact.get("id", ""): fact
            for fact in facts
            if fact.get("id")
        }
        invalid_fact_id_count = 0
        seen_keys: set[tuple[str, tuple[str, ...]]] = set()
        claims: list[AnalysisClaim] = []
        for candidate in candidates[:8]:
            if not isinstance(candidate, dict):
                continue
            claim_text = clean_text(candidate.get("claim", ""))
            if not claim_text or is_low_quality_text(claim_text):
                continue
            raw_fact_ids = candidate.get("knowledge_fact_ids", [])
            if not isinstance(raw_fact_ids, list):
                continue
            requested_fact_ids = self._dedupe(raw_fact_ids)
            if not requested_fact_ids:
                continue
            invalid_fact_ids = [
                fact_id
                for fact_id in requested_fact_ids
                if fact_id not in fact_by_id
            ]
            invalid_fact_id_count += len(invalid_fact_ids)
            if invalid_fact_ids:
                continue

            selected_facts = [fact_by_id[fact_id] for fact_id in requested_fact_ids]
            evidence_ids = self._dedupe(
                evidence_id
                for fact in selected_facts
                for evidence_id in fact.get("evidence_ids", [])
                if evidence_id
            )
            if not evidence_ids:
                continue

            seed = selected_facts[0]
            analysis_dimension_id = str(seed.get("analysis_dimension_id", ""))
            dimension = dimensions_by_id.get(
                analysis_dimension_id,
                {"id": analysis_dimension_id},
            )
            competitor = str(seed.get("competitor", "") or "the target competitor")
            claim_type = self._claim_type_from_facts(selected_facts)
            normalized_claim = self._normalize_claim_text(claim_text)
            seen_key = (normalized_claim, tuple(requested_fact_ids))
            if seen_key in seen_keys:
                continue
            seen_keys.add(seen_key)

            report_section_id = (
                seed.get("report_section_id")
                or primary_report_section_id(dimension)
            )
            fact_key = "|".join(
                self._dedupe(
                    fact.get("normalized_key", "")
                    for fact in selected_facts
                    if fact.get("normalized_key")
                )[:4]
            )
            reasoning = clean_text(candidate.get("reasoning", ""))
            claims.append(
                {
                    "id": f"claim_{len(claims) + 1}",
                    "analysis_dimension_id": analysis_dimension_id,
                    "knowledge_fact_ids": requested_fact_ids,
                    "report_section_id": report_section_id,
                    "claim_source": "knowledge_fact_dimension_llm",
                    "claim_type": claim_type,
                    "claim_risk_level": self._claim_risk_level(
                        claim_type=claim_type,
                        analysis_dimension_id=analysis_dimension_id,
                        claim_text=claim_text,
                        fact_type=str(seed.get("fact_type", "")),
                    ),
                    "normalized_key": self._claim_normalized_key(
                        competitor,
                        analysis_dimension_id,
                        claim_type,
                        subject=claim_text[:90],
                        predicate="organized",
                        fact_key=fact_key or claim_text[:90],
                    ),
                    "branch_id": "",
                    "evidence_review_id": "",
                    "claim": claim_text[:700],
                    "competitors": [competitor] if competitor else [],
                    "evidence_ids": evidence_ids,
                    "reasoning": (
                        "LLM organized this AnalysisClaim from locally validated "
                        f"KnowledgeFact IDs; {len(requested_fact_ids)} fact(s) map to "
                        f"{len(evidence_ids)} EvidenceItem(s)."
                        + (f" LLM note: {reasoning[:360]}" if reasoning else "")
                    ),
                    "confidence": min(
                        self._average_fact_confidence(selected_facts),
                        self._bounded_confidence(candidate.get("confidence", 0.6)),
                    ),
                }
            )
        return claims, {"llm_invalid_fact_id_count": invalid_fact_id_count}

    def _fallback_claims_with_llm_reason(
        self,
        claims: list[AnalysisClaim],
        exc: Exception,
    ) -> list[AnalysisClaim]:
        return [
            {
                **claim,
                "reasoning": (
                    str(claim.get("reasoning", "")).rstrip()
                    + f" Analysis LLM organizer fallback used ({type(exc).__name__})."
                ).strip(),
            }
            for claim in claims
        ]

    def _add_llm_item_metadata(
        self,
        metadata: dict[str, Any],
        item_metadata: dict[str, Any],
    ) -> None:
        if item_metadata.get("llm_success"):
            metadata["llm_success_count"] += 1
        if item_metadata.get("llm_failed"):
            metadata["llm_failed_count"] += 1
        if item_metadata.get("llm_fallback"):
            metadata["llm_fallback_count"] += 1
        metadata["llm_invalid_fact_id_count"] += int(
            item_metadata.get("llm_invalid_fact_id_count", 0),
        )
        metadata["llm_cost"] += float(item_metadata.get("llm_cost", 0.0))
        metadata["llm_prompt_chars"] += int(
            item_metadata.get("llm_prompt_chars", 0),
        )

    def _rule_claims_for_fact_groups(
        self,
        groups: list[list[dict[str, Any]]],
        dimensions_by_id: dict[str, dict[str, Any]],
    ) -> list[AnalysisClaim]:
        claims: list[AnalysisClaim] = []
        for group in groups:
            claim = self._claim_from_fact_group(
                group,
                dimensions_by_id,
                claim_id=f"claim_{len(claims) + 1}",
            )
            if claim:
                claims.append(claim)
        return claims

    def _renumber_claims(self, claims: list[AnalysisClaim]) -> list[AnalysisClaim]:
        return [
            {**claim, "id": f"claim_{index}"}
            for index, claim in enumerate(claims, start=1)
        ]

    async def _claim_from_fact_group_with_llm(
        self,
        semaphore: asyncio.Semaphore,
        facts: list[dict[str, Any]],
        dimensions_by_id: dict[str, dict[str, Any]],
        claim_id: str,
    ) -> tuple[AnalysisClaim | None, dict[str, Any]]:
        base_claim = self._claim_from_fact_group(
            facts,
            dimensions_by_id,
            claim_id=claim_id,
        )
        if not base_claim:
            return None, {}
        analysis_dimension_id = str(base_claim.get("analysis_dimension_id", ""))
        dimension = dimensions_by_id.get(
            analysis_dimension_id,
            {"id": analysis_dimension_id},
        )
        async with semaphore:
            try:
                result = await self.claim_writer.write_claim(
                    base_claim=base_claim,
                    facts=facts,
                    dimension=dimension,
                )
            except Exception as exc:
                return {
                    **base_claim,
                    "reasoning": (
                        str(base_claim.get("reasoning", "")).rstrip()
                        + f" Analysis LLM failed; used rule fallback ({type(exc).__name__})."
                    ).strip(),
                }, {
                    "llm_failed": True,
                    "llm_fallback": True,
                }

        metadata = result.get("metadata", {}) or {}
        llm_claim = {
            **base_claim,
            "claim_source": "knowledge_fact_group_llm",
            "claim": result["claim"],
            "claim_risk_level": self._claim_risk_level(
                claim_type=str(base_claim.get("claim_type", "")),
                analysis_dimension_id=analysis_dimension_id,
                claim_text=result["claim"],
            ),
            "reasoning": (
                str(base_claim.get("reasoning", "")).rstrip()
                + " LLM drafted claim wording from bound KnowledgeFact records."
                + (
                    f" LLM note: {result.get('reasoning')}"
                    if result.get("reasoning")
                    else ""
                )
            ).strip(),
            "confidence": min(
                float(base_claim.get("confidence", 0.5)),
                float(result.get("confidence", 0.6)),
            ),
        }
        return llm_claim, {
            "llm_success": True,
            "llm_cost": float(metadata.get("llm_cost", 0.0)),
            "llm_prompt_chars": int(metadata.get("llm_prompt_chars", 0)),
        }

    def _claims_from_knowledge_facts(
        self,
        state: CompetitorAnalysisState,
        knowledge_facts: list[dict[str, Any]],
    ) -> list[AnalysisClaim]:
        dimensions_by_id = self._analysis_dimension_lookup(state)
        claims: list[AnalysisClaim] = []
        for group in self._group_knowledge_facts(knowledge_facts).values():
            claim = self._claim_from_fact_group(
                group,
                dimensions_by_id,
                claim_id=f"claim_{len(claims) + 1}",
            )
            if claim:
                claims.append(claim)
        return claims

    def _group_knowledge_facts(
        self,
        knowledge_facts: list[dict[str, Any]],
    ) -> dict[tuple[str, ...], list[dict[str, Any]]]:
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for fact in knowledge_facts:
            if not self._usable_fact(fact):
                continue
            fact_type = str(fact.get("fact_type", "") or "public_evidence_signal")
            claim_type = self._claim_type_for_fact_type(fact_type)
            key = (
                str(fact.get("competitor", "") or "the target competitor"),
                str(fact.get("analysis_dimension_id", "")),
                claim_type,
                self._normalize_key_part(
                    str(fact.get("subject", "") or self._fact_object_preview(fact)),
                ),
                self._normalize_key_part(str(fact.get("predicate", "") or "indicates")),
                str(fact.get("normalized_key", "") or ""),
            )
            grouped[key].append(fact)
        return grouped

    def _knowledge_fact_packages_with_facts(
        self,
        knowledge_facts: list[dict[str, Any]],
        knowledge_fact_packages: list[KnowledgeFactPackage],
    ) -> list[dict[str, Any]]:
        fact_by_id = {
            fact.get("id", ""): fact
            for fact in knowledge_facts
            if fact.get("id") and self._usable_fact(fact)
        }
        packages: list[dict[str, Any]] = []
        for package in knowledge_fact_packages:
            fact_ids = self._dedupe(package.get("knowledge_fact_ids", []))
            facts = [
                fact_by_id[fact_id]
                for fact_id in fact_ids
                if fact_id in fact_by_id
            ]
            if facts:
                packages.append({"package": package, "facts": facts})
        if packages:
            return packages

        fallback: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for fact in knowledge_facts:
            if not self._usable_fact(fact):
                continue
            key = (
                str(fact.get("competitor", "") or "the target competitor"),
                str(fact.get("analysis_dimension_id", "")),
            )
            fallback[key].append(fact)
        return [
            {
                "package": {
                    "id": f"analysis_fallback_package_{index}",
                    "competitor": competitor,
                    "analysis_dimension_id": analysis_dimension_id,
                    "knowledge_fact_ids": [
                        fact.get("id", "")
                        for fact in facts
                        if fact.get("id")
                    ],
                },
                "facts": facts,
            }
            for index, ((competitor, analysis_dimension_id), facts) in enumerate(
                fallback.items(),
                start=1,
            )
        ]

    def _usable_fact(self, fact: dict[str, Any]) -> bool:
        evidence_ids = [evidence_id for evidence_id in fact.get("evidence_ids", []) if evidence_id]
        if not evidence_ids:
            return False
        if not fact.get("analysis_dimension_id"):
            return False
        statement = clean_text(fact.get("statement", ""))
        return bool(statement) and not is_low_quality_text(statement)

    def _claim_from_fact_group(
        self,
        facts: list[dict[str, Any]],
        dimensions_by_id: dict[str, dict[str, Any]],
        claim_id: str,
    ) -> AnalysisClaim | None:
        if not facts:
            return None
        seed = facts[0]
        analysis_dimension_id = str(seed.get("analysis_dimension_id", ""))
        if not analysis_dimension_id:
            return None
        dimension = dimensions_by_id.get(analysis_dimension_id, {"id": analysis_dimension_id})
        dimension_name = dimension.get("name", analysis_dimension_id.replace("_", " "))
        competitor = str(seed.get("competitor", "") or "the target competitor")
        fact_type = str(seed.get("fact_type", "") or "public_evidence_signal")
        claim_type = self._claim_type_for_fact_type(fact_type)
        evidence_ids = self._dedupe(
            evidence_id
            for fact in facts
            for evidence_id in fact.get("evidence_ids", [])
            if evidence_id
        )
        if not evidence_ids:
            return None
        knowledge_fact_ids = self._dedupe(
            fact.get("id", "")
            for fact in facts
            if fact.get("id")
        )
        report_section_id = (
            seed.get("report_section_id")
            or primary_report_section_id(dimension)
        )
        fact_objects = [
            self._fact_object_preview(fact)
            for fact in facts
            if self._fact_object_preview(fact)
        ]
        claim_text = self._claim_text(
            competitor=competitor,
            dimension_name=str(dimension_name),
            fact_type=fact_type,
            subject=str(seed.get("subject", "")),
            predicate=str(seed.get("predicate", "")),
            fact_objects=fact_objects,
        )
        return {
            "id": claim_id,
            "analysis_dimension_id": analysis_dimension_id,
            "knowledge_fact_ids": knowledge_fact_ids,
            "report_section_id": report_section_id,
            "claim_source": "knowledge_fact_group",
            "claim_type": claim_type,
            "claim_risk_level": self._claim_risk_level(
                claim_type=claim_type,
                analysis_dimension_id=analysis_dimension_id,
                claim_text=claim_text,
                fact_type=fact_type,
            ),
            "normalized_key": self._claim_normalized_key(
                competitor,
                analysis_dimension_id,
                claim_type,
                subject=str(seed.get("subject", "")),
                predicate=str(seed.get("predicate", "")),
                fact_key=str(seed.get("normalized_key", "")),
            ),
            "branch_id": "",
            "evidence_review_id": "",
            "claim": claim_text,
            "competitors": [competitor] if competitor else [],
            "evidence_ids": evidence_ids,
            "reasoning": (
                "Derived by grouping structured KnowledgeFact atoms with the same "
                "competitor, analysis dimension, claim type, subject, predicate, "
                f"and normalized fact key; {len(facts)} fact(s) cite "
                f"{len(evidence_ids)} accepted EvidenceItem(s)."
            ),
            "confidence": self._average_fact_confidence(facts),
        }

    def _claim_type_for_fact_type(self, fact_type: str) -> str:
        return {
            "pricing_signal": "pricing_strategy",
            "feature_presence": "capability_signal",
            "target_user_signal": "customer_segment_signal",
            "trust_compliance_signal": "trust_compliance_signal",
            "integration_signal": "ecosystem_signal",
            "market_signal": "market_position_signal",
            "public_evidence_signal": "public_evidence_signal",
        }.get(fact_type, "public_evidence_signal")

    def _claim_type_from_facts(self, facts: list[dict[str, Any]]) -> str:
        fact_types = [
            str(fact.get("fact_type", "") or "public_evidence_signal")
            for fact in facts
        ]
        if not fact_types:
            return "public_evidence_signal"
        fact_type = max(set(fact_types), key=fact_types.count)
        return self._claim_type_for_fact_type(fact_type)

    def _claim_risk_level(
        self,
        *,
        claim_type: str,
        analysis_dimension_id: str,
        claim_text: str,
        fact_type: str = "",
    ) -> str:
        text = " ".join(
            [claim_type, analysis_dimension_id, fact_type, claim_text],
        ).lower()
        high_risk_terms = {
            "pricing",
            "price",
            "billing",
            "enterprise",
            "financial",
            "filing",
            "compliance",
            "security",
            "privacy",
            "trust",
            "regulator",
            "regulatory",
            "incident",
            "complaint",
            "contradict",
            "outperform",
            "superior",
            "leading",
            "leader",
            "dominant",
            "strongest",
            "cheaper",
            "expensive",
            "定价",
            "价格",
            "收费",
            "合规",
            "安全",
            "隐私",
            "监管",
            "投诉",
            "事故",
            "领先",
            "最强",
            "显著优势",
        }
        if any(term in text for term in high_risk_terms):
            return "high"
        medium_risk_terms = {
            "comparison",
            "market",
            "growth",
            "customer",
            "segment",
            "persona",
            "review",
            "sentiment",
            "capability",
            "feature",
            "integration",
            "ecosystem",
            "用户",
            "客户",
            "市场",
            "增长",
            "功能",
            "能力",
            "集成",
        }
        if any(term in text for term in medium_risk_terms):
            return "medium"
        return "low"

    def _claim_text(
        self,
        competitor: str,
        dimension_name: str,
        fact_type: str,
        subject: str,
        predicate: str,
        fact_objects: list[str],
    ) -> str:
        label = self._fact_type_label(fact_type)
        predicate_phrase = self._predicate_phrase(predicate)
        unique_objects = self._dedupe(fact_objects)
        if not unique_objects:
            return f"{competitor} {dimension_name}: accepted public evidence contains {label}."
        if fact_type == "pricing_signal":
            pricing_summary = self._pricing_claim_summary(unique_objects)
            if pricing_summary:
                return f"{competitor} {dimension_name}: public evidence reports {pricing_summary}."
        subject = clean_text(subject)
        if len(unique_objects) == 1:
            if subject and predicate_phrase:
                return (
                    f"{competitor} {dimension_name}: public evidence "
                    f"{predicate_phrase} {subject}: {unique_objects[0]}."
                )
            return f"{competitor} {dimension_name}: public evidence {label} {unique_objects[0]}."
        examples = "; ".join(unique_objects[:3])
        return (
            f"{competitor} {dimension_name}: public evidence contains multiple "
            f"{label}, including {examples}."
        )[:520]

    def _revised_claims_from_support_reviews(
        self,
        claims: list[dict[str, Any]],
        reviews: list[dict[str, Any]],
    ) -> list[AnalysisClaim]:
        if not claims or not reviews:
            return []
        review_by_claim = {
            review.get("claim_id", ""): review
            for review in reviews
            if review.get("claim_id")
        }
        revised_claims: list[AnalysisClaim] = []
        changed = False
        for claim in claims:
            review = review_by_claim.get(claim.get("id", ""), {})
            if (
                review.get("recommended_action") == "revise"
                and review.get("suggested_revision")
            ):
                changed = True
                revised_claims.append(
                    {
                        **claim,
                        "claim": review["suggested_revision"],
                        "reasoning": (
                            str(claim.get("reasoning", "")).rstrip()
                            + " Revised after ClaimSupportReviewer requested tighter wording."
                        ).strip(),
                        "confidence": min(
                            float(claim.get("confidence", 0.5)),
                            float(review.get("confidence", 0.5)),
                        ),
                    }
                )
                continue
            revised_claims.append(claim)
        return revised_claims if changed else []

    def _pricing_claim_summary(self, fact_objects: list[str]) -> str:
        details: list[str] = []
        for text in fact_objects:
            details.extend(self._pricing_details(text))
            lowered = text.lower()
            if (
                "free tier available" in lowered
                or any(term in text for term in ("免费版", "免费套餐", "免费计划"))
            ) and "free tier available" not in details:
                details.append("free tier available")
            if (
                "quote" in lowered
                or any(term in text for term in ("联系销售", "定制报价", "企业版询价"))
            ) and "enterprise pricing requires sales contact" not in details:
                details.append("enterprise pricing requires sales contact")
        if not details:
            return ""
        return "; ".join(self._dedupe(details)[:5])

    def _pricing_details(self, text: str) -> list[str]:
        details: list[str] = []
        patterns = [
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{1,24})\s+pricing is\s+(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:人|用户|user|seat)?\s*/?\s*(?:月|年|month|mo|year|yr))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{0,24}(?:版|套餐|计划|plan|tier)?)\s*(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:人|用户|user|seat)?\s*/?\s*(?:月|年|month|mo|year|yr))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{0,24}(?:版|套餐|计划|plan|tier)?)\s*(?:定价为|价格为|收费为|每人每月)\s*(?P<price>\d+(?:[.,]\d+)?\s*元(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{0,24}(?:版|套餐|计划|plan|tier)?)\s*(?P<price>\d+(?:[.,]\d+)?\s*元(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                plan = " ".join((match.group("plan") or "").split()).strip(" ：:-")
                plan = self._clean_pricing_plan(plan)
                price = " ".join((match.group("price") or "").split())
                if not price:
                    continue
                if not self._valid_pricing_plan(plan):
                    continue
                detail = f"{plan} {price}" if plan else price
                if detail not in details:
                    details.append(detail)
        return details

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

    def _fact_type_label(self, fact_type: str) -> str:
        return {
            "pricing_signal": "pricing signals",
            "feature_presence": "product capability signals",
            "target_user_signal": "target-user signals",
            "trust_compliance_signal": "trust or compliance signals",
            "integration_signal": "integration or ecosystem signals",
            "market_signal": "market signals",
            "public_evidence_signal": "relevant public evidence signals",
        }.get(fact_type, "relevant public evidence signals")

    def _predicate_phrase(self, predicate: str) -> str:
        return {
            "exists": "shows",
            "publishes_price": "publishes pricing for",
            "requires_quote": "marks pricing as quote-based for",
            "uses_billing_model": "describes",
            "offers_discount": "describes a discount for",
            "publishes": "publishes",
            "describes": "describes",
            "signals": "signals",
            "documents": "documents",
            "reports": "reports",
            "indicates": "indicates",
        }.get(predicate, "")

    def _fact_object_preview(self, fact: dict[str, Any]) -> str:
        text = clean_text(fact.get("object") or fact.get("statement", ""))
        if not text or is_low_quality_text(text):
            return ""
        return " ".join(text.split())[:320]

    def _claim_normalized_key(
        self,
        competitor: str,
        analysis_dimension_id: str,
        claim_type: str,
        subject: str = "",
        predicate: str = "",
        fact_key: str = "",
    ) -> str:
        return "|".join(
            [
                self._normalize_key_part(competitor or "unknown"),
                self._normalize_key_part(analysis_dimension_id or "unknown"),
                self._normalize_key_part(claim_type or "claim"),
                self._normalize_key_part(subject or "subject"),
                self._normalize_key_part(predicate or "predicate"),
                self._normalize_key_part(fact_key or "fact"),
            ]
        )

    def _normalize_key_part(self, value: str) -> str:
        import re

        return (
            re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", str(value).lower()).strip("_")
            or "unknown"
        )

    def _average_fact_confidence(self, facts: list[dict[str, Any]]) -> float:
        confidences = [
            float(fact.get("confidence", 0.5))
            for fact in facts
        ]
        if not confidences:
            return 0.5
        return round(sum(confidences) / len(confidences), 2)

    def _bounded_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.6
        return round(max(0.0, min(1.0, confidence)), 2)

    def _dedupe(self, values: Any) -> list[Any]:
        return list(dict.fromkeys(value for value in values if value))

    def _analysis_dimension_lookup(
        self,
        state: CompetitorAnalysisState,
    ) -> dict[str, dict[str, Any]]:
        dimensions_by_id: dict[str, dict[str, Any]] = {}
        for dimension in state.get("analysis_dimensions", []):
            dimension_id = dimension.get("id", "")
            if dimension_id:
                dimensions_by_id[dimension_id] = dimension
            for schema_field_id in dimension.get("schema_field_ids", []):
                if schema_field_id:
                    dimensions_by_id.setdefault(schema_field_id, dimension)
        return dimensions_by_id

    def _claims_from_quality_accepted_evidence(
        self,
        state: CompetitorAnalysisState,
    ) -> list[AnalysisClaim]:
        dimensions_by_id = self._analysis_dimension_lookup(state)
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in state.get("evidence_items", [])
            if evidence.get("id")
        }
        branch_by_id = {
            branch.get("id", ""): branch
            for branch in state.get("research_branches", [])
            if branch.get("id")
        }
        claims: list[AnalysisClaim] = []

        for review in state.get("evidence_reviews", []):
            accepted_ids = [
                evidence_id
                for evidence_id in review.get("accepted_evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
            if not accepted_ids:
                continue

            branch = branch_by_id.get(review.get("branch_id", ""), {})
            claim_candidates = []
            for evidence_id in accepted_ids:
                evidence = evidence_by_id[evidence_id]
                competitor = (
                    branch.get("competitor")
                    or evidence.get("competitor")
                    or "the target competitor"
                )
                dimension = (
                    branch.get("analysis_dimension_id")
                    or evidence.get("analysis_dimension_id")
                )
                if not dimension or dimension == "competitor_profile":
                    continue
                evidence_text = self._evidence_excerpt_preview([evidence])
                if is_low_quality_text(evidence_text):
                    continue
                dimension_name = (
                    branch.get("dimension_name")
                    or evidence.get("dimension_name")
                    or dimensions_by_id.get(dimension, {}).get("name")
                    or dimension.replace("_", " ")
                )
                report_section_id = (
                    evidence.get("report_section_id")
                    or branch.get("report_section_id")
                    or primary_report_section_id(
                        dimensions_by_id.get(dimension, {"id": dimension}),
                    )
                )
                claim_candidates.append(
                    {
                        "competitor": str(competitor),
                        "analysis_dimension_id": dimension,
                        "dimension_name": str(dimension_name),
                        "report_section_id": report_section_id,
                        "evidence": evidence,
                        "evidence_id": evidence_id,
                        "claim": self._evidence_claim_text(
                            str(competitor),
                            str(dimension_name),
                            evidence,
                        ),
                    }
                )

            for cluster in self._cluster_claim_candidates(claim_candidates):
                representative = cluster[0]
                cluster_evidence_items = [candidate["evidence"] for candidate in cluster]
                cluster_evidence_ids = [candidate["evidence_id"] for candidate in cluster]
                claims.append(
                    {
                        "id": f"claim_{len(claims) + 1}",
                        "analysis_dimension_id": representative["analysis_dimension_id"],
                        "knowledge_fact_ids": [],
                        "report_section_id": representative.get("report_section_id", ""),
                        "claim_source": "accepted_evidence",
                        "claim_type": "public_evidence_signal",
                        "claim_risk_level": self._claim_risk_level(
                            claim_type="public_evidence_signal",
                            analysis_dimension_id=representative["analysis_dimension_id"],
                            claim_text=representative["claim"],
                        ),
                        "branch_id": review.get("branch_id", ""),
                        "evidence_review_id": review.get("id", ""),
                        "claim": representative["claim"],
                        "competitors": [representative["competitor"]]
                        if representative["competitor"]
                        else [],
                        "evidence_ids": cluster_evidence_ids,
                        "reasoning": (
                            "Derived immediately after EvidenceQualityReviewer accepted "
                            f"{len(cluster_evidence_ids)} EvidenceItem(s) supporting the same "
                            "atomic claim for this schema dimension."
                        ),
                        "confidence": self._quality_gated_confidence(
                            cluster_evidence_items,
                            review,
                        ),
                    }
                )

        return claims

    def _cluster_claim_candidates(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        clusters: list[list[dict[str, Any]]] = []
        for candidate in candidates:
            for cluster in clusters:
                if self._same_atomic_claim(candidate, cluster[0]):
                    cluster.append(candidate)
                    break
            else:
                clusters.append([candidate])
        return clusters

    def _same_atomic_claim(
        self,
        candidate: dict[str, Any],
        seed: dict[str, Any],
    ) -> bool:
        if candidate.get("analysis_dimension_id") != seed.get("analysis_dimension_id"):
            return False
        if candidate.get("competitor") != seed.get("competitor"):
            return False

        candidate_text = self._normalize_claim_text(candidate.get("claim", ""))
        seed_text = self._normalize_claim_text(seed.get("claim", ""))
        if not candidate_text or not seed_text:
            return False
        if candidate_text == seed_text:
            return True
        if len(candidate_text) > 60 and len(seed_text) > 60:
            if candidate_text in seed_text or seed_text in candidate_text:
                return True

        candidate_tokens = self._claim_similarity_tokens(candidate_text)
        seed_tokens = self._claim_similarity_tokens(seed_text)
        if min(len(candidate_tokens), len(seed_tokens)) < 4:
            return False
        overlap = len(candidate_tokens & seed_tokens)
        return (
            overlap / min(len(candidate_tokens), len(seed_tokens)) >= 0.7
            and overlap / max(len(candidate_tokens), len(seed_tokens)) >= 0.45
        )

    def _normalize_claim_text(self, text: str) -> str:
        import re

        normalized = " ".join(str(text).lower().split())
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized).strip()

    def _claim_similarity_tokens(self, text: str) -> set[str]:
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "has",
            "have",
            "its",
            "their",
            "acme",
        }
        return {
            token
            for token in text.split()
            if len(token) >= 3 and token not in stopwords
        }

    def _evidence_claim_text(
        self,
        competitor: str,
        dimension_name: str,
        evidence: dict[str, Any],
    ) -> str:
        evidence_preview = self._evidence_excerpt_preview([evidence])
        return f"{competitor} {dimension_name}: {evidence_preview}"

    def _evidence_excerpt_preview(self, evidence_items: list[dict[str, Any]]) -> str:
        snippets = []
        for evidence in evidence_items[:2]:
            text = (
                evidence.get("excerpt")
                or evidence.get("title")
                or evidence.get("url")
                or ""
            )
            normalized = " ".join(clean_text(text).split())
            if normalized:
                snippets.append(normalized[:220])
        return " ".join(snippets)[:420] or "accepted source-backed evidence is available."

    def _quality_gated_confidence(
        self,
        evidence_items: list[dict[str, Any]],
        review: dict[str, Any],
    ) -> float:
        evidence_confidences = [
            float(evidence.get("confidence", 0.5))
            for evidence in evidence_items
        ]
        evidence_confidence = (
            sum(evidence_confidences) / len(evidence_confidences)
            if evidence_confidences
            else 0.5
        )
        review_score = float(review.get("score", evidence_confidence))
        return round(max(0.0, min(1.0, (evidence_confidence + review_score) / 2)), 2)

    def _append_feature_claims(self, claims: list[AnalysisClaim], knowledge: dict) -> None:
        competitor = knowledge.get("competitor", "")
        for feature in knowledge.get("feature_tree", []):
            description = feature.get("description") or feature.get("name") or ""
            description = clean_text(description)
            if not description:
                continue
            if is_low_quality_text(description):
                continue
            dimension = feature.get("category", "feature_tree")
            claims.append(
                {
                    "id": f"claim_{len(claims) + 1}",
                    "analysis_dimension_id": dimension,
                    "knowledge_fact_ids": [],
                    "report_section_id": primary_report_section_id({"id": dimension}),
                    "claim_source": "competitor_knowledge",
                    "claim_type": "capability_signal",
                    "claim_risk_level": self._claim_risk_level(
                        claim_type="capability_signal",
                        analysis_dimension_id=dimension,
                        claim_text=f"{competitor} shows a product capability signal: {description[:420]}",
                    ),
                    "claim": f"{competitor} shows a product capability signal: {description[:420]}",
                    "competitors": [competitor] if competitor else [],
                    "evidence_ids": feature.get("evidence_ids", []),
                    "reasoning": "Derived from the active CompetitorKnowledge feature tree.",
                    "confidence": feature.get("confidence", knowledge.get("confidence", 0.5)),
                }
            )

    def _append_pricing_claims(self, claims: list[AnalysisClaim], knowledge: dict) -> None:
        competitor = knowledge.get("competitor", "")
        pricing_model = knowledge.get("pricing_model", {})
        plans = pricing_model.get("plans", [])
        if not plans:
            return
        evidence_ids = [
            evidence_id
            for plan in plans
            for evidence_id in plan.get("evidence_ids", [])
        ]
        plan_names = ", ".join(plan.get("name", "observed plan") for plan in plans[:4])
        plan_names = clean_text(plan_names)
        if is_low_quality_text(plan_names):
            return
        claims.append(
            {
                "id": f"claim_{len(claims) + 1}",
                "analysis_dimension_id": "pricing_model",
                "knowledge_fact_ids": [],
                "report_section_id": primary_report_section_id({"id": "pricing_model"}),
                "claim_source": "competitor_knowledge",
                "claim_type": "pricing_strategy",
                "claim_risk_level": self._claim_risk_level(
                    claim_type="pricing_strategy",
                    analysis_dimension_id="pricing_model",
                    claim_text=f"{competitor} has public pricing-model signals around: {plan_names}.",
                ),
                "claim": f"{competitor} has public pricing-model signals around: {plan_names}.",
                "competitors": [competitor] if competitor else [],
                "evidence_ids": evidence_ids,
                "reasoning": "Derived from the active CompetitorKnowledge pricing model.",
                "confidence": pricing_model.get("confidence", knowledge.get("confidence", 0.5)),
            }
        )

    def _append_persona_claims(self, claims: list[AnalysisClaim], knowledge: dict) -> None:
        competitor = knowledge.get("competitor", "")
        for persona in knowledge.get("user_personas", []):
            needs = clean_text(", ".join(persona.get("needs", [])[:3]))
            if not needs:
                continue
            if is_low_quality_text(needs):
                continue
            claims.append(
                {
                    "id": f"claim_{len(claims) + 1}",
                    "analysis_dimension_id": "user_personas",
                    "knowledge_fact_ids": [],
                    "report_section_id": primary_report_section_id({"id": "user_personas"}),
                    "claim_source": "competitor_knowledge",
                    "claim_type": "customer_segment_signal",
                    "claim_risk_level": self._claim_risk_level(
                        claim_type="customer_segment_signal",
                        analysis_dimension_id="user_personas",
                        claim_text=f"{competitor} appears to serve {persona.get('segment', 'a user segment')} needs: {needs}.",
                    ),
                    "claim": f"{competitor} appears to serve {persona.get('segment', 'a user segment')} needs: {needs}.",
                    "competitors": [competitor] if competitor else [],
                    "evidence_ids": persona.get("evidence_ids", []),
                    "reasoning": "Derived from the active CompetitorKnowledge user-persona model.",
                    "confidence": persona.get("confidence", knowledge.get("confidence", 0.5)),
                }
            )
