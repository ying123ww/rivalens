"""Structure collected evidence into the active competitor knowledge schema."""

from collections import defaultdict
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from rivalens.agents.evidence_snippets import EvidenceSnippetBuilder
from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState, CompetitorKnowledge, KnowledgeFact
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


PRICING_ATOM_PREDICATES = {
    "free_tier": "exists",
    "published_plan_price": "publishes_price",
    "quote_only": "requires_quote",
    "usage_based_billing": "uses_billing_model",
    "annual_discount": "offers_discount",
}


class KnowledgeStructuringAgent:
    def __init__(
        self,
        snippet_builder: EvidenceSnippetBuilder | None = None,
    ) -> None:
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

        knowledge_facts, fact_extraction = self._build_knowledge_facts_with_metadata(
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
                        "rule_sentence_selected_count": fact_extraction.get(
                            "rule_sentence_selected_count",
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

    def _empty_atomization_stats(self) -> dict[str, int]:
        return {
            "rule_skipped_evidence_count": 0,
            "rule_semantic_noise_count": 0,
            "rule_sentence_selected_count": 0,
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
        if finding.get("sentence_selected"):
            stats["rule_sentence_selected_count"] += 1
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
        fact_object, sentence_selected = self._fact_object_with_metadata(
            evidence,
            text,
            fact_type,
        )
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
            finding["sentence_selected"] = sentence_selected
            return [], finding
        return [generic_fact], {
            "status": "atomic",
            "sentence_selected": sentence_selected,
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

    def _fact_sentences(self, text: str) -> list[str]:
        value = self._clean_evidence_text(text)
        if not value:
            return []
        raw_segments = re.split(r"(?<=[.!?。！？；;])\s*|\s+[|•]\s+|\s+-\s+", value)
        sentences: list[str] = []
        for segment in raw_segments:
            segment = " ".join(segment.split()).strip(" -:：|")
            if not segment:
                continue
            if len(segment) > 320:
                sentences.extend(self._split_long_fact_segment(segment))
                continue
            sentences.append(segment)
        return [sentence for sentence in sentences if len(sentence) >= 8]

    def _split_long_fact_segment(self, segment: str) -> list[str]:
        parts = re.split(r"(?<=[,，、])\s*", segment)
        chunks: list[str] = []
        current = ""
        for part in parts:
            part = part.strip(" ,，、")
            if not part:
                continue
            next_value = f"{current}，{part}" if current else part
            if len(next_value) <= 240:
                current = next_value
                continue
            if current:
                chunks.append(current)
            current = part
        if current:
            chunks.append(current)
        return chunks or [segment[:240]]

    def _score_fact_sentence(
        self,
        evidence: dict[str, Any],
        sentence: str,
        fact_type: str,
    ) -> int:
        if self._sentence_boilerplate_reason(sentence):
            return -100
        score = 0
        sentence_lower = sentence.lower()
        dimension_name = clean_text(evidence.get("dimension_name", ""))
        title = clean_text(evidence.get("title", ""))
        if 24 <= len(sentence) <= 220:
            score += 4
        elif len(sentence) < 16:
            score -= 3
        elif len(sentence) > 280:
            score -= 2
        if self._has_concrete_signal(sentence):
            score += 4
        if re.search(r"[$¥€£]\s?\d|\d+(?:[.,]\d+)?\s*(?:%|元|人|用户|月|年)", sentence):
            score += 3
        if any(
            keyword in sentence_lower
            for keyword in [
                "supports",
                "offers",
                "provides",
                "includes",
                "integrates",
                "certified",
                "pricing",
                "plan",
                "billing",
            ]
        ):
            score += 2
        if any(
            keyword in sentence
            for keyword in [
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
            ]
        ):
            score += 2
        if fact_type != "public_evidence_signal" and fact_type.replace("_", " ") in sentence_lower:
            score += 1
        for keyword in self._key_terms(dimension_name)[:4]:
            if keyword and keyword in self._key_terms(sentence):
                score += 1
        if title and not is_low_quality_text(title):
            title_head = self._concise_title(title).lower()
            if title_head and title_head in sentence_lower:
                score += 1
        score -= min(4, self._navigation_noise_hits(sentence))
        score -= min(3, self._page_list_noise_hits(sentence))
        return score

    def _sentence_boilerplate_reason(self, sentence: str) -> str:
        value = " ".join(str(sentence or "").split())
        if not value:
            return "empty"
        lower = value.lower()
        if "you need to enable javascript" in lower:
            return "javascript_fallback"
        if "以下内容由" in value and "AI" in value and "目标关键词" in value:
            return "ai_keyword_notice"
        if re.fullmatch(r"(?:nan[-/\s]*){2,}nan", lower):
            return "invalid_date_noise"
        if not self._has_concrete_signal(value):
            download_directory_reason = self._download_directory_noise_reason(value)
            if download_directory_reason:
                return download_directory_reason
            if self._navigation_noise_hits(value) >= 3:
                return "navigation_chrome"
            if self._page_list_noise_hits(value) >= 3:
                return "page_index"
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
        fact_type = self._fact_type_for_evidence(
            evidence,
            self._evidence_analysis_dimension_id(evidence),
            text,
        )
        fact_object, _sentence_selected = self._fact_object_with_metadata(
            evidence,
            text,
            fact_type,
        )
        return fact_object

    def _fact_object_with_metadata(
        self,
        evidence: dict[str, Any],
        text: str,
        fact_type: str,
    ) -> tuple[str, bool]:
        cleaned_text = self._clean_evidence_text(text)
        sentences = self._fact_sentences(cleaned_text)
        scored = [
            (self._score_fact_sentence(evidence, sentence, fact_type), sentence)
            for sentence in sentences
        ]
        scored = [(score, sentence) for score, sentence in scored if score > -100]
        if scored:
            score, selected = max(scored, key=lambda item: (item[0], len(item[1])))
            if score >= -2:
                selected = self._trim_fact_boilerplate(selected)
                if not selected:
                    return "", False
                sentence_selected = len(sentences) > 1 or len(selected) < len(cleaned_text) - 20
                return selected, sentence_selected

        fallback = self._trim_fact_boilerplate(cleaned_text)
        if self._sentence_boilerplate_reason(fallback):
            return "", False
        return fallback, False

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
                r"(?:支持|提供|采用|包括|集成|认证|定价|计费|突破|超过|同比增长|"
                r"战略级|安全合规|自主可控|supports|offers|provides|includes|"
                r"integrates|certified|pricing|billing)",
                value,
                flags=re.IGNORECASE,
            )
            if marker and marker.start() > 0:
                value = value[marker.start() :].strip(" ,，。；;:-")
        return value[:240]

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
        return str(
            evidence.get("analysis_dimension_id")
            or evidence.get("dimension_id")
            or ""
        )

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
