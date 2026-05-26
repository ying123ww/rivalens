"""Analysis agent that turns evidence into traceable claims."""

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.file_context import format_rag_context
from rivalens.research import ResearchToolkit
from rivalens.schema import AnalysisClaim, CompetitorAnalysisState


class AnalysisAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        verbose = bool(task.get("verbose", True))
        knowledge_message = latest_message_for(
            state,
            receiver="analysis",
            message_type="schema",
            sender="knowledge_structuring",
        )
        schema_payload = knowledge_message.get("payload", {}) if knowledge_message else {}
        competitor_knowledge = state.get("competitor_knowledge") or schema_payload.get("competitor_knowledge", [])
        claims: list[AnalysisClaim] = []
        file_rag = format_rag_context(
            state.get("file_context", {}),
            f"{task.get('query', '')} competitive implications",
            limit=8,
        )

        focused_research = await self.research_toolkit.focused_analysis(
            query=f"Analyze competitive implications for: {task.get('query', '')}",
            context={
                "active_schema": state.get("active_knowledge_schema", {}),
                "competitor_knowledge": competitor_knowledge,
                "local_file_rag": file_rag,
            },
            verbose=verbose,
        )

        for knowledge in competitor_knowledge:
            self._append_feature_claims(claims, knowledge)
            self._append_pricing_claims(claims, knowledge)
            self._append_persona_claims(claims, knowledge)

        artifact = {
            "id": "artifact_focused_analysis_1",
            "agent": "analysis",
            "mode": focused_research["mode"],
            "query": focused_research["query"],
            "report": focused_research["report"],
            "context": focused_research["context"],
            "costs": focused_research["costs"],
        }
        message = create_agent_message(
            sender="analysis",
            receiver="quality",
            message_type="analysis",
            payload={"claim_count": len(claims), "claims": claims},
            artifact_ids=[artifact["id"]],
            evidence_ids=[evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", [])],
        )

        return {
            "analysis_claims": claims,
            "research_artifacts": state.get("research_artifacts", []) + [artifact],
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "analysis",
                    "action": "derive_traceable_claims",
                    "input": {
                        "knowledge_count": len(competitor_knowledge),
                        "message_id": knowledge_message.get("id") if knowledge_message else None,
                    },
                    "output": {"claim_count": len(claims), "research_mode": focused_research["mode"]},
                }
            ],
        }

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
