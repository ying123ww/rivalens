"""Claim support review for traceable competitor analysis."""

from __future__ import annotations

import os
import re
from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import ClaimSupportReview, CompetitorAnalysisState


class ClaimSupportReviewer:
    """Check whether claims are sufficiently supported by accepted evidence."""

    def __init__(
        self,
        enable_verification: bool | None = None,
        max_verification_tasks: int | None = None,
    ) -> None:
        self.enable_verification = (
            enable_verification
            if enable_verification is not None
            else self._env_flag("RIVALENS_ENABLE_CLAIM_VERIFICATION", False)
        )
        self.max_verification_tasks = (
            max_verification_tasks
            if max_verification_tasks is not None
            else self._env_int("RIVALENS_MAX_CLAIM_VERIFICATION_TASKS", 8, minimum=1)
        )

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
        verification_enabled = self.enable_verification and verification_rounds == 0
        verification_task_candidates: list[dict[str, Any]] = []

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
                allow_verification=verification_enabled,
            )
            verification_task_candidates.extend(follow_up_tasks)
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

        verification_task_queue = self._merge_prioritized_follow_up_tasks(
            verification_task_candidates,
        )
        tasks_by_claim_id = {
            claim_id: task
            for task in verification_task_queue
            for claim_id in task.get("claim_ids", [])
        }
        for review in reviews:
            claim_task = tasks_by_claim_id.get(review.get("claim_id", ""))
            review["required_follow_up_tasks"] = [claim_task] if claim_task else []

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
                        "verification_enabled": verification_enabled,
                    },
                    "output": {
                        "review_count": len(reviews),
                        "supported_count": supported_count,
                        "weak_count": weak_count,
                        "verification_task_count": len(verification_task_queue),
                        "verification_task_candidate_count": len(verification_task_candidates),
                        "max_verification_tasks": self.max_verification_tasks,
                    },
                }
            ],
        }

    def _env_flag(self, env_name: str, default: bool) -> bool:
        raw_value = os.getenv(env_name)
        if raw_value in (None, ""):
            return default
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(self, env_name: str, default: int, minimum: int = 0) -> int:
        raw_value = os.getenv(env_name)
        if raw_value in (None, ""):
            return default
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed)

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
        claim_tokens = self._support_terms(claim_text)
        overlap = [token for token in claim_tokens if token in evidence_text]

        if overlap:
            return (
                "supported",
                [],
                "Claim text is anchored in the accepted evidence snippets.",
                round(min(1.0, max(0.0, base_score)), 2),
            )

        if any(
            keyword in evidence_text
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
        ):
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
            "public",
            "quality",
            "reviewed",
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
                "success_criteria": [
                    {
                        "id": "claim_verification",
                        "description": f"Verify claim: {claim_text[:120]}",
                        "target_source_types": target_source_types,
                        "required_source_types": target_source_types,
                        "kind": "claim_verification",
                    }
                ],
                "generated_from_gap": f"verification:{claim.get('id', '')}",
                "decision_action": "claim_verification",
                "decision_subtype": "evidence_check",
                "reason": "Claim support review marked this claim as weak or unverifiable.",
                "search_stage": "verification",
                "competitor": competitor,
                "dimension_id": dimension,
                "parent_branch_id": claim.get("branch_id", ""),
                "claim_ids": [claim.get("id", "")],
                "support_statuses": [support_status],
                "unsupported_phrases": unsupported_phrases,
                "priority": self._verification_priority(support_status),
            }
        ]

    def _merge_prioritized_follow_up_tasks(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for task in tasks:
            source_type = self._primary_source_type(task)
            key = (
                str(task.get("competitor", "")),
                str(task.get("dimension_id", "")),
                source_type,
            )
            if key not in grouped:
                grouped[key] = self._new_merged_task(task, source_type)
            else:
                self._add_to_merged_task(grouped[key], task)

        ranked = sorted(
            grouped.values(),
            key=lambda task: (
                int(task.get("priority", 99)),
                -len(task.get("claim_ids", [])),
                str(task.get("competitor", "")),
                str(task.get("dimension_id", "")),
            ),
        )
        return ranked[: self.max_verification_tasks]

    def _new_merged_task(self, task: dict[str, Any], source_type: str) -> dict[str, Any]:
        merged = dict(task)
        claim_ids = [claim_id for claim_id in task.get("claim_ids", []) if claim_id]
        merged["claim_ids"] = claim_ids
        merged["support_statuses"] = list(task.get("support_statuses", []) or [])
        merged["unsupported_phrases"] = list(task.get("unsupported_phrases", []) or [])
        merged["target_source_types"] = list(
            dict.fromkeys([source_type] + list(task.get("target_source_types", []) or []))
        )
        merged["source_type"] = source_type
        merged["merged_claim_count"] = len(claim_ids)
        return merged

    def _add_to_merged_task(self, merged: dict[str, Any], task: dict[str, Any]) -> None:
        claim_ids = list(merged.get("claim_ids", []) or [])
        for claim_id in task.get("claim_ids", []) or []:
            if claim_id and claim_id not in claim_ids:
                claim_ids.append(claim_id)
        merged["claim_ids"] = claim_ids
        merged["merged_claim_count"] = len(claim_ids)

        merged["support_statuses"] = list(
            dict.fromkeys(
                list(merged.get("support_statuses", []) or [])
                + list(task.get("support_statuses", []) or [])
            )
        )
        merged["unsupported_phrases"] = list(
            dict.fromkeys(
                list(merged.get("unsupported_phrases", []) or [])
                + list(task.get("unsupported_phrases", []) or [])
            )
        )[:8]
        merged["target_source_types"] = list(
            dict.fromkeys(
                list(merged.get("target_source_types", []) or [])
                + list(task.get("target_source_types", []) or [])
            )
        )
        merged["priority"] = min(
            int(merged.get("priority", 99)),
            int(task.get("priority", 99)),
        )

        objectives = [str(merged.get("objective", "")), str(task.get("objective", ""))]
        queries = [str(merged.get("query", "")), str(task.get("query", ""))]
        merged["objective"] = self._merged_text("Verify grouped claims", objectives, limit=220)
        merged["query"] = self._merged_text(
            "Search for public evidence that directly supports or contradicts these grouped claims.",
            queries,
            limit=900,
        )
        merged["generated_from_gap"] = self._merged_gap_id(merged)
        merged["reason"] = "Claim support review grouped multiple weak claims for one verification collection."

    def _primary_source_type(self, task: dict[str, Any]) -> str:
        source_types = task.get("target_source_types", []) or []
        return str(source_types[0]) if source_types else "other"

    def _verification_priority(self, support_status: str) -> int:
        return {
            "contradicted": 0,
            "unverifiable": 1,
            "weak": 2,
        }.get(support_status, 9)

    def _merged_gap_id(self, task: dict[str, Any]) -> str:
        competitor = re.sub(r"[^a-zA-Z0-9]+", "_", str(task.get("competitor", "")).strip()).strip("_")
        dimension = re.sub(r"[^a-zA-Z0-9]+", "_", str(task.get("dimension_id", "")).strip()).strip("_")
        source_type = re.sub(r"[^a-zA-Z0-9]+", "_", str(task.get("source_type", "")).strip()).strip("_")
        parts = [part for part in [competitor, dimension, source_type] if part]
        return "verification_batch:" + ":".join(parts or ["claims"])

    def _merged_text(self, prefix: str, values: list[str], limit: int) -> str:
        deduped = [value for value in dict.fromkeys(values) if value]
        text = "\n\n".join([prefix, *deduped])
        return text[:limit]

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
