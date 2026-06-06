"""Report writer summary format contract tests."""

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
