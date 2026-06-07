"""Shared text repair and quality checks for Rivalens pipeline inputs."""

from __future__ import annotations

from html import unescape
import re
import unicodedata
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - dependency is optional at runtime.
    BeautifulSoup = None


HTML_TAG_RE = re.compile(
    r"<(?:!doctype|html|head|body|main|article|section|div|p|script|style|nav|footer|header)\b",
    re.I,
)


def clean_text(text: Any) -> str:
    repaired = repair_utf8_mojibake(str(text or ""))
    return "".join(
        char
        for char in repaired
        if unicodedata.category(char) != "Cc" or char in "\t\n\r"
    )


def repair_utf8_mojibake(text: str) -> str:
    if not looks_like_utf8_mojibake(text):
        return text
    try:
        raw_bytes = bytearray()
        for char in text:
            try:
                raw_bytes.extend(char.encode("latin-1"))
            except UnicodeEncodeError:
                raw_bytes.extend(char.encode("cp1252"))
        repaired = raw_bytes.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if looks_like_utf8_mojibake(repaired):
        return text
    return repaired


def looks_like_utf8_mojibake(text: str) -> bool:
    if any("\u0080" <= char <= "\u009f" for char in text):
        return True
    marker_count = sum(text.count(marker) for marker in ("æ", "å", "é", "è", "ç", "ä"))
    return marker_count >= 2


def is_low_quality_text(text: Any) -> bool:
    value = clean_text(text)
    compact = "".join(value.split())
    if not compact:
        return True
    if looks_like_utf8_mojibake(value):
        return True

    replacement_count = compact.count("\ufffd")
    if replacement_count >= 3 or replacement_count / max(1, len(compact)) >= 0.02:
        return True

    readable_chars = sum(
        1
        for char in compact
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )
    symbol_noise_chars = sum(
        1
        for char in compact
        if unicodedata.category(char).startswith(("S", "C"))
        and char not in {"。", "，", "；", "：", "！", "？"}
    )
    if len(compact) >= 20 and readable_chars / len(compact) < 0.25:
        return True
    if len(compact) >= 20 and symbol_noise_chars / len(compact) > 0.35:
        return True

    long_noise_runs = re.search(r"[\ufffd\u0000-\u001f\u007f-\u009f]{3,}", value)
    return bool(long_noise_runs)


def clean_source_text(text: Any) -> str:
    """Clean scraped page content before it becomes an EvidenceItem excerpt."""
    value = unescape(clean_text(text))
    if not value:
        return ""
    if HTML_TAG_RE.search(value):
        value = html_to_visible_text(value)
    value = remove_source_boilerplate(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s*\n+\s*", "\n", value)
    return " ".join(value.split()).strip()


def html_to_visible_text(html: str) -> str:
    if BeautifulSoup is None:
        return re.sub(r"<[^>]+>", " ", html)

    soup = BeautifulSoup(html, "lxml")
    for node in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "header",
            "footer",
            "form",
            "button",
        ]
    ):
        node.decompose()
    return soup.get_text("\n")


def remove_source_boilerplate(text: str) -> str:
    value = re.sub(
        r"以下内容由\s*AI\s*匹配目标关键词[^。.!?！？\n]*(?:[。.!?！？])?",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\bNaN(?:\s*[-/]\s*NaN){1,}\b", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)

    lines = []
    for line in value.splitlines():
        normalized = " ".join(line.split()).strip()
        if not normalized:
            continue
        if is_source_boilerplate_line(normalized):
            continue
        lines.append(normalized)
    return "\n".join(lines)


def is_source_boilerplate_line(line: str) -> bool:
    normalized = line.strip(" -_|:：•·")
    lower = normalized.lower()
    compact = re.sub(r"\s+", "", lower)
    if "youneedtoenablejavascripttorunthisapp" in compact:
        return True
    if re.fullmatch(r"(?:nan[-/\s]*){2,}nan", lower):
        return True
    if "以下内容由" in normalized and "AI" in normalized and "目标关键词" in normalized:
        return True

    exact_noise = {
        "登录",
        "注册",
        "下载",
        "免费试用",
        "联系我们",
        "联系销售",
        "立即咨询",
        "开始使用",
        "立即体验",
        "热门推荐",
        "案例与方案",
        "产品功能",
        "本文目录",
        "目录",
        "相关推荐",
        "相关产品",
        "login",
        "log in",
        "sign up",
        "download",
        "free trial",
        "contact us",
        "contact sales",
        "get started",
        "table of contents",
        "related articles",
        "recommended",
        "popular",
        "resources",
        "product features",
    }
    if lower in exact_noise or normalized in exact_noise:
        return True

    nav_terms = [
        "登录",
        "注册",
        "下载",
        "免费试用",
        "联系我们",
        "联系销售",
        "login",
        "sign up",
        "download",
        "free trial",
        "contact us",
        "contact sales",
    ]
    page_terms = [
        "热门推荐",
        "案例与方案",
        "产品功能",
        "本文目录",
        "目录",
        "相关推荐",
        "related articles",
        "table of contents",
        "recommended",
        "resources",
    ]
    noise_hits = sum(
        term in normalized or term in lower
        for term in nav_terms + page_terms
    )
    if (
        len(normalized) <= 80
        and noise_hits >= 3
        and not has_source_concrete_signal(normalized)
    ):
        return True
    return False


def has_source_concrete_signal(text: str) -> bool:
    value = str(text or "")
    lower = value.lower()
    if re.search(
        r"[$¥€£]\s?\d|\d+(?:[.,]\d+)?\s*(?:%|元|人|用户|月|年|gb|tb)",
        value,
    ):
        return True
    if re.search(
        r"\b(api|sdk|sso|iso\s?\d+|soc\s?2|gdpr|hipaa|enterprise|pro)\b",
        lower,
    ):
        return True
    if any(
        term in value
        for term in [
            "支持",
            "提供",
            "采用",
            "包括",
            "集成",
            "认证",
            "定价",
            "价格",
            "版本",
            "套餐",
            "计费",
            "额度",
            "权限",
        ]
    ):
        return True
    return any(
        term in lower
        for term in [
            "supports",
            "offers",
            "provides",
            "includes",
            "integrates",
            "certified",
            "pricing",
            "billing",
            "workflow",
            "automation",
            "security",
            "compliance",
        ]
    )
