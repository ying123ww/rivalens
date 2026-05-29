"""Human-review views for industry direction templates."""

from pathlib import Path
from typing import Any

from rivalens.industry_templates import INDUSTRY_DIRECTION_TEMPLATES


REVIEW_COLUMNS = [
    "行业",
    "industry_id",
    "direction_id",
    "方向名称",
    "必选",
    "证据来源",
    "调研理由",
    "人工备注",
    "动作",
]


def build_direction_review_rows(
    templates: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (
        INDUSTRY_DIRECTION_TEMPLATES
    ),
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for template in templates:
        industry_id = str(template["industry_id"])
        industry_name = str(template["name"])
        for direction in template.get("directions", []):
            rows.append(
                {
                    "行业": industry_name,
                    "industry_name": industry_name,
                    "industry_id": industry_id,
                    "direction_id": str(direction["direction_id"]),
                    "方向名称": str(direction["name"]),
                    "必选": "是" if direction.get("required", True) else "否",
                    "required": "是" if direction.get("required", True) else "否",
                    "证据来源": ", ".join(direction.get("source_hints", [])),
                    "source_hints": ", ".join(direction.get("source_hints", [])),
                    "调研理由": str(direction.get("reason", "")),
                    "人工备注": "",
                    "动作": "",
                }
            )
    return rows


def render_direction_review_markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Industry Direction Review",
        "",
        "This file is generated from `rivalens/industry_templates/directions.py`.",
        "Edit the source template, then regenerate this review view.",
        "",
        f"Total directions: {len(rows)}",
        "",
        "| " + " | ".join(REVIEW_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in REVIEW_COLUMNS) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_escape_markdown_table(row.get(column, "")) for column in REVIEW_COLUMNS)
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def write_direction_review_markdown(path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_direction_review_markdown(build_direction_review_rows()),
        encoding="utf-8",
    )
    return output_path


def _escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    write_direction_review_markdown("docs/industry_directions_review.md")
