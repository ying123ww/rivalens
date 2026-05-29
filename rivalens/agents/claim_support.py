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
        reviews: list[ClaimSupportReview] = []
        supported_count = 0
        weak_count = 0
        verification_rounds = int(state.get("verification_rounds", 0) or 0)
        verification_task_queue: list[dict[str, Any]] = []

        for claim in claims:
            claim_id = claim.get("id", "")
            claim_text = str(claim.get("claim", ""))
            evidence_ids = [
                evidence_id
                for evidence_id in claim.get("evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
            evidence_items = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
            status, unsupported_phrases, reviewer_notes, confidence = self._support_status(
                claim_text,
                evidence_items,
                claim.get("confidence", 0.5),
            )
            if status == "supported":
                supported_count += 1
            elif status in {"weak", "contradicted"}:
                weak_count += 1

            follow_up_tasks = self._follow_up_tasks(
                claim,
                status,
                unsupported_phrases,
                evidence_items,
                allow_verification=verification_rounds == 0,
            )
            verification_task_queue.extend(follow_up_tasks)
            reviews.append(
                {
                    "id": f"claim_support_{claim_id or len(reviews) + 1}",
                    "claim_id": claim_id,
                    "branch_id": claim.get("branch_id", ""),
                    "dimension": claim.get("dimension", ""),
                    "support_status": status,
                    "evidence_ids": evidence_ids,
                    "unsupported_phrases": unsupported_phrases,
                    "required_follow_up_tasks": follow_up_tasks,
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
            "verification_task_queue": verification_task_queue,
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
                        "verification_rounds": verification_rounds,
                    },
                    "output": {
                        "review_count": len(reviews),
                        "supported_count": supported_count,
                        "weak_count": weak_count,
                        "verification_task_count": len(verification_task_queue),
                    },
                }
            ],
        }

    def _support_status(
        self,
        claim_text: str,
        evidence_items: list[dict[str, Any]],
        base_confidence: float,
    ) -> tuple[str, list[str], str, float]:
        try:
            base_score = float(base_confidence)
        except (TypeError, ValueError):
            base_score = 0.5
        if not evidence_items:
            return (
                "unverifiable",
                ["missing evidence ids"],
                "Claim has no traceable evidence bindings.",
                round(min(1.0, max(0.0, base_score * 0.6)), 2),
            )

        evidence_text = " ".join(
            " ".join(
                str(part)
                for part in [
                    evidence.get("title", ""),
                    evidence.get("excerpt", ""),
                    evidence.get("url", ""),
                ]
            )
            for evidence in evidence_items
        ).lower()
        claim_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", claim_text.lower())
            if len(token) > 3 and token not in {"with", "from", "that", "this", "have", "has", "were", "been", "evidence", "public"}
        ]
        overlap = [token for token in claim_tokens if token in evidence_text]

        if overlap:
            return (
                "supported",
                [],
                "Claim text is anchored in the accepted evidence snippets.",
                round(min(1.0, max(0.0, base_score)), 2),
            )

        if any(keyword in evidence_text for keyword in ["no ", "not ", "lack", "missing", "insufficient", "unclear"]):
            return (
                "weak",
                claim_tokens[:3],
                "Evidence exists but does not directly substantiate the claim wording.",
                round(max(0.0, min(1.0, base_score * 0.75)), 2),
            )

        return (
            "weak",
            claim_tokens[:3],
            "Evidence is traceable but the claim needs a tighter verification query.",
            round(max(0.0, min(1.0, base_score * 0.8)), 2),
        )

    def _follow_up_tasks(
        self,
        claim: dict[str, Any],
        support_status: str,
        unsupported_phrases: list[str],
        evidence_items: list[dict[str, Any]],
        allow_verification: bool,
    ) -> list[dict[str, Any]]:
        if support_status == "supported" or not allow_verification:
            return []

        dimension = str(claim.get("dimension", "source_evidence"))
        claim_text = str(claim.get("claim", ""))
        competitors = claim.get("competitors", []) or []
        competitor = competitors[0] if competitors else ""
        query_focus = " ".join(
            token
            for token in unsupported_phrases[:3] + [dimension, claim_text[:120]]
            if token
        ).strip()
        if not query_focus:
            query_focus = claim_text[:120] or dimension

        target_source_types = self._target_source_types(dimension, evidence_items)
        return [
            {
                "objective": f"Verify claim: {claim_text[:120]}",
                "query": "\n".join(
                    [
                        query_focus,
                        f"Claim dimension: {dimension}",
                        "Search for public evidence that directly supports or contradicts the claim.",
                    ]
                ),
                "target_source_types": target_source_types,
                "generated_from_gap": f"verification:{claim.get('id', '')}",
                "decision_action": "claim_verification",
                "decision_subtype": "evidence_check",
                "reason": "Claim support review marked this claim as weak or unverifiable.",
                "search_stage": "verification",
                "competitor": competitor,
                "dimension_id": dimension,
                "parent_branch_id": claim.get("branch_id", ""),
            }
        ]

    def _target_source_types(
        self,
        dimension: str,
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        observed = [
            item.get("source_type", "other")
            for item in evidence_items
            if item.get("source_type")
        ]
        if dimension == "pricing_model":
            preferred = ["pricing_page", "official_site", "docs"]
        elif dimension == "user_personas":
            preferred = ["review", "official_site", "marketplace"]
        elif dimension in {"feature_tree", "core_feature"}:
            preferred = ["official_site", "docs", "marketplace"]
        else:
            preferred = ["official_site", "docs", "news"]
        return list(dict.fromkeys(preferred + observed[:2]))
