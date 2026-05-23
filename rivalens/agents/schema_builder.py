"""Schema-building agent for competitor knowledge facts."""

from rivalens.agents.messages import create_agent_message
from rivalens.research import ResearchToolkit
from rivalens.schema import CompetitorAnalysisState, ProductFact


class SchemaBuilderAgent:
    def __init__(self, research_toolkit: ResearchToolkit | None = None):
        self.research_toolkit = research_toolkit or ResearchToolkit()

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        task = state.get("task", {})
        verbose = bool(task.get("verbose", True))
        evidence_items = state.get("evidence_items", [])
        facts: list[ProductFact] = []

        schema_research = await self.research_toolkit.extract_schema(
            query=f"Extract competitor knowledge schema facts for: {task.get('query', '')}",
            context=evidence_items,
            verbose=verbose,
        )

        for evidence in evidence_items:
            evidence_id = evidence.get("id", "")
            summary = evidence.get("summary") or evidence.get("excerpt") or ""
            if not summary:
                continue

            facts.append(
                {
                    "id": f"fact_{len(facts) + 1}",
                    "competitor": evidence.get("competitor", ""),
                    "dimension": "public_signal",
                    "value": summary[:500],
                    "evidence_ids": [evidence_id] if evidence_id else [],
                    "confidence": evidence.get("confidence", 0.5),
                }
            )

        artifact = {
            "id": "artifact_schema_extraction_1",
            "agent": "schema_builder",
            "mode": schema_research["mode"],
            "query": schema_research["query"],
            "report": schema_research["report"],
            "context": schema_research["context"],
            "costs": schema_research["costs"],
        }
        message = create_agent_message(
            sender="schema_builder",
            receiver="analysis",
            message_type="schema",
            payload={"fact_count": len(facts), "facts": facts},
            artifact_ids=[artifact["id"]],
            evidence_ids=[evidence_id for fact in facts for evidence_id in fact.get("evidence_ids", [])],
        )

        return {
            "product_facts": facts,
            "research_artifacts": state.get("research_artifacts", []) + [artifact],
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "schema_builder",
                    "action": "extract_competitor_knowledge_facts",
                    "input": {"evidence_count": len(evidence_items)},
                    "output": {"fact_count": len(facts), "research_mode": schema_research["mode"]},
                }
            ],
        }
