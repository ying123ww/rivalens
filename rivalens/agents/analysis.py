"""Analysis agent that turns evidence into traceable claims."""

from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
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
        claims = self._claims_from_quality_accepted_evidence(state)
        claim_source = "accepted_evidence_reviews" if claims else "competitor_knowledge"

        if not claims:
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
                        "message_id": knowledge_message.get("id") if knowledge_message else None,
                        "evidence_review_count": len(state.get("evidence_reviews", [])),
                    },
                    "output": {
                        "claim_count": len(claims),
                        "claim_granularity": (
                            "accepted_evidence_cluster"
                            if claim_source == "accepted_evidence_reviews"
                            else "competitor_knowledge"
                        ),
                    },
                }
            ],
        }

    def _claims_from_quality_accepted_evidence(
        self,
        state: CompetitorAnalysisState,
    ) -> list[AnalysisClaim]:
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
                    branch.get("dimension_id")
                    or evidence.get("dimension_id")
                    or "source_evidence"
                )
                if dimension == "competitor_profile":
                    continue
                evidence_text = self._evidence_excerpt_preview([evidence])
                if is_low_quality_text(evidence_text):
                    continue
                dimension_name = (
                    branch.get("dimension_name")
                    or evidence.get("dimension_name")
                    or dimension.replace("_", " ")
                )
                claim_candidates.append(
                    {
                        "competitor": str(competitor),
                        "dimension": dimension,
                        "dimension_name": str(dimension_name),
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
                        "dimension": representative["dimension"],
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
        if candidate.get("dimension") != seed.get("dimension"):
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
            claims.append(
                {
                    "id": f"claim_{len(claims) + 1}",
                    "dimension": feature.get("category", "feature_tree"),
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
                "dimension": "pricing_model",
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
                    "dimension": "user_personas",
                    "claim": f"{competitor} appears to serve {persona.get('segment', 'a user segment')} needs: {needs}.",
                    "competitors": [competitor] if competitor else [],
                    "evidence_ids": persona.get("evidence_ids", []),
                    "reasoning": "Derived from the active CompetitorKnowledge user-persona model.",
                    "confidence": persona.get("confidence", knowledge.get("confidence", 0.5)),
                }
            )
