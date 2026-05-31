"""Shared text repair and quality checks for Rivalens pipeline inputs."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


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
