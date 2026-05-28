"""Report writer for structured competitor analysis output."""

import json
from typing import Any, Callable

from rivalens.agents.messages import create_agent_message
from rivalens.schema import CompetitorAnalysisState
from rivalens.research.config import Config
from rivalens.research.prompts import get_prompt_family
from rivalens.research.skills.writer import ReportGenerator
from rivalens.research.utils.enum import ReportSource, ReportType, Tone


class _ReportResearcherAdapter:
    """Small adapter exposing the ResearchEngine fields used by ReportGenerator."""

    def __init__(
        self,
        query: str,
        context: str,
        cfg: Config,
        role: str,
    ) -> None:
        self.query = query
        self.report_type = ReportType.ResearchReport.value
        self.report_source = ReportSource.Web.value
        self.tone = Tone.Analytical
        self.websocket = None
        self.cfg = cfg
        self.headers: dict[str, str] = {}
        self.context = context
        self.kwargs: dict[str, Any] = {}
        self.role = role
        self.parent_query = ""
        self.subtopics: list[str] = []
        self.verbose = False
        self.research_costs = 0.0
        self.step_costs: dict[str, float] = {}
        self._current_step = "report_writing"
        self.log_handler = None
        self.prompt_family = get_prompt_family(
            getattr(cfg, "prompt_family", "default"),
            cfg,
        )

    def get_research_images(self, top_k: int = 10) -> list[dict[str, Any]]:
        return []

    def add_costs(self, cost: float) -> None:
        self.research_costs += float(cost)
        step = self._current_step
        self.step_costs[step] = self.step_costs.get(step, 0.0) + float(cost)


class ReportWriterAgent:
    def __init__(
        self,
        config: Config | None = None,
        report_generator_factory: Callable[[Any], Any] = ReportGenerator,
    ) -> None:
        self.config = config
        self.report_generator_factory = report_generator_factory

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        claims = state.get("analysis_claims", [])
        evidence_items = self._report_evidence_items(state, claims)
        evidence_ids = self._ordered_evidence_ids(claims, evidence_items)
        context = self._build_report_context(state, claims, evidence_items)
        query = self._report_query(state)
        cfg = self.config or Config()
        researcher = _ReportResearcherAdapter(
            query=query,
            context=context,
            cfg=cfg,
            role=self._writer_role_prompt(),
        )
        generator = self.report_generator_factory(researcher)

        generation_error = None
        try:
            generated_report = await generator.write_report()
        except Exception as exc:
            generated_report = ""
            generation_error = str(exc)
        report = (generated_report or "").strip()
        if not report:
            report = self._fallback_report(state, claims, evidence_items)
        report = self._append_traceability_section(report, claims, evidence_items)
        report_length = len(report)
        generated_report_length = len(generated_report or "")

        return {
            "report": report,
            "messages": state.get("messages", [])
            + [
                create_agent_message(
                    sender="writer",
                    receiver="publisher",
                    message_type="report",
                    payload={"report_length": report_length},
                    evidence_ids=evidence_ids,
                )
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "writer",
                    "action": "compose_traceable_research_report",
                    "input": {
                        "query": query,
                        "claim_count": len(claims),
                        "evidence_count": len(evidence_items),
                        "report_generator": generator.__class__.__name__,
                        "report_type": researcher.report_type,
                        "report_source": researcher.report_source,
                        "prompt_family": researcher.prompt_family.__class__.__name__,
                        "context_length": len(context),
                        "model": getattr(cfg, "smart_llm_model", None),
                        "token_limit": getattr(cfg, "smart_token_limit", None),
                    },
                    "output": {
                        "generated_report_length": generated_report_length,
                        "report_length": report_length,
                        "fallback_used": not bool(generated_report),
                        "cost": researcher.research_costs,
                        "step_costs": researcher.step_costs,
                        "generation_error": generation_error,
                    },
                }
            ],
        }

    def _report_query(self, state: CompetitorAnalysisState) -> str:
        task = state.get("task", {})
        base_query = task.get("query") or "Write a competitor analysis report."
        return (
            f"{base_query}\n\n"
            "Write a traceable competitor analysis report using only the provided "
            "Rivalens context. Keep important claims tied to evidence IDs and source URLs."
        )

    def _writer_role_prompt(self) -> str:
        return (
            "You are a competitive intelligence report writer. Write clear, "
            "source-grounded markdown reports. Do not introduce material claims "
            "that are not supported by the provided EvidenceItem records."
        )

    def _build_report_context(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> str:
        report_evidence_ids = {
            evidence.get("id", "")
            for evidence in evidence_items
            if evidence.get("id")
        }
        payload = {
            "reporting_constraints": [
                "Use analysis_claims as the main claim set.",
                "Keep evidence_ids visible for material claims.",
                "Use EvidenceItem.url values as source URLs.",
                "Do not use rejected evidence as support for claims.",
            ],
            "task": state.get("task", {}),
            "active_knowledge_schema": state.get("active_knowledge_schema", {}),
            "analysis_claims": [
                self._compact_claim(claim, report_evidence_ids)
                for claim in claims
            ],
            "competitor_knowledge": state.get("competitor_knowledge", []),
            "evidence_items": [
                self._compact_evidence_item(evidence)
                for evidence in evidence_items
            ],
            "evidence_reviews": [
                self._compact_evidence_review(review, report_evidence_ids)
                for review in state.get("evidence_reviews", [])
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _compact_claim(
        self,
        claim: dict[str, Any],
        report_evidence_ids: set[str],
    ) -> dict[str, Any]:
        return {
            "id": claim.get("id", ""),
            "dimension": claim.get("dimension", ""),
            "branch_id": claim.get("branch_id", ""),
            "evidence_review_id": claim.get("evidence_review_id", ""),
            "claim": claim.get("claim", ""),
            "competitors": claim.get("competitors", []),
            "evidence_ids": [
                evidence_id
                for evidence_id in claim.get("evidence_ids", [])
                if evidence_id in report_evidence_ids
            ],
            "reasoning": claim.get("reasoning", ""),
            "confidence": claim.get("confidence", 0.5),
        }

    def _compact_evidence_item(self, evidence: dict[str, Any]) -> dict[str, Any]:
        excerpt = " ".join(str(evidence.get("excerpt", "")).split())
        return {
            "id": evidence.get("id", ""),
            "competitor": evidence.get("competitor", ""),
            "branch_id": evidence.get("branch_id", ""),
            "collection_task_id": evidence.get("collection_task_id", ""),
            "dimension_id": evidence.get("dimension_id", ""),
            "dimension_name": evidence.get("dimension_name", ""),
            "title": evidence.get("title", ""),
            "url": evidence.get("url", ""),
            "source_type": evidence.get("source_type", ""),
            "published_at": evidence.get("published_at"),
            "retrieved_at": evidence.get("retrieved_at", ""),
            "excerpt": excerpt[:1200],
            "confidence": evidence.get("confidence", 0.5),
        }

    def _compact_evidence_review(
        self,
        review: dict[str, Any],
        report_evidence_ids: set[str],
    ) -> dict[str, Any]:
        return {
            "id": review.get("id", ""),
            "branch_id": review.get("branch_id", ""),
            "collection_task_id": review.get("collection_task_id", ""),
            "accepted": review.get("accepted", False),
            "score": review.get("score", 0.0),
            "accepted_evidence_ids": [
                evidence_id
                for evidence_id in review.get("accepted_evidence_ids", [])
                if evidence_id in report_evidence_ids
            ],
            "rejected_evidence_count": len(review.get("rejected_evidence_ids", [])),
            "required_action": review.get("required_action", ""),
        }

    def _report_evidence_items(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence_items = state.get("evidence_items", [])
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }
        rejected_ids = {
            evidence_id
            for review in state.get("evidence_reviews", [])
            for evidence_id in review.get("rejected_evidence_ids", [])
        }
        claim_evidence_ids = [
            evidence_id
            for claim in claims
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id in evidence_by_id and evidence_id not in rejected_ids
        ]
        if claim_evidence_ids:
            return [
                evidence_by_id[evidence_id]
                for evidence_id in dict.fromkeys(claim_evidence_ids)
            ]

        accepted_ids = [
            evidence_id
            for review in state.get("evidence_reviews", [])
            for evidence_id in review.get("accepted_evidence_ids", [])
            if evidence_id in evidence_by_id
        ]
        if accepted_ids:
            return [
                evidence_by_id[evidence_id]
                for evidence_id in dict.fromkeys(accepted_ids)
            ]

        return [
            evidence
            for evidence in evidence_items
            if evidence.get("id", "") not in rejected_ids
        ]

    def _ordered_evidence_ids(
        self,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        report_evidence_ids = {
            evidence.get("id", "")
            for evidence in evidence_items
            if evidence.get("id")
        }
        ordered_ids = [
            evidence_id
            for claim in claims
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id in report_evidence_ids
        ]
        ordered_ids.extend(
            evidence.get("id", "")
            for evidence in evidence_items
            if evidence.get("id")
        )
        return list(dict.fromkeys(ordered_ids))

    def _fallback_report(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> str:
        task = state.get("task", {})
        lines = [
            "# Competitor Analysis Report",
            "",
            f"Task: {task.get('query', 'Competitor analysis')}",
            "",
            "## Key Claims",
        ]
        if claims:
            report_evidence_ids = {
                evidence.get("id", "")
                for evidence in evidence_items
                if evidence.get("id")
            }
            for claim in claims:
                evidence_ids = ", ".join(
                    evidence_id
                    for evidence_id in claim.get("evidence_ids", [])
                    if evidence_id in report_evidence_ids
                ) or "no evidence"
                lines.append(f"- {claim.get('claim', '')} [evidence: {evidence_ids}]")
        else:
            lines.append("- No claims generated yet.")

        if evidence_items:
            lines.extend(["", "## Source Summary"])
            for evidence in evidence_items:
                label = evidence.get("id", "evidence")
                title = evidence.get("title") or evidence.get("url") or "Untitled source"
                url = evidence.get("url", "")
                lines.append(f"- [{label}] {title}: {url}")
        return "\n".join(lines)

    def _append_traceability_section(
        self,
        report: str,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> str:
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }
        lines = [
            "",
            "## Rivalens Evidence Traceability",
            "",
            "| Claim ID | Evidence IDs | Source URLs |",
            "| --- | --- | --- |",
        ]
        if claims:
            for claim in claims:
                claim_evidence_ids = [
                    evidence_id
                    for evidence_id in claim.get("evidence_ids", [])
                    if evidence_id in evidence_by_id
                ]
                urls = [
                    evidence_by_id[evidence_id].get("url", "")
                    for evidence_id in claim_evidence_ids
                    if evidence_by_id[evidence_id].get("url")
                ]
                lines.append(
                    "| "
                    f"{claim.get('id', '') or 'claim'} | "
                    f"{', '.join(claim_evidence_ids) or 'no evidence'} | "
                    f"{'<br>'.join(urls) or 'no source URL'} |"
                )
        else:
            lines.append("| no claims | no evidence | no source URL |")

        lines.extend(["", "### Evidence Items"])
        if evidence_items:
            for evidence in evidence_items:
                evidence_id = evidence.get("id", "")
                url = evidence.get("url", "")
                title = evidence.get("title") or url or "Untitled source"
                lines.append(f"- `{evidence_id}`: {title} ({url or 'no source URL'})")
        else:
            lines.append("- No EvidenceItem records were available to the writer.")
        return f"{report.rstrip()}\n" + "\n".join(lines)
