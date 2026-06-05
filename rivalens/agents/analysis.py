"""Analysis agent that turns evidence into traceable claims."""

from collections import defaultdict
from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.report_routing import primary_report_section_id
from rivalens.schema import AnalysisClaim, CompetitorAnalysisState
from rivalens.text_quality import clean_text, is_low_quality_text


class AnalysisAgent:
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
        claims = self._claims_from_knowledge_facts(state, knowledge_facts)
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
                        "message_id": knowledge_message.get("id") if knowledge_message else None,
                        "evidence_review_count": len(state.get("evidence_reviews", [])),
                    },
                    "output": {
                        "claim_count": len(claims),
                        "claim_granularity": (
                            "knowledge_fact"
                            if claim_source == "knowledge_facts"
                            else (
                                "accepted_evidence_cluster"
                                if claim_source == "accepted_evidence_reviews"
                                else "competitor_knowledge"
                            )
                        ),
                    },
                }
            ],
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
        return " ".join(text.split())[:180]

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
                    "claim": f"{competitor} appears to serve {persona.get('segment', 'a user segment')} needs: {needs}.",
                    "competitors": [competitor] if competitor else [],
                    "evidence_ids": persona.get("evidence_ids", []),
                    "reasoning": "Derived from the active CompetitorKnowledge user-persona model.",
                    "confidence": persona.get("confidence", knowledge.get("confidence", 0.5)),
                }
            )
