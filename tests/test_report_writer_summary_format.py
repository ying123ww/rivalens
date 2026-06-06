"""Report writer summary format contract tests."""

import json

from rivalens.agents.writing import ReportWriterAgent


def _fixed_summary() -> str:
    return """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1] | **W 劣势**<br>1. 公开证据不足。 |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[2] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[3] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][2] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][3] |
| W 劣势 | **WO 扭转型**<br>1. 公开证据不足，无法推演。 | **WT 防御型**<br>1. 公开证据不足，无法推演。 |

### 总结论述

现有公开证据显示，双方仍需围绕 AI 协同继续验证差异。[1][2]
""".strip()


def test_summary_prompt_contains_fixed_matrix_contract():
    prompt = ReportWriterAgent()._summary_prompt()

    assert "|  | 正向因素 | 负向因素 |" in prompt
    assert "| 内部 | **S 优势**<br>1. ...<br>2. ...<br>3. ... |" in prompt
    assert "|  | O 机会 | T 威胁 |" in prompt
    assert "| S 优势 | **SO 增长型**<br>1. ...<br>2. ... |" in prompt


def test_clean_summary_segment_accepts_fixed_matrices():
    writer = ReportWriterAgent()

    cleaned = writer._clean_summary_segment(_fixed_summary())

    assert cleaned.startswith("## 第四章：总结")
    assert "|  | 正向因素 | 负向因素 |" in cleaned
    assert "| S 优势 | **SO 增长型**" in cleaned


def test_clean_summary_segment_rejects_variable_swot_layout():
    variable_summary = """
## 第四章：总结

### SWOT 因素矩阵
|  | 优势（S） | 劣势（W） |
| --- | --- | --- |
| 机会（O） | 机会和优势混在一起。[1] | 机会和劣势混在一起。[2] |
| 威胁（T） | 威胁和优势混在一起。[3] | 威胁和劣势混在一起。[4] |

### TOWS 战略矩阵
|  | 优势（S） | 劣势（W） |
| --- | --- | --- |
| 机会（O） | SO 内容。[1] | WO 内容。[2] |
| 威胁（T） | ST 内容。[3] | WT 内容。[4] |

### 总结论述
格式不应被接受。
"""

    assert ReportWriterAgent()._clean_summary_segment(variable_summary) == ""


def test_fallback_summary_uses_fixed_matrix_contract():
    summary = ReportWriterAgent()._fallback_summary_chapter(
        claims=[{"evidence_ids": ["ev_1"]}],
        evidence_items=[{"id": "ev_1"}],
    )

    assert ReportWriterAgent()._has_fixed_summary_matrices(summary)
    assert "|  | 正向因素 | 负向因素 |" in summary
    assert "| W 劣势 | **WO 扭转型**" in summary


def test_dynamic_section_body_requires_refs_for_each_claim_competitor():
    writer = ReportWriterAgent()
    claims = [
        {
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}
    body = """
| 对比项 | 飞书 | 钉钉 |
| --- | --- | --- |
| 核心增长打法 | 飞书有可追溯增长证据。[1] | 公开可追溯的增长与渠道获客维度相关有效证据不足 |
""".strip()

    assert not writer._dynamic_section_body_covers_claim_competitors(
        body,
        claims,
        refs,
    )


def test_dynamic_section_body_accepts_refs_for_each_claim_competitor():
    writer = ReportWriterAgent()
    claims = [
        {
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}
    body = """
| 对比项 | 飞书 | 钉钉 |
| --- | --- | --- |
| 核心增长打法 | 飞书有可追溯增长证据。[1] | 钉钉有客户争夺和用户规模相关证据。[2] |
""".strip()

    assert writer._dynamic_section_body_covers_claim_competitors(
        body,
        claims,
        refs,
    )


def test_dynamic_section_body_rejects_asymmetric_gap_cell_for_supported_competitor():
    writer = ReportWriterAgent()
    claims = [
        {
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}
    body = """
| 对比维度 | 飞书 | 钉钉 |
| --- | --- | --- |
| 公开可查标杆落地案例 | 飞书有标杆案例公开证据。[1] | 公开证据不足 |
| 核心差异化特色能力 | 公开证据不足 | 钉钉有 AI 办公能力公开证据。[2] |

公开资料显示，飞书与钉钉均有可追溯证据。[1][2]
""".strip()

    assert not writer._dynamic_section_body_covers_claim_competitors(
        body,
        claims,
        refs,
    )


def test_dynamic_section_body_allows_conservative_paragraph_when_competitors_supported():
    writer = ReportWriterAgent()
    claims = [
        {
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}
    body = """
| 对比维度 | 飞书 | 钉钉 |
| --- | --- | --- |
| 公开定位与能力 | 飞书有标杆案例公开证据。[1] | 钉钉有 AI 办公能力公开证据。[2] |

公开资料显示，双方均有证据支撑核心定位，但尚不足以确认完整长期落地细节。[1][2]
""".strip()

    assert writer._dynamic_section_body_covers_claim_competitors(
        body,
        claims,
        refs,
    )


def test_dynamic_section_context_includes_blocked_coverage_with_evidence():
    writer = ReportWriterAgent()
    section = {
        "number": "3.8",
        "id": "operations_fulfillment",
        "title": "运营与履约",
        "guiding_question": "比较运营履约公开证据。",
        "source_dimension_ids": ["operations_fulfillment"],
    }
    state = {
        "task": {"query": "分析飞书和钉钉"},
        "competitors": [{"name": "钉钉"}],
        "analysis_dimensions": [
            {"id": "operations_fulfillment", "name": "运营与履约"},
        ],
        "branch_coverage_states": [
            {
                "id": "coverage_dingtalk_ops",
                "competitor": "钉钉",
                "analysis_dimension_id": "operations_fulfillment",
                "dimension_id": "operations_fulfillment",
                "dimension_name": "运营与履约",
                "status": "blocked",
                "accepted_evidence_ids": ["ev_ops"],
                "found_source_types": ["docs"],
                "open_gap_codes": ["insufficient_primary_authoritative_sources"],
                "blocked_gap_codes": ["insufficient_primary_authoritative_sources"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_ops",
                "competitor": "钉钉",
                "analysis_dimension_id": "operations_fulfillment",
                "dimension_id": "operations_fulfillment",
                "title": "钉钉运营履约公开资料",
                "excerpt": "钉钉有运营履约公开证据。",
            }
        ],
        "knowledge_facts": [],
    }
    claims = [
        {
            "id": "claim_ops",
            "analysis_dimension_id": "operations_fulfillment",
            "claim": "钉钉运营履约有公开证据。",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_ops"],
        }
    ]

    context = writer._build_dynamic_section_context(
        state,
        section,
        claims,
        {"ev_ops": "[1]"},
    )
    payload = json.loads(context)

    assert "branch_coverage_states" in payload
    assert payload["branch_coverage_states"][0]["status"] == "blocked"
    assert payload["branch_coverage_states"][0]["accepted_evidence_count"] == 1
    assert "same-basis" in " ".join(payload["reporting_constraints"])
