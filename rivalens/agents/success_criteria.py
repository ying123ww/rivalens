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


def normalize_success_criteria(
    criteria: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized = []
    for criterion in criteria or []:
        description = str(criterion.get("description", "")).strip()
        criterion_id = str(criterion.get("id", "")).strip()
        if not criterion_id or not description:
            continue
        normalized.append(
            {
                **criterion,
                "id": criterion_id,
                "description": description,
                "required_source_types": _string_list(
                    criterion.get("required_source_types", []),
                ),
                "target_source_types": _string_list(
                    criterion.get("target_source_types")
                    or criterion.get("required_source_types")
                    or [],
                ),
            }
        )
    return normalized


def evidence_matches_success_criterion(
    evidence: dict[str, Any],
    criterion: dict[str, Any],
    branch: dict[str, Any],
) -> bool:
    required_source_types = set(_string_list(criterion.get("required_source_types", [])))
    source_type = str(evidence.get("source_type") or "")
    if required_source_types and source_type in required_source_types:
        return True

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
    return {
        term
        for term in _terms(text)
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
    return terms


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
