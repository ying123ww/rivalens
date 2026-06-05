"""Helpers for matching evidence against collection success criteria."""

from __future__ import annotations

import re
from typing import Any


_STOPWORDS = {
    "about",
    "aligned",
    "and",
    "any",
    "are",
    "backed",
    "collect",
    "competitor",
    "criteria",
    "criterion",
    "does",
    "evidence",
    "find",
    "for",
    "from",
    "goal",
    "how",
    "is",
    "must",
    "of",
    "or",
    "original",
    "public",
    "query",
    "request",
    "research",
    "source",
    "sources",
    "the",
    "this",
    "to",
    "what",
    "when",
    "which",
    "with",
}

_CJK_TERM_ALIASES = {
    "价格": {"price", "pricing"},
    "定价": {"price", "pricing"},
    "套餐": {"plan", "plans", "package", "packaging"},
    "计费": {"billing"},
    "收费": {"fee", "pricing"},
    "变现": {"monetization"},
    "商业模式": {"business", "model", "monetization"},
    "企业": {"enterprise"},
    "免费": {"free"},
    "功能": {"feature", "features"},
    "能力": {"capability", "capabilities"},
    "产品": {"product"},
    "用户": {"user", "users"},
    "客户": {"customer", "customers"},
    "画像": {"persona", "segment"},
    "评价": {"review", "reviews"},
    "口碑": {"review", "sentiment"},
    "案例": {"case", "customer"},
    "安全": {"security"},
    "合规": {"compliance"},
    "隐私": {"privacy"},
    "信任": {"trust"},
    "风险": {"risk"},
    "集成": {"integration", "integrations"},
    "接口": {"api"},
    "文档": {"docs", "documentation"},
    "开发": {"developer", "api"},
    "市场": {"market"},
    "增长": {"growth"},
    "融资": {"funding"},
    "区域": {"region"},
    "定位": {"positioning"},
    "战略": {"strategy"},
    "差异": {"differentiation"},
    "优势": {"advantage"},
    "流程": {"workflow", "process"},
    "工作流": {"workflow"},
}


def normalize_success_criteria(
    criteria: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized = []
    for criterion in criteria or []:
        description = str(criterion.get("description", "")).strip()
        criterion_id = str(criterion.get("id", "")).strip()
        if not criterion_id or not description:
            continue
        normalized_criterion = dict(criterion)
        normalized_criterion.pop("required_source_types", None)
        normalized_criterion.pop("target_source_types", None)
        normalized.append(
            {
                **normalized_criterion,
                "id": criterion_id,
                "description": description,
            }
        )
    return normalized


def evidence_matches_success_criterion(
    evidence: dict[str, Any],
    criterion: dict[str, Any],
    branch: dict[str, Any],
) -> bool:
    meaningful_terms = _criterion_terms(criterion, branch)
    if not meaningful_terms:
        return False

    evidence_terms = _terms(_evidence_text(evidence))
    return bool(meaningful_terms.intersection(evidence_terms))


def matched_success_criterion_ids(
    evidence: dict[str, Any],
    criteria: list[dict[str, Any]],
    branch: dict[str, Any],
) -> list[str]:
    return [
        criterion["id"]
        for criterion in normalize_success_criteria(criteria)
        if evidence_matches_success_criterion(evidence, criterion, branch)
    ]


def success_criterion_terms(
    criterion: dict[str, Any],
    branch: dict[str, Any],
) -> set[str]:
    return _criterion_terms(criterion, branch)


def text_terms(text: str) -> set[str]:
    return _terms(text)


def _criterion_terms(
    criterion: dict[str, Any],
    branch: dict[str, Any],
) -> set[str]:
    competitor_terms = _terms(str(branch.get("competitor", "")))
    parts = [
        criterion.get("description", ""),
        criterion.get("objective", ""),
        " ".join(_string_list(criterion.get("keywords", []))),
    ]
    text = " ".join(str(value or "") for value in parts)
    criterion_terms = {
        term
        for term in _terms(text)
        if term not in competitor_terms and term not in _STOPWORDS
    }
    if criterion_terms:
        return criterion_terms

    branch_text = " ".join(
        str(value or "")
        for value in [
            branch.get("dimension_id", ""),
            branch.get("dimension_name", ""),
            branch.get("topic", ""),
        ]
    )
    return {
        term
        for term in _terms(branch_text)
        if term not in competitor_terms and term not in _STOPWORDS
    }


def _evidence_text(evidence: dict[str, Any]) -> str:
    return " ".join(
        str(evidence.get(field) or "")
        for field in ("title", "excerpt", "summary", "url", "source_type")
    )


def _terms(text: str) -> set[str]:
    normalized = str(text or "").lower()
    terms = {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 2 and token not in _STOPWORDS
    }
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        terms.update(
            segment[index : index + 2]
            for index in range(0, max(1, len(segment) - 1))
        )
    for phrase, aliases in _CJK_TERM_ALIASES.items():
        if phrase in normalized:
            terms.update(aliases)
    return terms


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
