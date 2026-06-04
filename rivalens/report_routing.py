"""Task-level dynamic report-section routing."""

from typing import Any


def report_targets_for_dimension(
    dimension_id: str,
    *,
    name: str = "",
    description: str = "",
    source_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    section_id = _section_id(dimension_id or name)
    label = name or dimension_id or "动态分析维度"
    return [
        {
            "section_id": section_id,
            "role": "primary",
            "reason": f"{label} 是本次任务的动态分析章节。",
        }
    ]


def primary_report_section_id(dimension: dict[str, Any]) -> str:
    targets = dimension.get("report_targets", [])
    for target in targets:
        section_id = str(target.get("section_id", "") or "")
        if target.get("role") == "primary" and section_id:
            return _section_id(section_id)

    if targets:
        section_id = str(targets[0].get("section_id", "") or "")
        if section_id:
            return _section_id(section_id)

    return _section_id(
        str(
            dimension.get("id")
            or dimension.get("analysis_dimension_id")
            or dimension.get("direction_id")
            or dimension.get("name")
            or "dynamic_analysis",
        )
    )


def _section_id(value: str) -> str:
    cleaned = "".join(
        character.lower() if character.isalnum() else "_"
        for character in str(value).strip()
    ).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or "dynamic_analysis"
