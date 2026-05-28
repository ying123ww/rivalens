"""Analysis agent that turns evidence into traceable claims."""

from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import AnalysisClaim, CompetitorAnalysisState


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
                    "output": {"claim_count": len(claims)},
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
            if not review.get("accepted") and review.get("required_action") != "accept":
                continue

            accepted_ids = [
                evidence_id
                for evidence_id in review.get("accepted_evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
            if not accepted_ids:
                continue

            evidence_items = [evidence_by_id[evidence_id] for evidence_id in accepted_ids]
            branch = branch_by_id.get(review.get("branch_id", ""), {})
            competitor = (
                branch.get("competitor")
                or evidence_items[0].get("competitor")
                or "the target competitor"
            )
            dimension = (
                branch.get("dimension_id")
                or evidence_items[0].get("dimension_id")
                or "source_evidence"
            )
            dimension_name = (
                branch.get("dimension_name")
                or evidence_items[0].get("dimension_name")
                or dimension.replace("_", " ")
            )

            claims.append(
                {
                    "id": f"claim_{len(claims) + 1}",
                    "dimension": dimension,
                    "branch_id": review.get("branch_id", ""),
                    "evidence_review_id": review.get("id", ""),
                    "claim": self._branch_claim_text(
                        str(competitor),
                        str(dimension_name),
                        evidence_items,
                    ),
                    "competitors": [str(competitor)] if competitor else [],
                    "evidence_ids": accepted_ids,
                    "reasoning": (
                        "Derived immediately after EvidenceQualityReviewer accepted "
                        "the branch evidence for this schema dimension."
                    ),
                    "confidence": self._quality_gated_confidence(evidence_items, review),
                }
            )

        return claims

    def _branch_claim_text(
        self,
        competitor: str,
        dimension_name: str,
        evidence_items: list[dict[str, Any]],
    ) -> str:
        evidence_preview = self._evidence_excerpt_preview(evidence_items)
        return f"{competitor} has quality-reviewed {dimension_name} evidence: {evidence_preview}"

    def _evidence_excerpt_preview(self, evidence_items: list[dict[str, Any]]) -> str:
        snippets = []
        for evidence in evidence_items[:2]:
            text = (
                evidence.get("excerpt")
                or evidence.get("title")
                or evidence.get("url")
                or ""
            )
            normalized = " ".join(str(text).split())
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
            if not description:
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
            needs = ", ".join(persona.get("needs", [])[:3])
            if not needs:
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
