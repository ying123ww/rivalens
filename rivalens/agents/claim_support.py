"""Claim support review for traceable competitor analysis."""

from __future__ import annotations

import re
from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import ClaimSupportReview, CompetitorAnalysisState


class ClaimSupportReviewer:
    """Check whether claims are sufficiently supported by accepted evidence."""

    def review(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        analysis_message = latest_message_for(
            state,
            receiver="claim_support",
            message_type="analysis",
            sender="analysis",
        )
        claims = list(
            state.get("analysis_claims")
            or (analysis_message.get("payload", {}).get("claims", []) if analysis_message else [])
        )
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in state.get("evidence_items", [])
            if evidence.get("id")
        }
        knowledge_fact_by_id = {
            fact.get("id", ""): fact
            for fact in state.get("knowledge_facts", [])
            if fact.get("id")
        }
        reviews: list[ClaimSupportReview] = []
        supported_count = 0
        weak_count = 0
        contradicted_count = 0
        unverifiable_count = 0
        accepted_count = 0
        revision_count = 0
        suppressed_count = 0

        for claim in claims:
            claim_id = claim.get("id", "")
            evidence_ids = [
                evidence_id
                for evidence_id in claim.get("evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
            evidence_items = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
            knowledge_fact_ids = [
                fact_id
                for fact_id in claim.get("knowledge_fact_ids", [])
                if fact_id in knowledge_fact_by_id
            ]
            knowledge_facts = [
                knowledge_fact_by_id[fact_id]
                for fact_id in knowledge_fact_ids
            ]
            (
                status,
                recommended_action,
                unsupported_phrases,
                suggested_revision,
                reviewer_notes,
                confidence,
            ) = self._review_claim_support(
                claim,
                evidence_items,
                knowledge_facts,
            )
            if status == "supported":
                supported_count += 1
            elif status == "unverifiable":
                unverifiable_count += 1
            elif status == "contradicted":
                contradicted_count += 1
            elif status in {"weak", "contradicted"}:
                weak_count += 1

            if recommended_action == "accept":
                accepted_count += 1
            elif recommended_action == "revise":
                revision_count += 1
            elif recommended_action == "suppress":
                suppressed_count += 1
            reviews.append(
                {
                    "id": f"claim_support_{claim_id or len(reviews) + 1}",
                    "claim_id": claim_id,
                    "branch_id": claim.get("branch_id", ""),
                    "analysis_dimension_id": claim.get("analysis_dimension_id", ""),
                    "report_section_id": claim.get("report_section_id", ""),
                    "support_status": status,
                    "recommended_action": recommended_action,
                    "claim_risk_level": self._claim_risk_level(claim),
                    "evidence_ids": evidence_ids,
                    "knowledge_fact_ids": knowledge_fact_ids,
                    "unsupported_phrases": unsupported_phrases,
                    "required_follow_up_tasks": [],
                    "suggested_revision": suggested_revision,
                    "reviewer_notes": reviewer_notes,
                    "confidence": confidence,
                }
            )

        message = create_agent_message(
            sender="claim_support",
            receiver="writer",
            message_type="claim_support",
            payload={
                "review_count": len(reviews),
                "supported_count": supported_count,
                "weak_count": weak_count,
                "contradicted_count": contradicted_count,
                "unverifiable_count": unverifiable_count,
                "accepted_count": accepted_count,
                "revision_count": revision_count,
                "suppressed_count": suppressed_count,
                "reviews": reviews,
            },
            evidence_ids=[
                evidence_id
                for review in reviews
                for evidence_id in review.get("evidence_ids", [])
            ],
        )

        return {
            "claim_support_reviews": reviews,
            "messages": state.get("messages", []) + [message],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "claim_support",
                    "action": "review_claim_support",
                    "input": {
                        "analysis_message_id": analysis_message.get("id") if analysis_message else None,
                        "claim_count": len(claims),
                        "evidence_count": len(evidence_by_id),
                        "knowledge_fact_count": len(knowledge_fact_by_id),
                    },
                    "output": {
                        "review_count": len(reviews),
                        "supported_count": supported_count,
                        "weak_count": weak_count,
                        "contradicted_count": contradicted_count,
                        "unverifiable_count": unverifiable_count,
                        "accepted_count": accepted_count,
                        "revision_count": revision_count,
                        "suppressed_count": suppressed_count,
                    },
                }
            ],
        }

    def _review_claim_support(
        self,
        claim: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        knowledge_facts: list[dict[str, Any]],
    ) -> tuple[str, str, list[str], str, str, float]:
        claim_text = str(claim.get("claim", ""))
        claim_risk_level = self._claim_risk_level(claim)
        try:
            base_score = float(claim.get("confidence", 0.5))
        except (TypeError, ValueError):
            base_score = 0.5
        if not evidence_items:
            return (
                "unverifiable",
                "evidence_gap",
                ["missing evidence ids"],
                "",
                "Claim has no traceable evidence bindings.",
                round(min(1.0, max(0.0, base_score * 0.6)), 2),
            )

        alignment_issue = self._alignment_issue(claim, evidence_items, knowledge_facts)
        if alignment_issue:
            return (
                "contradicted",
                "suppress",
                [alignment_issue],
                "",
                "Claim bindings do not align with the cited evidence or facts.",
                round(max(0.0, min(1.0, base_score * 0.5)), 2),
            )

        context_text = self._support_context(evidence_items, knowledge_facts)
        claim_tokens = self._support_terms(claim_text)
        context_tokens = set(self._support_terms(context_text))
        overlap = [token for token in claim_tokens if token in context_tokens]
        unsupported = [token for token in claim_tokens if token not in context_tokens][:6]
        overclaim_terms = self._overclaim_terms(claim_text)
        suggested_revision = self._suggested_revision(
            claim,
            evidence_items,
            knowledge_facts,
        )

        if overclaim_terms and not self._overclaim_supported(overclaim_terms, context_text):
            return (
                "weak",
                "revise",
                overclaim_terms[:4],
                suggested_revision,
                "Claim uses comparative or superiority language that the bound evidence does not directly support.",
                round(max(0.0, min(1.0, base_score * 0.75)), 2),
            )

        if not claim.get("knowledge_fact_ids"):
            if claim_risk_level == "high":
                return (
                    "unverifiable",
                    "evidence_gap",
                    unsupported or claim_tokens[:4],
                    suggested_revision,
                    "High-risk claim is bound to evidence snippets but not to structured KnowledgeFact records.",
                    round(max(0.0, min(1.0, base_score * 0.68)), 2),
                )
            return (
                "weak",
                "revise",
                unsupported or claim_tokens[:4],
                suggested_revision,
                "Claim is bound to evidence but not to structured KnowledgeFact records.",
                round(max(0.0, min(1.0, base_score * 0.82)), 2),
            )

        if overlap:
            return (
                "supported",
                "accept",
                [],
                "",
                "Claim text is anchored in the accepted evidence snippets.",
                round(min(1.0, max(0.0, base_score)), 2),
            )

        if self._context_has_uncertainty(context_text):
            return (
                "weak",
                "revise",
                unsupported or claim_tokens[:4],
                suggested_revision,
                "Evidence exists but does not directly substantiate the claim wording.",
                round(max(0.0, min(1.0, base_score * 0.75)), 2),
            )

        return (
            "weak",
            "revise",
            unsupported or claim_tokens[:4],
            suggested_revision,
            "Evidence is traceable but the claim should be tightened to match cited facts.",
            round(max(0.0, min(1.0, base_score * 0.8)), 2),
            )

    def _support_terms(self, text: str) -> list[str]:
        normalized = text.lower()
        stopwords = {
            "with",
            "from",
            "that",
            "this",
            "have",
            "has",
            "were",
            "been",
            "evidence",
            "including",
            "public",
            "quality",
            "reviewed",
            "signal",
            "signals",
            "contains",
            "multiple",
            "source",
            "sources",
            "shows",
            "indicates",
        }
        terms = [
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) > 3 and token not in stopwords
        ]
        for segment in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(segment) <= 4:
                terms.append(segment)
            terms.extend(
                segment[index : index + 2]
                for index in range(max(0, len(segment) - 1))
            )
        return list(dict.fromkeys(terms))

    def _support_context(
        self,
        evidence_items: list[dict[str, Any]],
        knowledge_facts: list[dict[str, Any]],
    ) -> str:
        parts = []
        for fact in knowledge_facts:
            parts.extend(
                [
                    fact.get("statement", ""),
                    fact.get("object", ""),
                    " ".join(str(value) for value in (fact.get("value", {}) or {}).values()),
                ]
            )
        for evidence in evidence_items:
            parts.extend(
                [
                    evidence.get("title", ""),
                    evidence.get("excerpt", ""),
                    evidence.get("url", ""),
                ]
            )
        return " ".join(str(part or "") for part in parts).lower()

    def _alignment_issue(
        self,
        claim: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        knowledge_facts: list[dict[str, Any]],
    ) -> str:
        claim_competitors = [
            str(competitor)
            for competitor in claim.get("competitors", [])
            if str(competitor or "").strip()
        ]
        evidence_competitors = [
            str(evidence.get("competitor", ""))
            for evidence in evidence_items
            if str(evidence.get("competitor", "")).strip()
        ]
        if claim_competitors and evidence_competitors and not any(
            self._competitor_matches(claim_competitor, evidence_competitor)
            for claim_competitor in claim_competitors
            for evidence_competitor in evidence_competitors
        ):
            return "competitor_mismatch"

        claim_dimension = str(claim.get("analysis_dimension_id", "") or "")
        bound_dimensions = [
            str(item.get("analysis_dimension_id", "") or "")
            for item in [*evidence_items, *knowledge_facts]
            if str(item.get("analysis_dimension_id", "") or "").strip()
        ]
        if claim_dimension and bound_dimensions and claim_dimension not in bound_dimensions:
            return "dimension_mismatch"
        return ""

    def _competitor_matches(self, expected: str, observed: str) -> bool:
        left = expected.strip().lower()
        right = observed.strip().lower()
        return bool(left and right and (left == right or left in right or right in left))

    def _overclaim_terms(self, claim_text: str) -> list[str]:
        normalized = claim_text.lower()
        keywords = [
            "best",
            "leading",
            "leader",
            "dominant",
            "strongest",
            "outperform",
            "outperforms",
            "superior",
            "most advanced",
            "significant advantage",
            "领先",
            "最佳",
            "最强",
            "显著优势",
            "绝对优势",
        ]
        return [keyword for keyword in keywords if keyword in normalized]

    def _overclaim_supported(self, overclaim_terms: list[str], context_text: str) -> bool:
        normalized = context_text.lower()
        return any(term in normalized for term in overclaim_terms)

    def _context_has_uncertainty(self, context_text: str) -> bool:
        return any(
            keyword in context_text
            for keyword in [
                "no ",
                "not ",
                "lack",
                "missing",
                "insufficient",
                "unclear",
                "没有",
                "缺少",
                "不足",
                "不明确",
                "无法确认",
            ]
        )

    def _suggested_revision(
        self,
        claim: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        knowledge_facts: list[dict[str, Any]],
    ) -> str:
        competitor = (
            (claim.get("competitors") or [""])[0]
            or "the target competitor"
        )
        dimension = str(claim.get("analysis_dimension_id", "") or "the reviewed dimension")
        source_text = ""
        for fact in knowledge_facts:
            source_text = str(fact.get("object") or fact.get("statement") or "").strip()
            if source_text:
                break
        if not source_text:
            for evidence in evidence_items:
                source_text = str(evidence.get("excerpt") or evidence.get("title") or "").strip()
                if source_text:
                    break
        source_text = " ".join(source_text.split())[:220]
        if not source_text:
            return ""
        return f"{competitor} {dimension}: public evidence indicates {source_text}."

    def _claim_risk_level(self, claim: dict[str, Any]) -> str:
        risk_level = str(claim.get("claim_risk_level") or "").lower()
        if risk_level in {"low", "medium", "high"}:
            return risk_level
        text = " ".join(
            [
                str(claim.get("claim_type", "")),
                str(claim.get("analysis_dimension_id", "")),
                str(claim.get("claim", "")),
            ]
        ).lower()
        high_risk_terms = {
            "pricing",
            "price",
            "billing",
            "financial",
            "compliance",
            "security",
            "privacy",
            "regulator",
            "incident",
            "complaint",
            "outperform",
            "superior",
            "leading",
            "strongest",
            "cheaper",
            "定价",
            "价格",
            "合规",
            "安全",
            "隐私",
            "监管",
            "领先",
            "最强",
        }
        if any(term in text for term in high_risk_terms):
            return "high"
        low_risk_terms = {"profile", "identity", "official", "基础信息", "官网"}
        if any(term in text for term in low_risk_terms):
            return "low"
        return "medium"
