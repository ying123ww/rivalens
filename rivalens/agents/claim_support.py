"""Claim support review for traceable competitor analysis."""

from __future__ import annotations

import re
from typing import Any

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.agents.specificity import (
    combined_specificity_text,
    extract_specificity_hints,
    is_generic_specificity_claim,
    missing_specificity_hints,
)
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
                "suppress",
                ["missing evidence ids"],
                "",
                "Claim has no traceable evidence bindings and is suppressed at the claim gate.",
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
        pricing_detail_issue = self._pricing_detail_issue(
            claim_text,
            context_text,
        )
        if pricing_detail_issue:
            return (
                "weak",
                "revise",
                pricing_detail_issue[:4],
                suggested_revision,
                "Pricing claim omits concrete price or plan details present in the bound evidence.",
                round(max(0.0, min(1.0, base_score * 0.78)), 2),
            )

        specificity_issue = self._specificity_detail_issue(
            claim_text,
            evidence_items,
            knowledge_facts,
        )
        if specificity_issue:
            return (
                "weak",
                "revise",
                specificity_issue[:4],
                suggested_revision,
                "Claim omits concrete modules, metrics, reports, or scenarios present in the bound evidence.",
                round(max(0.0, min(1.0, base_score * 0.8)), 2),
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
                    "weak",
                    "revise",
                    unsupported or claim_tokens[:4],
                    suggested_revision,
                    "High-risk claim should be tightened to the cited evidence wording; claim support does not trigger collection.",
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
            snippet_text = self._evidence_snippet_text(evidence)
            parts.extend(
                [
                    evidence.get("title", ""),
                    snippet_text,
                    evidence.get("excerpt", ""),
                    evidence.get("url", ""),
                ]
            )
        return " ".join(str(part or "") for part in parts)

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
        normalized = context_text.lower()
        return any(
            keyword in normalized
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
                source_text = (
                    self._evidence_snippet_text(evidence)
                    or str(evidence.get("excerpt") or evidence.get("title") or "")
                ).strip()
                if source_text:
                    break
        source_text = " ".join(source_text.split())[:220]
        if not source_text:
            return ""
        pricing_details = self._pricing_details(source_text)
        if pricing_details:
            return (
                f"{competitor} {dimension}: public evidence reports "
                f"{'; '.join(pricing_details[:4])}."
            )
        specificity_hints = extract_specificity_hints(
            combined_specificity_text(claim, evidence_items, knowledge_facts),
        )
        if specificity_hints:
            return (
                f"{competitor} {dimension}: public evidence indicates "
                f"{source_text}; concrete details include "
                f"{'; '.join(specificity_hints[:5])}."
            )[:520]
        return f"{competitor} {dimension}: public evidence indicates {source_text}."

    def _pricing_detail_issue(
        self,
        claim_text: str,
        context_text: str,
    ) -> list[str]:
        lowered_claim = claim_text.lower()
        if not any(
            term in lowered_claim
            for term in (
                "pricing",
                "price",
                "billing",
                "定价",
                "价格",
                "收费",
                "计费",
                "运行额度",
                "额度",
                "消耗规则",
                "调用次数",
                "点数",
                "算粒",
            )
        ):
            return []

        details = self._pricing_details(context_text)
        if not details:
            return []
        if self._has_pricing_detail(claim_text) and not self._generic_pricing_claim(
            claim_text,
        ):
            return []
        return details

    def _specificity_detail_issue(
        self,
        claim_text: str,
        evidence_items: list[dict[str, Any]],
        knowledge_facts: list[dict[str, Any]],
    ) -> list[str]:
        context_text = combined_specificity_text(
            {"claim": claim_text},
            evidence_items,
            knowledge_facts,
        )
        if (
            self._billing_usage_details(claim_text, [])
            and self._billing_usage_details(context_text, [])
        ):
            return []
        context_hints = extract_specificity_hints(context_text)
        if len(context_hints) < 2:
            return []
        missing_hints = missing_specificity_hints(claim_text, context_hints)
        if len(missing_hints) < 2:
            return []
        if not is_generic_specificity_claim(claim_text):
            return []
        return missing_hints

    def _generic_pricing_claim(self, claim_text: str) -> bool:
        lowered = claim_text.lower()
        return any(
            phrase in lowered
            for phrase in (
                "multiple pricing signals",
                "pricing signals around",
                "public pricing-model signals",
                "多梯度付费",
                "付费套餐布局",
                "定价信号",
            )
        )

    def _has_pricing_detail(self, text: str) -> bool:
        if not text:
            return False
        return bool(
            re.search(r"[$¥€£]\s?\d", text)
            or re.search(r"\d+(?:[.,]\d+)?\s*元", text)
            or re.search(
                r"\d+(?:[.,]\d+)?\s*(?:运行额度|额度|点数|算粒|次\s*AI\s*调用|次调用|次)",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(r"\bfree(?:\s+(?:plan|tier|version))?\b", text.lower())
            or any(
                term in text
                for term in (
                    "免费版",
                    "免费套餐",
                    "联系销售",
                    "定制报价",
                    "计费单元",
                    "固定消耗",
                    "基础运行",
                    "模型调用",
                    "运行额度",
                )
            )
        )

    def _pricing_details(self, text: str) -> list[str]:
        if not text:
            return []
        details: list[str] = []
        patterns = [
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{1,24})\s+pricing is\s+(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:人|用户|user|seat)?\s*/?\s*(?:月|年|month|mo|year|yr))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{0,24}(?:版|套餐|计划|plan|tier)?)\s*(?P<price>[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:人|用户|user|seat)?\s*/?\s*(?:月|年|month|mo|year|yr))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{0,24}(?:版|套餐|计划|plan|tier)?)\s*(?:定价为|价格为|收费为|每人每月)\s*(?P<price>\d+(?:[.,]\d+)?\s*元(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?)",
            r"(?P<plan>[\u4e00-\u9fffA-Za-z0-9+ -]{0,24}(?:版|套餐|计划|plan|tier)?)\s*(?P<price>\d+(?:[.,]\d+)?\s*元(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                detail = self._pricing_detail_from_match(match)
                if detail and detail not in details:
                    details.append(detail)
        details.extend(self._billing_usage_details(text, details))
        if re.search(r"\bfree(?:\s+(?:plan|tier|version))?\b", text.lower()) or any(
            term in text for term in ("免费版", "免费套餐", "免费计划")
        ):
            free_detail = "free tier available"
            if free_detail not in details:
                details.append(free_detail)
        return details[:8]

    def _billing_usage_details(self, text: str, existing: list[str]) -> list[str]:
        details: list[str] = []
        billing_patterns = [
            (
                r"采用[「\"]?(?P<unit>[^」\"，。；;]{2,24})[」\"]?作为计费单元",
                lambda match: f"计费单元: {match.group('unit')}",
            ),
            (
                r"赠送\s*(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>运行额度|额度|点数|算粒)",
                lambda match: f"赠送 {match.group('amount')} {match.group('unit')}",
            ),
            (
                r"固定消耗\s*(?P<amount>\d+(?:[.,]\d+)?)\s*(?:个)?\s*(?P<unit>运行额度|额度|点数|算粒)",
                lambda match: f"固定消耗 {match.group('amount')} {match.group('unit')}",
            ),
            (
                r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>运行额度|额度|点数|算粒|次\s*AI\s*调用|次调用)",
                lambda match: f"{match.group('amount')} {match.group('unit')}",
            ),
            (
                r"运行额度由[「\"]?基础运行[」\"]?和[「\"]?模型调用[」\"]?两部分组成",
                lambda match: "运行额度由基础运行和模型调用两部分组成",
            ),
        ]
        seen = set(existing)
        for pattern, formatter in billing_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                detail = " ".join(formatter(match).split())
                if detail and detail not in seen:
                    details.append(detail)
                    seen.add(detail)
        return details

    def _pricing_detail_from_match(self, match: re.Match[str]) -> str:
        plan = " ".join((match.group("plan") or "").split()).strip(" ：:-")
        plan = self._clean_pricing_plan(plan)
        price = " ".join((match.group("price") or "").split())
        if not price:
            return ""
        if not self._valid_pricing_plan(plan):
            return ""
        if plan:
            return f"{plan} {price}"
        return price

    def _clean_pricing_plan(self, value: str) -> str:
        plan = " ".join(str(value or "").split()).strip(" ：:-")
        if " " in plan:
            plan = plan.split()[-1]
        if (
            plan
            and re.fullmatch(r"[\u4e00-\u9fff]{1,8}", plan)
            and not plan.endswith(("版", "套餐", "计划"))
        ):
            plan = f"{plan}版"
        return plan

    def _valid_pricing_plan(self, plan: str) -> bool:
        if not plan:
            return True
        return plan.lower() not in {
            "at",
            "costs",
            "from",
            "is",
            "plan",
            "priced",
            "starts",
        }

    def _evidence_snippet_text(self, evidence: dict[str, Any]) -> str:
        snippets = evidence.get("evidence_snippets", []) or []
        return " ".join(
            str(snippet.get("text", "") or "").strip()
            for snippet in snippets[:4]
            if str(snippet.get("text", "") or "").strip()
        )

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
