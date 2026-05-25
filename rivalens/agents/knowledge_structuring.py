"""Structure collected evidence into the active competitor knowledge schema."""

from collections import defaultdict
from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState, CompetitorKnowledge


class KnowledgeStructuringAgent:
    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        evidence_message = latest_message_for(
            state,
            receiver="knowledge_structuring",
            message_type="evidence",
            sender="collection",
        )
        active_schema = state.get("active_knowledge_schema", {})
        evidence_items = state.get("evidence_items", [])

        knowledge = self._build_competitor_knowledge(evidence_items, active_schema)
        message = create_agent_message(
            sender="knowledge_structuring",
            receiver="analysis",
            message_type="schema",
            payload={
                "knowledge_count": len(knowledge),
                "competitor_knowledge": knowledge,
            },
            evidence_ids=[
                evidence_id
                for item in knowledge
                for evidence_id in item.get("evidence_ids", [])
            ],
        )

        return {
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
                        "active_schema_id": active_schema.get("id"),
                        "message_id": evidence_message.get("id") if evidence_message else None,
                    },
                    "output": {
                        "knowledge_count": len(knowledge),
                    },
                }
            ],
        }

    def _build_competitor_knowledge(
        self,
        evidence_items: list[dict[str, Any]],
        active_schema: dict[str, Any],
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
                evidence_id = evidence.get("id", "")
                text = evidence.get("summary") or evidence.get("excerpt") or evidence.get("title") or ""
                if not text:
                    continue
                source_type = evidence.get("source_type", "other")
                confidence = evidence.get("confidence", 0.5)
                title = evidence.get("title", "")
                normalized_text = f"{title} {text}".lower()

                if source_type == "pricing_page" or "pricing" in normalized_text or "price" in normalized_text:
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

                if any(keyword in normalized_text for keyword in ["customer", "user", "persona", "segment", "用户", "客户"]):
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
                        "category": self._guess_feature_category(normalized_text, active_schema),
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
                    "active_schema_id": active_schema.get("id", ""),
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
                    "industry_extensions": {
                        extension.get("id", ""): {
                            "name": extension.get("name", ""),
                            "description": extension.get("description", ""),
                            "evidence_ids": evidence_ids,
                            "confidence": extension.get("confidence", 0.5),
                        }
                        for extension in active_schema.get("industry_extensions", [])
                        if extension.get("id")
                    },
                    "evidence_ids": evidence_ids,
                    "confidence": self._average_confidence(competitor_evidence),
                }
            )

        return knowledge_items

    def _guess_feature_category(self, text: str, active_schema: dict[str, Any]) -> str:
        for extension in active_schema.get("industry_extensions", []):
            extension_id = extension.get("id", "")
            extension_name = extension.get("name", "")
            tokens = [token for token in extension_id.replace("_", " ").split() if token]
            tokens.extend(token for token in extension_name.lower().split() if token)
            if any(token in text for token in tokens):
                return extension_id
        return "core_feature"

    def _average_confidence(self, items: list[dict[str, Any]]) -> float:
        confidences = [float(item.get("confidence", 0.5)) for item in items]
        if not confidences:
            return 0.5
        return round(sum(confidences) / len(confidences), 2)
