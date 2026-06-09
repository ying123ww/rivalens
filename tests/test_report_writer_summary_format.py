"""Report writer summary format contract tests."""

import asyncio
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


def test_clean_summary_segment_strips_llm_instruction_echoes():
    summary = """
## 第四章：总结

### SWOT 因素矩阵

基于 Context 中的 analysis_claims 和 evidence_items 对主要竞品做综合分析，输出固定 2×2 SWOT 因素矩阵；不要改表头、不要改行名、不要新增列。只替换每个格子里的编号内容：

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1] | **W 劣势**<br>1. 产品迁移成本较高。[2] |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[3] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[4] |

### TOWS 战略矩阵

基于上述 SWOT 因子交叉配对，输出 TOWS 战略矩阵（SO 增长型 / WO 扭转型 / ST 多点型 / WT 防御型）。
必须严格输出下面这个固定 TOWS 战略矩阵；不要改表头、不要改行名、不要新增列。只替换每个格子里的编号内容：

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][3] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][4] |
| W 劣势 | **WO 扭转型**<br>1. 通过 AI 协同机会降低迁移成本。[2][3] | **WT 防御型**<br>1. 针对竞争压力降低迁移风险。[2][4] |

### 总结论述

现有公开证据显示，双方仍需围绕 AI 协同继续验证差异。[1][2]
"""

    cleaned = ReportWriterAgent()._clean_summary_segment(summary)

    assert cleaned
    assert "基于 Context" not in cleaned
    assert "不要改表头" not in cleaned
    assert "|  | 正向因素 | 负向因素 |" in cleaned
    assert "| W 劣势 | **WO 扭转型**" in cleaned


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


def test_clean_summary_segment_rejects_mixed_gap_fillers():
    mixed_summary = """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1]<br>2. 公开证据不足 | **W 劣势**<br>1. 公开证据不足。 |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[2] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[3] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][2] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][3] |
| W 劣势 | **WO 扭转型**<br>1. 公开证据不足，无法推演。 | **WT 防御型**<br>1. 公开证据不足，无法推演。 |

### 总结论述

格式不应被接受。
"""

    assert ReportWriterAgent()._clean_summary_segment(mixed_summary) == ""


def test_clean_summary_segment_rejects_cited_soft_gap_fillers():
    soft_gap_summary = """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1]<br>2. 公开证据中未明确提及钉钉在此维度的标杆客户案例。[2] | **W 劣势**<br>1. 公开证据不足。 |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[2] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[3] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][2] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][3] |
| W 劣势 | **WO 扭转型**<br>1. 公开证据不足，无法推演。 | **WT 防御型**<br>1. 公开证据不足，无法推演。 |

### 总结论述

格式不应被接受。
"""

    assert ReportWriterAgent()._clean_summary_segment(soft_gap_summary) == ""


def test_clean_summary_segment_rejects_uncited_soft_gap_cells():
    uncited_gap_summary = """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1] | **W 劣势**<br>1. 飞书：公开证据中未明确提及针对其内部劣势的具体描述。 |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[2] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[3] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][2] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][3] |
| W 劣势 | **WO 扭转型**<br>1. 公开证据不足，无法推演。 | **WT 防御型**<br>1. 公开证据不足，无法推演。 |

### 总结论述

格式不应被接受。
"""

    assert ReportWriterAgent()._clean_summary_segment(uncited_gap_summary) == ""


def test_clean_summary_segment_rejects_partially_uncited_matrix_entries():
    partially_uncited_summary = """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1] | **W 劣势**<br>1. 产品迁移成本较高。[2]<br>2. 飞书大众市场认知覆盖度相对有限 |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[3] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[4] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][3] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][4] |
| W 劣势 | **WO 扭转型**<br>1. 通过 AI 协同机会降低迁移成本。[2][3] | **WT 防御型**<br>1. 针对竞争压力降低迁移风险。[2][4] |

### 总结论述

格式不应被接受。
"""

    assert ReportWriterAgent()._clean_summary_segment(partially_uncited_summary) == ""


def test_summary_generation_retries_invalid_output_before_fallback():
    bad_summary = """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1] | **W 劣势**<br>1. 产品迁移成本较高。[2]<br>2. 飞书大众市场认知覆盖度相对有限 |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[3] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[4] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][3] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][4] |
| W 劣势 | **WO 扭转型**<br>1. 通过 AI 协同机会降低迁移成本。[2][3] | **WT 防御型**<br>1. 针对竞争压力降低迁移风险。[2][4] |

### 总结论述

格式应触发重试。
"""

    class DummyConfig:
        prompt_family = "default"
        smart_llm_model = "fake"
        smart_token_limit = 4096

    class FakeSummaryGenerator:
        responses = [bad_summary, _fixed_summary()]
        prompts: list[str] = []

        def __init__(self, researcher):
            self.researcher = researcher

        async def write_report(self, custom_prompt: str = "") -> str:
            self.prompts.append(custom_prompt)
            return self.responses.pop(0)

    generation = {
        "report": "",
        "errors": [],
        "cost": 0.0,
        "step_costs": {},
        "segment_context_lengths": [],
        "segment_count": 0,
        "fallback_used": False,
        "repair_attempts": {},
        "repair_feedback": {},
    }
    writer = ReportWriterAgent(report_generator_factory=FakeSummaryGenerator)

    summary = asyncio.run(
        writer._generate_summary_segment_with_retries(
            query="分析飞书和钉钉",
            context="{}",
            cfg=DummyConfig(),
            generation=generation,
        )
    )

    assert summary == _fixed_summary()
    assert generation["segment_count"] == 2
    assert generation["repair_attempts"]["summary"] == 1
    assert "SWOT/TOWS 某些编号条目缺少 citation_ref" in generation["repair_feedback"]["summary"][0]["errors"][0]
    assert "第 1/3 次修复机会" in FakeSummaryGenerator.prompts[1]
    assert not generation["fallback_used"]


def test_clean_summary_segment_rejects_wt_using_st_pair():
    bad_wt_summary = """
## 第四章：总结

### SWOT 因素矩阵

|  | 正向因素 | 负向因素 |
| --- | --- | --- |
| 内部 | **S 优势**<br>1. 飞书项目支持 50 天免费试用。[1] | **W 劣势**<br>1. 产品迁移成本较高。[2] |
| 外部 | **O 机会**<br>1. AI 协同仍有结构性机会。[3] | **T 威胁**<br>1. 跨界 SaaS 竞争可能分流客户。[4] |

### TOWS 战略矩阵

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| S 优势 | **SO 增长型**<br>1. 依托飞书项目扩展 AI 项目管理方案。[1][3] | **ST 多点型**<br>1. 用项目管理深度绑定核心客户。[1][4] |
| W 劣势 | **WO 扭转型**<br>1. 通过 AI 协同机会降低迁移成本。[2][3] | **WT 防御型**<br>1. 沿用 ST1 的客户绑定动作缓解迁移风险。[2][4] |

### 总结论述

格式不应被接受。
"""

    assert ReportWriterAgent()._clean_summary_segment(bad_wt_summary) == ""


def test_fallback_summary_uses_fixed_matrix_contract():
    summary = ReportWriterAgent()._fallback_summary_chapter(
        claims=[{"evidence_ids": ["ev_1"]}],
        evidence_items=[{"id": "ev_1"}],
    )

    assert ReportWriterAgent()._has_fixed_summary_matrices(summary)
    assert "|  | 正向因素 | 负向因素 |" in summary
    assert "| W 劣势 | **WO 扭转型**" in summary
    assert "竞品弱势领域在外部压力下可能成为突破口" not in summary
    assert "**WT 防御型**<br>1. 公开证据不足，无法推演" in summary


def test_opening_segment_requires_profile_refs_for_each_competitor():
    writer = ReportWriterAgent()
    state = {
        "competitors": [
            {"name": "飞书", "evidence_ids": ["ev_feishu"]},
            {"name": "钉钉", "evidence_ids": ["ev_dingtalk"]},
        ]
    }
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}

    assert not writer._opening_has_expected_competitor_citations(
        "# 竞品分析报告\n\n## 第二章：确定竞品\n\n飞书主要引用 [1]，钉钉主要引用 []。",
        state,
        refs,
    )
    assert writer._opening_has_expected_competitor_citations(
        "# 竞品分析报告\n\n## 第二章：确定竞品\n\n飞书主要引用 [1]，钉钉主要引用 [2]。",
        state,
        refs,
    )


def test_opening_segment_uses_claim_refs_when_profile_refs_are_missing():
    writer = ReportWriterAgent()
    state = {
        "competitors": [
            {"name": "飞书"},
            {"name": "钉钉"},
        ]
    }
    claims = [
        {
            "claim": "飞书主打一站式无缝办公协作。",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "claim": "钉钉定位为面向团队的AI智能办公平台。",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}

    assert not writer._opening_has_expected_competitor_citations(
        "# 竞品分析报告\n\n## 第二章：确定竞品\n\n飞书主要引用 [1]，钉钉暂无引用。",
        state,
        refs,
        claims,
    )
    assert writer._opening_has_expected_competitor_citations(
        "# 竞品分析报告\n\n## 第二章：确定竞品\n\n飞书主要引用 [1]，钉钉主要引用 [2]。",
        state,
        refs,
        claims,
    )


def test_fallback_opening_filters_raw_competitor_notes():
    state = {
        "task": {"query": "分析飞书和钉钉"},
        "competitors": [
            {
                "name": "飞书",
                "product": "飞书",
                "website": "https://www.feishu.cn",
                "category": "SaaS",
                "notes": (
                    "模板中心｜访客签到登记模板 - 飞书官网 合作与支持 飞行社 定价 "
                    "400-0682-666 下载飞书 系统中心 多维表格 访客签到登记表系统"
                ),
            },
            {
                "name": "钉钉",
                "product": "钉钉",
                "website": "https://dingtalk.com",
                "category": "SaaS",
                "notes": (
                    "覆盖企业网盘安全空间-钉盘-钉钉官网 悟空 超级服务 "
                    "开放平台 官方商城 办公数字化 组织数字化 业务数字化 "
                    "钉钉体验中心 客户案例 行业解决方案 模版中心"
                ),
            },
        ],
    }

    opening = ReportWriterAgent()._fallback_opening_chapters(state, {})

    assert "合作与支持 飞行社 定价" not in opening
    assert "下载飞书" not in opening
    assert "悟空 超级服务" not in opening
    assert "官方商城" not in opening
    assert "模版中心" not in opening
    assert "| 飞书 | 飞书 | SaaS | https://www.feishu.cn | 见后续分析维度 |" in opening
    assert "| 钉钉 | 钉钉 | SaaS | https://dingtalk.com | 见后续分析维度 |" in opening


def test_fallback_opening_uses_claim_refs_for_profile_table():
    writer = ReportWriterAgent()
    state = {
        "task": {"query": "分析飞书和钉钉"},
        "competitors": [
            {"name": "飞书", "product": "飞书", "website": "https://www.feishu.cn", "category": "SaaS"},
            {"name": "钉钉", "product": "钉钉", "website": "https://dingtalk.com", "category": "SaaS"},
        ],
    }
    claims = [
        {
            "claim": "飞书主打一站式无缝办公协作。",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "claim": "钉钉定位为面向团队的AI智能办公平台。",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]

    opening = writer._fallback_opening_chapters(
        state,
        {"ev_feishu": "[1]", "ev_dingtalk": "[2]"},
        claims,
    )

    assert "| 飞书 | 飞书 | SaaS | https://www.feishu.cn | 见后续分析维度 | [1] |" in opening
    assert "| 钉钉 | 钉钉 | SaaS | https://dingtalk.com | 见后续分析维度 | [2] |" in opening
    assert "公开资料不足" not in opening


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
    assert writer._dynamic_section_body_has_competitor_dimension_matrix(
        body,
        {
            "number": "3.1",
            "id": "ai_capability",
            "title": "AI 能力",
            "source_dimension_ids": ["ai_capability"],
            "competitors": ["飞书", "钉钉"],
        },
        claims,
    )


def test_dynamic_section_body_rejects_long_claim_table_layout():
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
    body = """
| 动态维度 | 竞品/对象 | 结论 | 引用 |
| --- | --- | --- | --- |
| AI 能力 | 飞书 | 飞书有可追溯 AI 能力证据。 | [1] |
| AI 能力 | 钉钉 | 钉钉有可追溯 AI 能力证据。 | [2] |
""".strip()

    assert not writer._dynamic_section_body_has_competitor_dimension_matrix(
        body,
        {
            "number": "3.1",
            "id": "ai_capability",
            "title": "AI 能力",
            "source_dimension_ids": ["ai_capability"],
            "competitors": ["飞书", "钉钉"],
        },
        claims,
    )


def test_dynamic_section_fallback_uses_competitor_columns_and_dimension_rows():
    writer = ReportWriterAgent()
    section = {
        "number": "3.1",
        "id": "ai_capability",
        "title": "AI 能力",
        "guiding_question": "比较 AI 能力。",
        "source_dimension_ids": ["ai_capability"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 Aily 智能体用于企业员工工作助手。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉 AI PaaS 面向生态伙伴开放。",
            "claim_type": "capability_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书商业版 ¥60/人/月。",
            "claim_type": "pricing_strategy",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_price"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉企业版 ¥18 人/月。",
            "claim_type": "pricing_strategy",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk_price"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书落地永辉客户案例。",
            "claim_type": "market_position_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_case"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉服务零售客户案例。",
            "claim_type": "market_position_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk_case"],
        },
    ]

    body = "\n".join(
        writer._dynamic_analysis_section_lines(
            section,
            claims,
            [],
            {
                "ev_feishu": "[1]",
                "ev_dingtalk": "[2]",
                "ev_feishu_price": "[3]",
                "ev_dingtalk_price": "[4]",
                "ev_feishu_case": "[5]",
                "ev_dingtalk_case": "[6]",
            },
        )
    )

    assert "| 对比维度 | 飞书 | 钉钉 |" in body
    assert "| AI 智能体与大模型能力 | 飞书 Aily 智能体用于企业员工工作助手。 [1] | 钉钉 AI PaaS 面向生态伙伴开放。 [2] |" in body
    assert "| 付费套餐与价格点 | 飞书商业版 ¥60/人/月。 [3] | 钉钉企业版 ¥18 人/月。 [4] |" in body
    assert "| 客户案例与行业落地 | 飞书落地永辉客户案例。 [5] | 钉钉服务零售客户案例。 [6] |" in body
    assert "| 动态维度 | 竞品/对象 | 结论 | 引用 |" not in body


def test_dynamic_section_fallback_does_not_use_raw_evidence_excerpt_without_claim():
    writer = ReportWriterAgent()
    section = {
        "number": "3.1",
        "id": "ai_capability",
        "title": "AI 能力",
        "guiding_question": "比较 AI 能力。",
        "source_dimension_ids": ["ai_capability"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 Aily 智能体用于企业员工工作助手。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        }
    ]
    evidence = [
        {
            "id": "ev_dingtalk_store",
            "analysis_dimension_id": "ai_capability",
            "competitor": "钉钉",
            "source_type": "review",
            "title": "DingTalk - Google Play 應用程式",
            "excerpt": (
                "DingTalk - Google Play 應用程式 DingTalk DingTalk "
                "(Singapore) Private Limited. 2.8 star 2.93K 則評論 所有人 "
                "info 500K+ 次下載 安裝 分享 加入願望清單 所有人 使用者互動 "
                "瞭解詳情 DingTalk —— 團隊的AI辦公平台"
            ),
        }
    ]

    body = "\n".join(
        writer._dynamic_analysis_section_lines(
            section,
            claims,
            evidence,
            {"ev_feishu": "[1]", "ev_dingtalk_store": "[7]"},
        )
    )

    assert "| 对比维度 | 飞书 | 钉钉 |" in body
    assert "飞书 Aily 智能体用于企业员工工作助手。 [1]" in body
    assert "公开证据不足" in body
    assert "[7]" not in body
    assert "Google Play" not in body
    assert "加入願望清單" not in body


def test_information_index_appendix_uses_claim_summary_not_raw_excerpt():
    writer = ReportWriterAgent()
    report = writer._append_information_index_appendix(
        "## 正文\n钉钉对外定位自身为面向团队的AI智能办公平台。[7]",
        [
            {
                "id": "claim_dingtalk_position",
                "analysis_dimension_id": "strategy",
                "claim": "钉钉对外定位自身为面向团队的AI智能办公平台。",
                "claim_type": "market_position_signal",
                "competitors": ["钉钉"],
                "evidence_ids": ["ev_dingtalk_store"],
            }
        ],
        [
            {
                "id": "ev_dingtalk_store",
                "analysis_dimension_id": "strategy",
                "dimension_name": "战略定位与差异化",
                "competitor": "钉钉",
                "source_type": "review",
                "title": "DingTalk - Google Play 應用程式",
                "url": "https://play.google.com/store/apps/details?id=com.alibaba.dingtalk.global",
                "excerpt": (
                    "DingTalk - Google Play 應用程式 DingTalk DingTalk "
                    "(Singapore) Private Limited. 2.8 star 2.93K 則評論 所有人 "
                    "info 500K+ 次下載 安裝 分享 加入願望清單 所有人 使用者互動 "
                    "瞭解詳情 DingTalk —— 團隊的AI辦公平台"
                ),
            }
        ],
        {"ev_dingtalk_store": "[7]"},
    )

    assert "| [7] | ev_dingtalk_store | claim_dingtalk_position |" in report
    assert "https://play.google.com/store/apps/details?id=com.alibaba.dingtalk.global" in report
    assert "钉钉对外定位自身为面向团队的AI智能办公平台。" in report
    assert "加入願望清單" not in report
    assert "使用者互動" not in report
    assert "2.8 star" not in report


def test_dynamic_section_fallback_does_not_write_raw_rule_fallback_claims():
    writer = ReportWriterAgent()
    section = {
        "number": "3.2",
        "id": "target_segments",
        "title": "目标用户与细分场景",
        "guiding_question": "比较目标用户与细分场景。",
        "source_dimension_ids": ["target_segments"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "id": "claim_raw_article",
            "analysis_dimension_id": "target_segments",
            "claim": (
                "飞书 目标用户与细分场景: public evidence signals 飞书——多维表格产品分析 "
                "| 人人都是产品经理 飞书——多维表格产品分析 文艺至死 2023-11-07 "
                "2 评论 13552 浏览 71 收藏 30 分钟 飞书多维表格属于飞书云文档的一种，"
                "那么使用起来体验如何？本文对飞书的多维表格产品进行体验，并分析其相关功能。"
            ),
            "claim_source": "knowledge_fact_group",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_raw_article"],
        },
        {
            "id": "claim_dingtalk_segment",
            "analysis_dimension_id": "target_segments",
            "claim": "专有钉钉面向大型组织，支持专有云、混合云部署。",
            "claim_source": "knowledge_fact_dimension_llm",
            "claim_type": "customer_segment_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk_segment"],
        },
    ]

    body = "\n".join(
        writer._dynamic_analysis_section_lines(
            section,
            claims,
            [],
            {"ev_raw_article": "[11]", "ev_dingtalk_segment": "[18]"},
        )
    )

    assert "| 对比维度 | 飞书 | 钉钉 |" in body
    assert "| 目标用户与细分场景 | 公开证据不足 | 专有钉钉面向大型组织，支持专有云、混合云部署。 [18] |" in body
    assert "[11]" not in body
    assert "人人都是产品经理" not in body
    assert "浏览" not in body
    assert "收藏" not in body


def test_dynamic_section_fallback_keeps_usable_long_knowledge_fact_group_claim():
    writer = ReportWriterAgent()
    section = {
        "number": "3.2",
        "id": "target_segments",
        "title": "目标用户与细分场景",
        "guiding_question": "比较目标用户与细分场景。",
        "source_dimension_ids": ["target_segments"],
        "competitors": ["飞书"],
    }
    claims = [
        {
            "id": "claim_feishu_segment",
            "analysis_dimension_id": "target_segments",
            "claim": (
                "飞书 目标用户与细分场景: public evidence signals "
                "合作与支持 飞行社 定价 飞书项目 下载飞书 "
                "飞书项目面向企业团队，支持项目管理、任务协作和进度跟踪场景。"
                "企业可通过飞书项目沉淀研发、营销、运营等流程。"
            ),
            "claim_source": "knowledge_fact_group",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_segment"],
        }
    ]

    body = "\n".join(
        writer._dynamic_analysis_section_lines(
            section,
            claims,
            [],
            {"ev_feishu_segment": "[12]"},
        )
    )

    assert "| 对比维度 | 飞书 |" in body
    assert "飞书项目面向企业团队，支持项目管理、任务协作和进度跟踪场景 [12]" in body
    assert "合作与支持 飞行社 定价" not in body
    assert "下载飞书" not in body


def test_dynamic_section_matrix_uses_same_dimension_claim_when_row_key_is_too_strict():
    writer = ReportWriterAgent()
    section = {
        "number": "3.1",
        "id": "strategy",
        "title": "战略定位",
        "guiding_question": "比较战略定位。",
        "source_dimension_ids": ["strategy"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "id": "claim_feishu_growth",
            "analysis_dimension_id": "strategy",
            "claim": "飞书公开资料显示其用户增长和跨行业客户签约持续推进。",
            "claim_type": "growth_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_growth"],
        },
        {
            "id": "claim_dingtalk_position",
            "analysis_dimension_id": "strategy",
            "claim": "钉钉对外定位自身为面向团队的AI智能办公平台。",
            "claim_type": "market_position_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk_position"],
        },
    ]
    refs = {"ev_feishu_growth": "[1]", "ev_dingtalk_position": "[2]"}

    body = "\n".join(
        writer._dynamic_analysis_section_lines(
            section,
            claims,
            [],
            refs,
        )
    )
    matrix_spec = writer._section_matrix_spec(section, claims, [], refs)

    assert "公开证据不足" not in body
    assert "同维度公开证据显示，钉钉对外定位自身为面向团队的AI智能办公平台。 [2]" in body
    assert "same_dimension" in json.dumps(matrix_spec, ensure_ascii=False)


def test_section_matrix_template_uses_sanitized_claim_candidates():
    writer = ReportWriterAgent()
    section = {
        "number": "3.2",
        "id": "target_segments",
        "title": "目标用户与细分场景",
        "guiding_question": "比较目标用户与细分场景。",
        "source_dimension_ids": ["target_segments"],
        "competitors": ["飞书"],
    }
    claims = [
        {
            "id": "claim_feishu_segment",
            "analysis_dimension_id": "target_segments",
            "claim": (
                "飞书 目标用户与细分场景: public evidence signals "
                "合作与支持 飞行社 定价 飞书项目 下载飞书 "
                "飞书项目面向企业团队，支持项目管理、任务协作和进度跟踪场景。"
            ),
            "claim_source": "knowledge_fact_group",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_segment"],
        }
    ]

    matrix_spec = writer._section_matrix_spec(
        section,
        claims,
        [],
        {"ev_feishu_segment": "[12]"},
    )
    candidate_text = matrix_spec["rows"][0]["cells"][0]["claim_candidates"][0]["text"]

    assert candidate_text == "飞书项目面向企业团队，支持项目管理、任务协作和进度跟踪场景"
    assert "合作与支持 飞行社 定价" not in candidate_text
    assert "下载飞书" not in candidate_text


def test_section_matrix_analysis_drops_outline_headings_and_samples_competitors():
    writer = ReportWriterAgent()
    claims = [
        {
            "claim": "飞书项目可将 SLA 标准、数据监控、知识沉淀落地为标准流程。",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_ops"],
        },
        {
            "claim": "三、「飞书项目」如何助力企业进行项目管理",
            "claim_source": "knowledge_fact_group",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_heading"],
        },
        {
            "claim": "飞书面向先进团队提供可定制业务管理工具。",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_team"],
        },
        {
            "claim": "专有钉钉面向大型组织，支持专有云、混合云部署。",
            "claim_type": "customer_segment_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]

    analysis = writer._section_matrix_analysis(
        claims,
        {
            "ev_feishu_ops": "[1]",
            "ev_feishu_heading": "[2]",
            "ev_feishu_team": "[3]",
            "ev_dingtalk": "[4]",
        },
    )

    assert "三、「飞书项目」" not in analysis
    assert "飞书项目可将 SLA 标准" in analysis
    assert "专有钉钉面向大型组织" in analysis


def test_dynamic_section_llm_json_fill_uses_fixed_matrix_and_rejects_raw_cells():
    writer = ReportWriterAgent()
    section = {
        "number": "3.1",
        "id": "ai_capability",
        "title": "AI 能力",
        "guiding_question": "比较 AI 能力。",
        "source_dimension_ids": ["ai_capability"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "id": "claim_feishu_ai",
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 Aily 智能体用于企业员工工作助手。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "id": "claim_dingtalk_ai",
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉 AI PaaS 面向生态伙伴开放。",
            "claim_type": "capability_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}
    matrix_spec = writer._section_matrix_spec(section, claims, [], refs)
    generated = json.dumps(
        {
            "cells": [
                {
                    "row_key": "ai_capability",
                    "competitor": "飞书",
                    "text": "飞书用 Aily 承接企业员工智能体场景。[1]",
                },
                {
                    "row_key": "ai_capability",
                    "competitor": "钉钉",
                    "text": (
                        "DingTalk - Google Play 應用程式 2.8 star "
                        "加入願望清單 使用者互動 瞭解詳情。[2]"
                    ),
                },
                {
                    "row_key": "invented_row",
                    "competitor": "飞书",
                    "text": "LLM 乱入的新维度。[1]",
                },
            ],
            "analysis": "公开资料显示，双方 AI 能力均有可追溯 claim 支撑。[1][2]",
        },
        ensure_ascii=False,
    )

    body = writer._dynamic_section_body_from_llm_fill(
        generated,
        section,
        claims,
        [],
        refs,
        matrix_spec,
    )

    assert "| 对比维度 | 飞书 | 钉钉 |" in body
    assert "| AI 智能体与大模型能力 | 飞书用 Aily 承接企业员工智能体场景。[1] | 钉钉 AI PaaS 面向生态伙伴开放。 [2] |" in body
    assert "公开资料显示，双方 AI 能力均有可追溯 claim 支撑。[1][2]" in body
    assert "LLM 乱入的新维度" not in body
    assert "Google Play" not in body
    assert "加入願望清單" not in body
    assert "| 动态维度 | 竞品/对象 | 结论 | 引用 |" not in body


def test_dynamic_section_llm_json_fill_accepts_ordered_cells_with_wrong_row_key():
    writer = ReportWriterAgent()
    section = {
        "number": "3.4",
        "id": "ai_capability",
        "title": "AI 能力与应用",
        "guiding_question": "比较 AI 能力。",
        "source_dimension_ids": ["ai_capability"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "id": "claim_feishu_ai",
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 CLI 支持 AI Agent 读消息、查日历、写文档。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "id": "claim_dingtalk_ai",
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉 AI 版本包含 20 万次大模型调用额度。",
            "claim_type": "capability_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    refs = {"ev_feishu": "[1]", "ev_dingtalk": "[2]"}
    matrix_spec = writer._section_matrix_spec(section, claims, [], refs)
    generated = json.dumps(
        {
            "cells": [
                {
                    "row_key": "AI能力产品落地",
                    "competitor": "飞书",
                    "text": "飞书 CLI 将 AI Agent 接入消息、日历和文档工作流。[1]",
                },
                {
                    "row_key": "AI能力产品落地",
                    "competitor": "钉钉",
                    "text": "钉钉 AI 版本公开包含 20 万次大模型调用额度。[2]",
                },
            ],
            "analysis": "公开资料显示，双方 AI 能力均有可追溯 claim 支撑。[1][2]",
        },
        ensure_ascii=False,
    )

    body = writer._dynamic_section_body_from_llm_fill(
        generated,
        section,
        claims,
        [],
        refs,
        matrix_spec,
    )

    assert "| AI 智能体与大模型能力 | 飞书 CLI 将 AI Agent 接入消息、日历和文档工作流。[1] | 钉钉 AI 版本公开包含 20 万次大模型调用额度。[2] |" in body


def test_dynamic_section_llm_analysis_rejects_gap_for_supported_competitor():
    writer = ReportWriterAgent()
    claims = [
        {
            "claim": "专有钉钉面向大型组织，支持专有云、混合云部署。",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        }
    ]

    accepted = writer._accepted_llm_analysis_text(
        "钉钉在该维度下公开证据不足，尚不足以确认完整细节。[1]",
        claims,
        {"ev_dingtalk": "[1]"},
    )

    assert accepted == ""


def test_dynamic_section_validation_rejects_gap_when_cell_has_candidates():
    writer = ReportWriterAgent()
    section = {
        "number": "3.2",
        "id": "target_segments",
        "title": "目标用户与细分场景",
        "guiding_question": "比较目标用户与细分场景。",
        "source_dimension_ids": ["target_segments"],
        "competitors": ["飞书", "钉钉"],
    }
    claims = [
        {
            "id": "claim_feishu",
            "analysis_dimension_id": "target_segments",
            "claim": "飞书项目可支撑企业 ITR 事件管理全流程。",
            "claim_type": "customer_segment_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "id": "claim_dingtalk",
            "analysis_dimension_id": "target_segments",
            "claim": "专有钉钉面向大型组织，支持专有云、混合云部署。",
            "claim_type": "customer_segment_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
    ]
    matrix_spec = writer._section_matrix_spec(
        section,
        claims,
        [],
        {"ev_feishu": "[1]", "ev_dingtalk": "[2]"},
    )
    generated = json.dumps(
        {
            "cells": [
                {
                    "row_key": "target_segments",
                    "competitor": "飞书",
                    "text": "飞书项目可支撑企业 ITR 事件管理全流程。[1]",
                },
                {
                    "row_key": "target_segments",
                    "competitor": "钉钉",
                    "text": "公开证据不足",
                },
            ],
            "analysis": "双方都有目标用户相关公开证据。[1][2]",
        },
        ensure_ascii=False,
    )

    errors = writer._dynamic_section_validation_errors(generated, matrix_spec)

    assert any("不能写公开证据不足" in error for error in errors)


def test_dynamic_section_validation_rejects_ungrounded_cited_cell_text():
    writer = ReportWriterAgent()
    matrix_spec = {
        "competitors": ["钉钉"],
        "rows": [
            {
                "row_key": "target_segments",
                "label": "目标用户与细分场景",
                "cells": [
                    {
                        "competitor": "钉钉",
                        "candidate_scope": "exact_row",
                        "claim_candidates": [
                            {
                                "text": "专有钉钉面向大型组织，支持专有云、混合云部署。",
                                "citation_refs": ["[18]"],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    generated = json.dumps(
        {
            "cells": [
                {
                    "row_key": "target_segments",
                    "competitor": "钉钉",
                    "text": "钉钉支持低代码搭建适配个性化业务需求的协作应用[18]",
                }
            ],
            "analysis": "钉钉有对应公开资料。[18]",
        },
        ensure_ascii=False,
    )

    errors = writer._dynamic_section_validation_errors(generated, matrix_spec)

    assert any("未贴近候选 claim" in error for error in errors)


def test_dynamic_section_validation_allows_grounded_cited_paraphrase():
    writer = ReportWriterAgent()
    matrix_spec = {
        "competitors": ["钉钉"],
        "rows": [
            {
                "row_key": "target_segments",
                "label": "目标用户与细分场景",
                "cells": [
                    {
                        "competitor": "钉钉",
                        "candidate_scope": "exact_row",
                        "claim_candidates": [
                            {
                                "text": "专有钉钉面向大型组织，支持专有云、混合云部署。",
                                "citation_refs": ["[18]"],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    generated = json.dumps(
        {
            "cells": [
                {
                    "row_key": "target_segments",
                    "competitor": "钉钉",
                    "text": "专有钉钉面向大型组织，可支持专有云与混合云部署[18]",
                }
            ],
            "analysis": "钉钉有对应公开资料。[18]",
        },
        ensure_ascii=False,
    )

    assert writer._dynamic_section_validation_errors(generated, matrix_spec) == []


def test_dynamic_section_non_json_llm_output_is_rejected_for_fallback():
    writer = ReportWriterAgent()
    section = {
        "number": "3.1",
        "id": "ai_capability",
        "title": "AI 能力",
        "guiding_question": "比较 AI 能力。",
        "source_dimension_ids": ["ai_capability"],
        "competitors": ["飞书"],
    }
    claims = [
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 Aily 智能体用于企业员工工作助手。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        }
    ]
    refs = {"ev_feishu": "[1]"}
    matrix_spec = writer._section_matrix_spec(section, claims, [], refs)

    assert (
        writer._dynamic_section_body_from_llm_fill(
            "| 竞品/对象 | 结论 | 引用 |\n| --- | --- | --- |",
            section,
            claims,
            [],
            refs,
            matrix_spec,
        )
        == ""
    )


def test_dynamic_section_generation_retries_invalid_output_before_fallback():
    class DummyConfig:
        prompt_family = "default"
        smart_llm_model = "fake"
        smart_token_limit = 4096

    class FakeSectionGenerator:
        responses = [
            "| 对比维度 | 飞书 |\n| --- | --- |\n| AI 能力 | 飞书有 AI。[1] |",
            json.dumps(
                {
                    "cells": [
                        {
                            "row_key": "ai_capability",
                            "competitor": "飞书",
                            "text": "飞书 Aily 智能体用于企业员工工作助手。[1]",
                        }
                    ],
                    "analysis": "公开资料显示，飞书 AI 能力有可追溯 claim 支撑。[1]",
                },
                ensure_ascii=False,
            ),
        ]
        prompts: list[str] = []

        def __init__(self, researcher):
            self.researcher = researcher

        async def write_report(self, custom_prompt: str = "") -> str:
            self.prompts.append(custom_prompt)
            return self.responses.pop(0)

    writer = ReportWriterAgent(report_generator_factory=FakeSectionGenerator)
    section = {
        "number": "3.1",
        "id": "ai_capability",
        "title": "AI 能力",
        "guiding_question": "比较 AI 能力。",
        "source_dimension_ids": ["ai_capability"],
        "competitors": ["飞书"],
    }
    claims = [
        {
            "id": "claim_feishu_ai",
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 Aily 智能体用于企业员工工作助手。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        }
    ]
    refs = {"ev_feishu": "[1]"}
    matrix_spec = ReportWriterAgent()._section_matrix_spec(section, claims, [], refs)
    generation = {
        "report": "",
        "errors": [],
        "cost": 0.0,
        "step_costs": {},
        "segment_context_lengths": [],
        "segment_count": 0,
        "fallback_used": False,
        "repair_attempts": {},
        "repair_feedback": {},
    }

    body = asyncio.run(
        writer._generate_dynamic_section_body_with_retries(
            state={},
            section=section,
            section_claims=claims,
            section_evidence=[],
            citation_refs_by_evidence_id=refs,
            matrix_spec=matrix_spec,
            query="分析飞书",
            context=json.dumps({"matrix_template": matrix_spec}, ensure_ascii=False),
            cfg=DummyConfig(),
            generation=generation,
        )
    )

    assert "飞书 Aily 智能体用于企业员工工作助手。[1]" in body
    assert generation["segment_count"] == 2
    assert generation["repair_attempts"]["analysis_ai_capability"] == 1
    assert "strict JSON" in generation["repair_feedback"]["analysis_ai_capability"][0]["errors"][0]
    assert "第 1/3 次修复机会" in FakeSectionGenerator.prompts[1]


def test_dynamic_analysis_sections_run_concurrently_and_keep_report_order():
    class DummyConfig:
        prompt_family = "default"
        smart_llm_model = "fake"
        smart_token_limit = 4096

    class FakeConcurrentSectionGenerator:
        active_sections = 0
        max_active_sections = 0

        def __init__(self, researcher):
            self.researcher = researcher

        async def write_report(self, custom_prompt: str = "") -> str:
            segment_id = self.researcher.query.split("Segment: ", 1)[1]
            if segment_id == "analysis_overview":
                return (
                    "### 分析维度总览\n\n"
                    "| 章节 | 动态维度 | 证据覆盖 | 主要竞品 | 主要引用 |\n"
                    "| --- | --- | --- | --- | --- |\n"
                    "| 3.1 | A 维度 | 1 条可追溯 claim | 飞书 | [1] |"
                )

            FakeConcurrentSectionGenerator.active_sections += 1
            FakeConcurrentSectionGenerator.max_active_sections = max(
                FakeConcurrentSectionGenerator.max_active_sections,
                FakeConcurrentSectionGenerator.active_sections,
            )
            try:
                if segment_id == "analysis_dim_a":
                    await asyncio.sleep(0.03)
                else:
                    await asyncio.sleep(0.01)
                payload = json.loads(self.researcher.context)
                matrix = payload["matrix_template"]
                refs = []
                cells = []
                for row in matrix.get("rows", []):
                    for cell in row.get("cells", []):
                        candidates = cell.get("claim_candidates", [])
                        if candidates:
                            candidate = candidates[0]
                            candidate_refs = candidate.get("citation_refs", [])
                            refs.extend(candidate_refs)
                            text = f"{candidate['text']}{''.join(candidate_refs)}"
                        else:
                            text = "公开证据不足"
                        cells.append(
                            {
                                "row_key": row["row_key"],
                                "competitor": cell["competitor"],
                                "text": text,
                            }
                        )
                return json.dumps(
                    {
                        "cells": cells,
                        "analysis": (
                            f"{payload['section']['title']} 有可追溯结论。"
                            f"{''.join(refs[:1])}"
                        ),
                    },
                    ensure_ascii=False,
                )
            finally:
                FakeConcurrentSectionGenerator.active_sections -= 1

    writer = ReportWriterAgent(
        report_generator_factory=FakeConcurrentSectionGenerator,
        max_concurrent_dynamic_sections=2,
    )
    claims = [
        {
            "id": "claim_a",
            "analysis_dimension_id": "dim_a",
            "claim": "飞书在 A 维度有明确能力。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_a"],
        },
        {
            "id": "claim_b",
            "analysis_dimension_id": "dim_b",
            "claim": "飞书在 B 维度有明确能力。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_b"],
        },
        {
            "id": "claim_c",
            "analysis_dimension_id": "dim_c",
            "claim": "飞书在 C 维度有明确能力。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_c"],
        },
    ]
    evidence_items = [
        {"id": "ev_a", "analysis_dimension_id": "dim_a", "competitor": "飞书"},
        {"id": "ev_b", "analysis_dimension_id": "dim_b", "competitor": "飞书"},
        {"id": "ev_c", "analysis_dimension_id": "dim_c", "competitor": "飞书"},
    ]
    dimensions = [
        {"id": "dim_a", "name": "A 维度", "description": "比较 A。"},
        {"id": "dim_b", "name": "B 维度", "description": "比较 B。"},
        {"id": "dim_c", "name": "C 维度", "description": "比较 C。"},
    ]
    generation = writer._empty_generation_metadata()

    chapter = asyncio.run(
        writer._generate_dynamic_analysis_chapter_segmented(
            state={"task": {"query": "分析飞书"}, "analysis_dimensions": dimensions},
            query="分析飞书",
            cfg=DummyConfig(),
            claims=claims,
            evidence_items=evidence_items,
            analysis_dimensions=dimensions,
            citation_refs_by_evidence_id={
                "ev_a": "[1]",
                "ev_b": "[2]",
                "ev_c": "[3]",
            },
            generation=generation,
        )
    )

    assert FakeConcurrentSectionGenerator.max_active_sections == 2
    assert chapter.index("### 3.1 A 维度") < chapter.index("### 3.2 B 维度")
    assert chapter.index("### 3.2 B 维度") < chapter.index("### 3.3 C 维度")
    assert generation["segment_count"] == 4
    assert not generation["fallback_used"]


def test_dynamic_section_body_rejects_single_row_when_claims_have_multiple_aspects():
    writer = ReportWriterAgent()
    claims = [
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书 Aily 智能体用于企业员工工作助手。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉 AI PaaS 面向生态伙伴开放。",
            "claim_type": "capability_signal",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "飞书商业版 ¥60/人/月。",
            "claim_type": "pricing_strategy",
            "competitors": ["飞书"],
            "evidence_ids": ["ev_feishu_price"],
        },
        {
            "analysis_dimension_id": "ai_capability",
            "claim": "钉钉企业版 ¥18 人/月。",
            "claim_type": "pricing_strategy",
            "competitors": ["钉钉"],
            "evidence_ids": ["ev_dingtalk_price"],
        },
    ]
    body = """
| 对比维度 | 飞书 | 钉钉 |
| --- | --- | --- |
| AI 能力 | 飞书有 AI 能力和定价证据。[1][3] | 钉钉有 AI 能力证据。[2] |
""".strip()

    assert not writer._dynamic_section_body_has_competitor_dimension_matrix(
        body,
        {
            "number": "3.1",
            "id": "ai_capability",
            "title": "AI 能力",
            "source_dimension_ids": ["ai_capability"],
            "competitors": ["飞书", "钉钉"],
        },
        claims,
    )


def test_dynamic_section_body_allows_asymmetric_gap_cells_when_competitors_supported():
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

    assert writer._dynamic_section_body_covers_claim_competitors(
        body,
        claims,
        refs,
    )


def test_dynamic_section_body_rejects_gap_only_column_for_supported_competitor():
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
| 核心差异化特色能力 | 飞书有特色能力公开证据。[1] | 公开证据不足 |

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


def test_summary_context_samples_across_dimensions_and_competitors():
    writer = ReportWriterAgent()
    claims = [
        {
            "id": f"claim_feishu_ai_{index}",
            "analysis_dimension_id": "ai_capability",
            "claim": f"飞书 Aily 能力证据 {index}。",
            "claim_type": "capability_signal",
            "competitors": ["飞书"],
            "evidence_ids": [f"ev_feishu_ai_{index}"],
        }
        for index in range(35)
    ]
    claims.extend(
        [
            {
                "id": "claim_raw_page",
                "analysis_dimension_id": "target_segments",
                "claim": (
                    "飞书 目标用户与细分场景: public evidence signals "
                    "飞书——多维表格产品分析 | 人人都是产品经理 文艺至死 "
                    "2 评论 13552 浏览 71 收藏 30 分钟"
                ),
                "claim_source": "knowledge_fact_group",
                "claim_type": "customer_segment_signal",
                "competitors": ["飞书"],
                "evidence_ids": ["ev_raw_page"],
            },
            {
                "id": "claim_dingtalk_target",
                "analysis_dimension_id": "target_segments",
                "claim": "专有钉钉面向大型组织，支持专有云、混合云部署。",
                "claim_type": "customer_segment_signal",
                "competitors": ["钉钉"],
                "evidence_ids": ["ev_dingtalk_target"],
            },
            {
                "id": "claim_dingtalk_pricing",
                "analysis_dimension_id": "business_model_pricing",
                "claim": "钉钉专业版公开套餐按组织规模提供付费权益。",
                "claim_type": "pricing_strategy",
                "competitors": ["钉钉"],
                "evidence_ids": ["ev_dingtalk_pricing"],
            },
        ]
    )
    refs = {
        **{
            f"ev_feishu_ai_{index}": f"[{index + 1}]"
            for index in range(35)
        },
        "ev_raw_page": "[90]",
        "ev_dingtalk_target": "[91]",
        "ev_dingtalk_pricing": "[92]",
    }

    context = writer._build_summary_context(
        {
            "task": {"query": "分析飞书和钉钉"},
            "competitors": [{"name": "飞书"}, {"name": "钉钉"}],
            "evidence_items": [],
            "knowledge_facts": [],
        },
        claims,
        [
            {"id": "ai_capability", "name": "AI 能力"},
            {"id": "target_segments", "name": "目标用户与细分场景"},
            {"id": "business_model_pricing", "name": "商业模式与定价"},
        ],
        refs,
    )
    payload = json.loads(context)
    sampled_ids = {claim["id"] for claim in payload["analysis_claims"]}

    assert "claim_dingtalk_target" in sampled_ids
    assert "claim_dingtalk_pricing" in sampled_ids
    assert "claim_raw_page" not in sampled_ids
