"""Helpers for preserving concrete evidence details in claims and reports."""

from __future__ import annotations

import re
from typing import Any


DETAIL_HINT_LIMIT = 8


def extract_specificity_hints(text: str, limit: int = DETAIL_HINT_LIMIT) -> list[str]:
    """Extract compact concrete details such as module names, metrics, reports, or certifications."""

    if not text:
        return []
    normalized = " ".join(str(text).split())
    candidates: list[str] = []

    patterns = [
        r"\d+(?:[.,]\d+)?\s*(?:运行额度|额度|点数|算粒|次\s*AI\s*调用|次调用|次)",
        r"(?:计费单元|基础运行|模型调用|运行额度|AI\s*运行调用|大模型调用)",
        r"(?:Gartner|Forrester|IDC|G2|艾瑞|易观|QuestMobile)?\s*《[^》]{2,48}》",
        r"[“\"]([^”\"]{2,48})[”\"]",
        r"\b(?:ISO|SOC|DSMM)\s*[A-Za-z0-9.-]{0,12}\b",
        r"\b(?:GDPR|CCPA|CSA|SLA|Gartner|Forrester|IDC|G2)\b",
        r"[$¥€£]\s?\d+(?:[.,]\d+)?(?:\s*/?\s*(?:人|用户|user|seat)?\s*/?\s*(?:月|年|month|mo|year|yr))?",
        r"\d+(?:[.,]\d+)?\s*元(?:\s*/?\s*(?:人|用户)?\s*/?\s*(?:月|年))?",
        r"\d+(?:[.,]\d+)?\s*%",
        r"\b20\d{2}(?:[-年./]\d{1,2}(?:[-月./]\d{1,2}日?)?)?\b",
        r"\bv?\d+(?:\.\d+){1,3}\b",
        r"\d+(?:[.,]\d+)?\s*(?:天|个|家|项|人|用户|席位|小时|分钟|GB|TB|次|万|亿|额度|点数|算粒)",
        r"[\u4e00-\u9fff]{1,10}[A-Za-z][A-Za-z0-9+._-]{1,24}",
        r"[A-Za-z]{2,}[A-Za-z0-9+._-]{0,24}[\u4e00-\u9fff]{1,10}",
        r"[\u4e00-\u9fffA-Za-z0-9+._-]{0,18}(?:飞书People|飞书项目|飞书云文档|飞书多维表格|飞书知识库|钉钉ONE|AI听记|AI助理|钉盘|服务窗)",
        r"[\u4e00-\u9fffA-Za-z0-9+._-]{2,24}(?:白皮书|指南|报告|认证|标准|SLA)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            value = match.group(1) if match.lastindex else match.group(0)
            _append_hint(candidates, value)

    for segment in re.findall(r"[\u4e00-\u9fffA-Za-z0-9+._-]{4,48}", normalized):
        _append_scenario_hints(candidates, segment)

    return candidates[:limit]


def missing_specificity_hints(text: str, hints: list[str], limit: int = 4) -> list[str]:
    """Return hints from evidence/facts that are absent from a claim or report cell."""

    normalized_text = _normalize_for_match(text)
    missing: list[str] = []
    for hint in hints:
        if _normalize_for_match(hint) not in normalized_text:
            missing.append(hint)
        if len(missing) >= limit:
            break
    return missing


def is_generic_specificity_claim(text: str) -> bool:
    """Detect claim wording that tends to hide concrete evidence details."""

    normalized = text.lower()
    generic_phrases = (
        "multiple signals",
        "multiple capability",
        "multiple features",
        "various capabilities",
        "broad capability",
        "capability matrix",
        "capability set",
        "product portfolio",
        "feature portfolio",
        "ecosystem layout",
        "public evidence contains",
        "相关信号",
        "多个信号",
        "多种信号",
        "多项信号",
        "多种能力",
        "多项能力",
        "多个能力",
        "能力矩阵",
        "能力体系",
        "能力布局",
        "功能矩阵",
        "功能体系",
        "产品矩阵",
        "产品组合",
        "场景覆盖",
        "体系化",
        "公开证据包含",
    )
    return any(phrase in normalized for phrase in generic_phrases)


def combined_specificity_text(
    claim: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    knowledge_facts: list[dict[str, Any]],
) -> str:
    """Build bounded detail text from a claim and its bound facts/evidence."""

    parts: list[str] = [
        str(claim.get("claim", "") or ""),
        str(claim.get("reasoning", "") or ""),
    ]
    for fact in knowledge_facts:
        parts.extend(
            [
                str(fact.get("subject", "") or ""),
                str(fact.get("predicate", "") or ""),
                str(fact.get("object", "") or ""),
                str(fact.get("statement", "") or ""),
                " ".join(str(value) for value in (fact.get("value", {}) or {}).values()),
            ]
        )
    for evidence in evidence_items:
        parts.extend(
            [
                str(evidence.get("title", "") or ""),
                _evidence_snippet_text(evidence),
                str(evidence.get("excerpt", "") or ""),
            ]
        )
    return " ".join(part for part in parts if part)


def _append_scenario_hints(candidates: list[str], segment: str) -> None:
    keywords = (
        "管理",
        "行业",
        "流程",
        "生命周期",
        "场景",
        "方案",
        "客户",
        "合同",
        "审批",
        "协同",
        "计费",
        "额度",
        "调用",
    )
    for keyword in keywords:
        start = 0
        while True:
            index = segment.find(keyword, start)
            if index < 0:
                break
            left = max(0, index - 8)
            right = min(len(segment), index + len(keyword) + 6)
            _append_hint(candidates, segment[left:right])
            start = index + len(keyword)


def _append_hint(candidates: list[str], value: str) -> None:
    hint = _clean_hint(value)
    if not hint:
        return
    if _low_value_hint(hint):
        return
    normalized_hint = _normalize_for_match(hint)
    for index, existing in enumerate(candidates):
        normalized_existing = _normalize_for_match(existing)
        if normalized_hint == normalized_existing or normalized_hint in normalized_existing:
            return
        if normalized_existing in normalized_hint:
            candidates[index] = hint
            return
    candidates.append(hint)


def _clean_hint(value: str) -> str:
    hint = " ".join(str(value or "").split()).strip(" ，,。.;；:：-—()（）[]【】")
    hint = re.sub(r"^(?:提供|支持|覆盖|包含|包括|推出|发布|显示|显示其)", "", hint)
    return hint.strip(" ，,。.;；:：-—()（）[]【】")[:64]


def _low_value_hint(hint: str) -> bool:
    if len(hint) < 2:
        return True
    lowered = hint.lower()
    low_value_terms = (
        "案例与方案",
        "产品功能",
        "合作与支持",
        "飞行社",
        "下载飞书",
        "免费试用",
        "登录",
        "博客中心",
        "联系我们",
        "联系销售",
        "手册精选",
    )
    if any(term in hint for term in low_value_terms):
        return True
    if "管理员" in hint and "权限" in hint and not re.search(r"\d", hint):
        return True
    if hint in {"飞书管理", "钉钉管理"}:
        return True
    if lowered in {
        "public evidence",
        "multiple signals",
        "feature",
        "features",
        "capability",
        "capabilities",
        "report",
        "guide",
    }:
        return True
    if re.fullmatch(r"\d+", hint):
        return True
    return False


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _evidence_snippet_text(evidence: dict[str, Any]) -> str:
    snippets = evidence.get("evidence_snippets", []) or []
    return " ".join(
        str(snippet.get("text", "") or "").strip()
        for snippet in snippets[:4]
        if str(snippet.get("text", "") or "").strip()
    )
