"""Report writer for structured competitor analysis output."""

import json
from typing import Any, Callable

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState
from rivalens.research.config import Config
from rivalens.research.prompts import get_prompt_family
from rivalens.research.skills.writer import ReportGenerator
from rivalens.research.utils.enum import ReportSource, ReportType, Tone


SECTION_CLAIM_LIMIT = 12
DYNAMIC_ANALYSIS_SECTION_LIMIT = 8
SUMMARY_CLAIM_LIMIT = 30
OPENING_CONTEXT_CHAR_LIMIT = 6000
ANALYSIS_OVERVIEW_CONTEXT_CHAR_LIMIT = 6000
SECTION_CONTEXT_CHAR_LIMIT = 8000
SUMMARY_CONTEXT_CHAR_LIMIT = 9000


class _ReportResearcherAdapter:
    """Small adapter exposing the ResearchEngine fields used by ReportGenerator."""

    def __init__(
        self,
        query: str,
        context: str,
        cfg: Config,
        role: str,
        custom_prompt: str = "",
    ) -> None:
        self.query = query
        self.report_type = ReportType.CustomReport.value
        self.report_source = ReportSource.Web.value
        self.tone = Tone.Analytical
        self.websocket = None
        self.cfg = cfg
        self.headers: dict[str, str] = {}
        self.context = context
        self.kwargs: dict[str, Any] = {}
        self.custom_prompt = custom_prompt
        self.role = role
        self.parent_query = ""
        self.subtopics: list[str] = []
        self.verbose = False
        self.research_costs = 0.0
        self.step_costs: dict[str, float] = {}
        self._current_step = "report_writing"
        self.log_handler = None
        self.prompt_family = get_prompt_family(
            getattr(cfg, "prompt_family", "default"),
            cfg,
        )

    def get_research_images(self, top_k: int = 10) -> list[dict[str, Any]]:
        return []

    def add_costs(self, cost: float) -> None:
        self.research_costs += float(cost)
        step = self._current_step
        self.step_costs[step] = self.step_costs.get(step, 0.0) + float(cost)


class ReportWriterAgent:
    def __init__(
        self,
        config: Config | None = None,
        report_generator_factory: Callable[[Any], Any] = ReportGenerator,
    ) -> None:
        self.config = config
        self.report_generator_factory = report_generator_factory

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        claims = state.get("analysis_claims", [])
        claim_support_message = latest_message_for(
            state,
            receiver="writer",
            message_type="claim_support",
            sender="claim_support",
        )
        claim_support_reviews = (
            state.get("claim_support_reviews")
            or (
                claim_support_message.get("payload", {}).get("reviews", [])
                if claim_support_message
                else []
            )
        )
        claims = self._supported_claims(claims, claim_support_reviews)
        evidence_items = self._report_evidence_items(state, claims)
        evidence_ids = self._ordered_evidence_ids(claims, evidence_items)
        citation_refs_by_evidence_id = self._citation_refs_by_evidence_id(evidence_ids)
        analysis_dimensions = self._analysis_dimensions(state, evidence_items)
        context = self._build_report_context(
            state,
            claims,
            evidence_items,
            analysis_dimensions,
            citation_refs_by_evidence_id,
        )
        query = self._report_query(state)
        custom_prompt = self._report_format_prompt(analysis_dimensions)
        cfg = self.config or Config()
        generation = await self._generate_segmented_report(
            state=state,
            query=query,
            cfg=cfg,
            claims=claims,
            evidence_items=evidence_items,
            analysis_dimensions=analysis_dimensions,
            citation_refs_by_evidence_id=citation_refs_by_evidence_id,
        )
        generated_report = generation["report"]
        generation_error = "; ".join(generation["errors"]) or None
        report = (generated_report or "").strip()
        if not report:
            report = self._fallback_report(
                state,
                claims,
                evidence_items,
                analysis_dimensions,
            )
        report = self._apply_inline_citations(
            report,
            claims,
            citation_refs_by_evidence_id,
        )
        report = self._ensure_dynamic_analysis_chapter(
            report,
            claims,
            evidence_items,
            analysis_dimensions,
        )
        report = self._apply_inline_citations(
            report,
            claims,
            citation_refs_by_evidence_id,
        )
        report = self._append_information_index_appendix(
            report,
            claims,
            evidence_items,
            citation_refs_by_evidence_id,
        )
        report_length = len(report)
        generated_report_length = len(generated_report or "")

        return {
            "report": report,
            "messages": state.get("messages", [])
            + [
                create_agent_message(
                    sender="writer",
                    receiver="publisher",
                    message_type="report",
                    payload={"report_length": report_length},
                    evidence_ids=evidence_ids,
                )
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "writer",
                    "action": "compose_traceable_research_report",
                    "input": {
                        "query": query,
                        "claim_count": len(claims),
                        "claim_support_review_count": len(claim_support_reviews),
                        "evidence_count": len(evidence_items),
                        "analysis_dimension_count": len(analysis_dimensions),
                        "report_generator": self._report_generator_name(),
                        "report_type": ReportType.CustomReport.value,
                        "report_source": ReportSource.Web.value,
                        "prompt_family": get_prompt_family(
                            getattr(cfg, "prompt_family", "default"),
                            cfg,
                        ).__class__.__name__,
                        "context_length": len(context),
                        "max_segment_context_length": max(
                            generation["segment_context_lengths"],
                            default=0,
                        ),
                        "segment_count": generation["segment_count"],
                        "segment_context_char_limits": {
                            "opening": OPENING_CONTEXT_CHAR_LIMIT,
                            "dynamic_overview": ANALYSIS_OVERVIEW_CONTEXT_CHAR_LIMIT,
                            "dynamic_section": SECTION_CONTEXT_CHAR_LIMIT,
                            "summary": SUMMARY_CONTEXT_CHAR_LIMIT,
                        },
                        "custom_prompt_length": len(custom_prompt),
                        "model": getattr(cfg, "smart_llm_model", None),
                        "token_limit": getattr(cfg, "smart_token_limit", None),
                    },
                    "output": {
                        "generated_report_length": generated_report_length,
                        "report_length": report_length,
                        "fallback_used": generation["fallback_used"] or not bool(generated_report),
                        "cost": generation["cost"],
                        "step_costs": generation["step_costs"],
                        "generation_error": generation_error,
                    },
                }
            ],
        }

    def _report_query(self, state: CompetitorAnalysisState) -> str:
        task = state.get("task", {})
        base_query = task.get("query") or "Write a competitor analysis report."
        return (
            f"{base_query}\n\n"
            "按照 Rivalens 固定的四章正文与附录格式，撰写可追溯的竞品分析报告。"
        )

    def _writer_role_prompt(self) -> str:
        return (
            "你是竞品分析报告写作者。你必须使用结构化证据、claim 和 source URL 写作，"
            "不得引入未由 EvidenceItem 支撑的重要事实。"
        )

    def _report_format_prompt(self, analysis_dimensions: list[dict[str, Any]]) -> str:
        return f"""
你将收到 Rivalens 结构化竞品分析上下文。请只基于 Context 写 Markdown 报告正文。

输出必须严格采用以下结构：

# 竞品分析报告

## 第一章：分析目的
- 用用户最初提出的需求 / 问题，写一段完整说明文字。
- 不要写成项目符号。

## 第二章：确定竞品
### 竞品信息卡片
- 为每个竞品输出一个简短信息卡片。
- 卡片字段优先使用 competitors 中的 name、product、website、category、notes、evidence_ids。
- 官网字段使用 competitors.website；若为空，写“公开资料不足”。不要在写报告阶段自行猜测或替换官网。
- 如果字段由公开证据推导，必须展示对应 citation_ref，例如 [1]；不要无证据扩写。

### 竞品分类表格
- 输出 Markdown 表格。
- 推荐列：竞品、产品/品牌、分类、官网、备注、主要证据 ID。

## 第三章：竞品分析
- 不要使用预设产品维度模板。
- 基于 Context 中已采到的 analysis_claims、analysis_dimensions、evidence_items 和用户问题，动态归纳最有证据支撑的分析维度。
- 必须先输出“### 分析维度总览”表格，推荐列：章节、动态维度、证据覆盖、主要竞品、主要引用。
- 随后按总览顺序输出小节，标题格式为“### 3.x 动态维度名称”。
- 每个小节必须包含一个正式对比表格和一段分析文字。
- 表格或段落中要保留相关 citation_ref，例如 [1]。
- 只要 Context 中存在与该小节问题相关、可追溯的 claim 或 evidence，就可以引用；不要因为来源类型不是某类优先来源而弃用。
- 对间接公开证据生成的结论要保持保守表述，例如“公开资料显示”“间接证据显示”“尚不足以确认完整细节”。
- 如果某个分析维度在 Context 中没有任何可追溯的 claim 或 evidence，直接跳过该维度，不生成该小节，也不要写任何占位文字。

## 第四章：总结

### SWOT 因素矩阵

先输出 2×2 SWOT 因素总览表：

| S 优势 | W 劣势 |
| --- | --- |
| O 机会 | T 威胁 |

每个象限 3-5 条，绑定 citation_ref。

各象限追问（必须在展开回答中覆盖，而非只列关键词）：

**S 优势** — 基于 evidence_items 回答：
1. 该竞品目前可观察的核心优势是什么？与同类竞品的差距有多大？
2. 这些优势能维持多久？竞品做出有力反应需要多长时间？
3. 是否有证据表明该优势正在减弱或被追赶？

**W 劣势** — 基于 evidence_items 回答：
1. 哪些劣势对该竞品影响最大？是功能缺口、定价问题还是运营短板？
2. 该劣势是否正在被市场机会放大？
3. 补充该劣势需要多大投入和多长时间？（可从公开信息推断）

**O 机会** — 基于 analysis_claims 和 competitor_knowledge 回答：
1. 对该竞品所在赛道，哪些是真正的结构性机会？会持续多久？
2. 该竞品在利用这些机会上有什么优势或劣势？
3. 有哪些机会是该竞品目前明显忽视或覆盖不足的？

**T 威胁** — 基于 analysis_claims 和 evidence_items 回答：
1. 哪些威胁对该竞品是致命的？
2. 面对这些威胁，该竞品可能会怎么做？其他竞品在做什么？
3. 如果无法规避，该竞品最可能的应对路径是什么？

**信息不足的维度绝对不可用编造，不足的地方留白。**

### TOWS 战略矩阵

基于 SWOT 因子交叉配对，输出竞品战略推演矩阵：

|  | O 机会 | T 威胁 |
| --- | --- | --- |
| **S 优势** | **SO 增长型**<br>竞品会如何用优势抢机会？<br>预计推出什么产品或动作？ | **ST 多点型**<br>竞品会如何用优势对冲威胁？<br>是否会分散经营化解风险？ |
| **W 劣势** | **WO 扭转型**<br>机会暴露了竞品哪些可被追的短板？<br>竞品是否已在调整？ | **WT 防御型**<br>竞品哪些短板在威胁面前最脆弱？<br>这些脆弱点是否构成可攻击的突破口？ |

每个格子输出 1-2 条具体战略推演，必须是可观察/可验证的动作，不能写空泛结论。

示例（仅供参考格式与颗粒度）：
假设 Context 中 S: “产品免费额度显著高于同类 [3]”，O: “中小企业对低成本工具的需求在增长 [5]”，则 SO 格应写为：
> **SO 增长型**: 该竞品可能以当前免费额度为钩子，推出面向中小企业的付费升级方案，以低成本获客路径抢占增量市场。[3][5]
不应写为：
> ~~发挥免费优势，抓住中小企业市场机会。~~（空泛，不可验证）

每条绑定 citation_ref。证据不足写”公开证据不足，无法推演”。

### 总结论述
- 基于 TOWS 矩阵，输出一段综合结论。说明核心竞争差异、竞品下一步最可能的战略动作，以及被分析对象相对竞品的关键机会窗口或风险敞口。

不要输出附录。附录将由系统基于 EvidenceItem 自动追加。
所有重要判断必须绑定 citation_ref。不要使用 Context 之外的信息。不要把原始 evidence ID 当作正文引用输出。
"""

    async def _generate_segmented_report(
        self,
        state: CompetitorAnalysisState,
        query: str,
        cfg: Config,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> dict[str, Any]:
        generation = {
            "report": "",
            "errors": [],
            "cost": 0.0,
            "step_costs": {},
            "segment_context_lengths": [],
            "segment_count": 0,
            "fallback_used": False,
        }

        opening_context = self._build_opening_context(
            state,
            citation_refs_by_evidence_id,
        )
        opening = await self._generate_report_segment(
            segment_id="opening",
            query=query,
            context=opening_context,
            custom_prompt=self._opening_prompt(),
            cfg=cfg,
            generation=generation,
        )
        opening = self._clean_opening_segment(opening)
        if not opening:
            generation["fallback_used"] = True
            opening = self._fallback_opening_chapters(
                state,
                citation_refs_by_evidence_id,
            )

        analysis_chapter = await self._generate_dynamic_analysis_chapter_segmented(
            state=state,
            query=query,
            cfg=cfg,
            claims=claims,
            evidence_items=evidence_items,
            analysis_dimensions=analysis_dimensions,
            citation_refs_by_evidence_id=citation_refs_by_evidence_id,
            generation=generation,
        )

        summary_context = self._build_summary_context(
            state,
            claims,
            analysis_dimensions,
            citation_refs_by_evidence_id,
        )
        summary = await self._generate_report_segment(
            segment_id="summary",
            query=query,
            context=summary_context,
            custom_prompt=self._summary_prompt(),
            cfg=cfg,
            generation=generation,
        )
        summary = self._clean_summary_segment(summary)
        if not summary:
            generation["fallback_used"] = True
            summary = self._fallback_summary_chapter(claims, evidence_items)

        generation["report"] = "\n\n".join(
            segment.strip()
            for segment in (opening, analysis_chapter, summary)
            if segment.strip()
        )
        return generation

    async def _generate_dynamic_analysis_chapter_segmented(
        self,
        state: CompetitorAnalysisState,
        query: str,
        cfg: Config,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
        generation: dict[str, Any],
    ) -> str:
        sections = self._dynamic_analysis_sections(
            claims,
            evidence_items,
            analysis_dimensions,
        )
        lines = [
            "## 第三章：竞品分析",
            "",
        ]
        overview = await self._generate_dynamic_analysis_overview_segmented(
            state=state,
            query=query,
            cfg=cfg,
            sections=sections,
            claims=claims,
            citation_refs_by_evidence_id=citation_refs_by_evidence_id,
            generation=generation,
        )
        lines.append(
            overview
            or self._dynamic_analysis_overview_markdown(
                sections,
                claims,
                evidence_items,
                citation_refs_by_evidence_id,
            )
        )
        for section in sections:
            section_claims = self._claims_for_dynamic_section(
                claims,
                section,
                SECTION_CLAIM_LIMIT,
            )
            section_context = self._build_dynamic_section_context(
                state,
                section,
                section_claims,
                citation_refs_by_evidence_id,
            )
            section_body = ""
            if section_claims:
                generated = await self._generate_report_segment(
                    segment_id=f"analysis_{section['id']}",
                    query=query,
                    context=section_context,
                    custom_prompt=self._dynamic_section_prompt(section),
                    cfg=cfg,
                    generation=generation,
                )
                section_body = self._clean_dynamic_section_body(generated)

            if not section_body:
                if section_claims:
                    generation["fallback_used"] = True
                section_lines = self._dynamic_analysis_section_lines(
                    section,
                    section_claims,
                    [],
                )
                lines.extend(["", *section_lines])
            else:
                lines.extend(["", f"### {section['number']} {section['title']}", "", section_body])
        return "\n".join(lines)

    async def _generate_dynamic_analysis_overview_segmented(
        self,
        state: CompetitorAnalysisState,
        query: str,
        cfg: Config,
        sections: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
        generation: dict[str, Any],
    ) -> str:
        context = self._build_dynamic_overview_context(
            state,
            sections,
            claims,
            citation_refs_by_evidence_id,
        )
        generated = await self._generate_report_segment(
            segment_id="analysis_overview",
            query=query,
            context=context,
            custom_prompt=self._dynamic_overview_prompt(),
            cfg=cfg,
            generation=generation,
        )
        overview = self._clean_dynamic_overview_body(generated)
        if overview:
            return overview
        generation["fallback_used"] = True
        return ""

    async def _generate_report_segment(
        self,
        segment_id: str,
        query: str,
        context: str,
        custom_prompt: str,
        cfg: Config,
        generation: dict[str, Any],
    ) -> str:
        generation["segment_count"] += 1
        generation["segment_context_lengths"].append(len(context))
        researcher = _ReportResearcherAdapter(
            query=f"{query}\n\nSegment: {segment_id}",
            context=context,
            cfg=cfg,
            role=self._writer_role_prompt(),
            custom_prompt=custom_prompt,
        )
        generator = self.report_generator_factory(researcher)
        try:
            report = await generator.write_report(custom_prompt=custom_prompt)
        except Exception as exc:
            generation["errors"].append(f"{segment_id}: {exc}")
            return ""

        generation["cost"] += researcher.research_costs
        for step, cost in researcher.step_costs.items():
            generation["step_costs"][step] = generation["step_costs"].get(step, 0.0) + cost
        return (report or "").strip()

    def _report_generator_name(self) -> str:
        return getattr(
            self.report_generator_factory,
            "__name__",
            self.report_generator_factory.__class__.__name__,
        )

    def _opening_prompt(self) -> str:
        return """
请只基于 Context 输出以下 Markdown 片段：

# 竞品分析报告

## 第一章：分析目的
- 写一段完整说明文字，不要写成项目符号。

## 第二章：确定竞品
### 竞品信息卡片
- 为每个竞品输出一个简短信息卡片。

### 竞品分类表格
- 输出 Markdown 表格，推荐列：竞品、产品/品牌、分类、官网、备注、主要引用。

必须保留可用的 citation_ref，例如 [1]。不要输出第三章、第四章或附录。
"""

    def _dynamic_overview_prompt(self) -> str:
        return """
请只基于 Context 输出第三章开头的“### 分析维度总览” Markdown 表格，不要输出任何其他章节。

要求：
1. 第一行必须是“### 分析维度总览”。
2. 由你根据 dynamic_analysis_sections、analysis_claims 和用户问题组织清单文字，不要套用预设产品维度模板。
3. 推荐列：章节、动态维度、证据覆盖、主要竞品、主要引用。
4. 章节编号和动态维度名称必须来自 dynamic_analysis_sections。
5. 证据覆盖和主要引用必须基于 Context 中的 claim/citation_ref；没有引用就写“公开证据不足”。
"""

    def _dynamic_section_prompt(self, section: dict[str, Any]) -> str:
        return f"""
请只基于 Context 输出“{section['number']} {section['title']}”小节正文，不要输出章节标题。

小节必须包含：
1. 一个正式对比表格。
2. 一段对应的分析文字。
3. 表格或段落中保留相关 citation_ref，例如 [1]。
4. 只要 Context 中存在与本动态维度相关、可追溯的 claim，就可以引用；不要因为来源类型不是某类优先来源而弃用。
5. 对间接公开证据生成的结论要保持保守表述，例如“公开资料显示”“间接证据显示”“尚不足以确认完整细节”。
6. 如果 Context 中没有与本动态维度相关的任何 claim 或 evidence，跳过本小节，不要输出任何文字，不要编造。

动态维度：{section['title']}
维度说明：{section['guiding_question']}
"""

    def _summary_prompt(self) -> str:
        return """
请只基于 Context 输出以下 Markdown 片段：

## 第四章：总结

### SWOT 因素矩阵
输出 2×2 SWOT 因素总览表，每格 3-5 条，绑定 citation_ref。需覆盖以下追问：
- S: 核心优势是什么？差距多大？能维持多久？
- W: 哪些劣势影响最大？是否被机会放大？
- O: 哪些是结构性机会？竞品是否忽视？
- T: 哪些威胁致命？竞品可能的应对路径？

### TOWS 战略矩阵

基于 SWOT 因子交叉配对，输出 TOWS 战略矩阵（SO 增长型 / WO 扭转型 / ST 多点型 / WT 防御型）。
每个格子 1-2 条具体战略推演（可观察的动作，不是空泛结论），绑定 citation_ref。
证据不足写"公开证据不足，无法推演"。

### 总结论述
- 输出一段综合结论，说明核心竞争差异、竞品下一步最可能的战略动作及关键机会窗口。

必须保留可用的 citation_ref，例如 [1]。不要输出附录。
"""

    def _clean_opening_segment(self, report: str) -> str:
        return self._truncate_before_any_heading(
            (report or "").strip(),
            ("## 第三章", "## 第四章", "## 附录"),
        ).strip()

    def _clean_summary_segment(self, report: str) -> str:
        segment = (report or "").strip()
        if not segment:
            return ""
        summary_start = segment.find("## 第四章")
        if summary_start >= 0:
            segment = segment[summary_start:]
        return self._truncate_before_any_heading(segment, ("## 附录",)).strip()

    def _clean_dynamic_section_body(self, report: str) -> str:
        body = self._strip_leading_markdown_heading(report)
        if not body:
            return ""
        if any(line.lstrip().startswith("#") for line in body.splitlines()):
            return ""
        return body

    def _clean_dynamic_overview_body(self, report: str) -> str:
        body = (report or "").strip()
        if not body or "### 分析维度总览" not in body:
            return ""
        return self._truncate_before_any_heading(
            body,
            ("### 3.", "## 第四章", "## 附录"),
        ).strip()

    def _truncate_before_any_heading(
        self,
        text: str,
        headings: tuple[str, ...],
    ) -> str:
        cut_at = len(text)
        for heading in headings:
            index = text.find(heading)
            if index >= 0:
                cut_at = min(cut_at, index)
        return text[:cut_at]

    def _build_opening_context(
        self,
        state: CompetitorAnalysisState,
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        payload = {
            "reporting_constraints": [
                "Only write chapters one and two.",
                "Use competitor fields and citation_ref values already attached to competitors.",
                "Use competitors.website as provided; write 公开资料不足 only if website is empty.",
                "Do not guess or replace competitor websites during report writing.",
                "Do not write chapter three, summary, or appendix.",
            ],
            "task": self._task_for_report_context(state, citation_refs_by_evidence_id),
            "competitors": self._compact_competitors_for_context(
                state.get("competitors") or state.get("task", {}).get("competitors", []),
                citation_refs_by_evidence_id,
            ),
        }
        return self._dump_context_with_budget(payload, OPENING_CONTEXT_CHAR_LIMIT)

    def _build_dynamic_section_context(
        self,
        state: CompetitorAnalysisState,
        section: dict[str, Any],
        claims: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        report_evidence_ids = set(citation_refs_by_evidence_id)
        mapped_dimensions = [
            dimension
            for dimension in self._analysis_dimensions(state, [])
            if self._matches_dynamic_section(dimension, section)
        ]
        payload = {
            "reporting_constraints": [
                "Only write this dynamic analysis subsection.",
                "Use the provided claims as the main claim set.",
                "Use citation_ref values like [1] for material claims.",
                "Use any relevant citation-backed claim for this section regardless of source type.",
                "Do not treat source-type preferences as a writing gate; keep indirect-evidence wording conservative.",
                "Do not infer new claims from raw evidence.",
                "If claims are missing, write 公开证据不足.",
            ],
            "task_query": state.get("task", {}).get("query", ""),
            "competitors": self._compact_competitors_for_context(
                state.get("competitors") or state.get("task", {}).get("competitors", []),
                citation_refs_by_evidence_id,
            ),
            "section": {
                "number": section["number"],
                "id": section["id"],
                "title": section["title"],
                "guiding_question": section["guiding_question"],
                "source_dimension_ids": section.get("source_dimension_ids", []),
            },
            "mapped_analysis_dimensions": mapped_dimensions,
            "analysis_claims": [
                self._compact_claim(
                    claim,
                    report_evidence_ids,
                    citation_refs_by_evidence_id,
                )
                for claim in self._fair_sample_claims_by_competitor(
                    claims,
                    SECTION_CLAIM_LIMIT,
                )
            ],
        }
        return self._dump_context_with_budget(payload, SECTION_CONTEXT_CHAR_LIMIT)

    def _build_dynamic_overview_context(
        self,
        state: CompetitorAnalysisState,
        sections: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        report_evidence_ids = set(citation_refs_by_evidence_id)
        payload = {
            "reporting_constraints": [
                "Only write the dynamic analysis overview table.",
                "Use dynamic_analysis_sections as the section set.",
                "Do not use a preset product-dimension checklist.",
                "Use citation_ref values like [1] where available.",
            ],
            "task_query": state.get("task", {}).get("query", ""),
            "competitors": self._compact_competitors_for_context(
                state.get("competitors") or state.get("task", {}).get("competitors", []),
                citation_refs_by_evidence_id,
            ),
            "dynamic_analysis_sections": sections,
            "analysis_claims": [
                self._compact_claim(
                    claim,
                    report_evidence_ids,
                    citation_refs_by_evidence_id,
                )
                for claim in claims[:SUMMARY_CLAIM_LIMIT]
            ],
        }
        return self._dump_context_with_budget(payload, ANALYSIS_OVERVIEW_CONTEXT_CHAR_LIMIT)

    def _build_summary_context(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        report_evidence_ids = set(citation_refs_by_evidence_id)
        payload = {
            "reporting_constraints": [
                "Only write chapter four.",
                "Use claims and citation_ref values like [1].",
                "Do not infer new claims from raw evidence.",
                "Do not write appendix.",
            ],
            "task_query": state.get("task", {}).get("query", ""),
            "competitors": self._compact_competitors_for_context(
                state.get("competitors") or state.get("task", {}).get("competitors", []),
                citation_refs_by_evidence_id,
            ),
            "analysis_dimensions": analysis_dimensions[:15],
            "analysis_claims": [
                self._compact_claim(
                    claim,
                    report_evidence_ids,
                    citation_refs_by_evidence_id,
                )
                for claim in claims[:SUMMARY_CLAIM_LIMIT]
            ],
        }
        return self._dump_context_with_budget(payload, SUMMARY_CONTEXT_CHAR_LIMIT)

    def _fallback_opening_chapters(
        self,
        state: CompetitorAnalysisState,
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        task = state.get("task", {})
        competitors = state.get("competitors") or task.get("competitors", [])
        lines = [
            "# 竞品分析报告",
            "",
            "## 第一章：分析目的",
            "",
            f"本次分析围绕用户提出的问题展开：{task.get('query', '竞品分析')}。报告基于已采集并通过质量检查的公开证据，比较竞品在关键维度上的差异，并保留正文引用编号与附录来源 URL 以便复核。",
            "",
            "## 第二章：确定竞品",
            "",
            "### 竞品信息卡片",
            "",
        ]
        if competitors:
            for competitor in competitors:
                if isinstance(competitor, dict):
                    website = self._competitor_website(competitor)
                    evidence_refs = self._citation_refs_for_evidence_ids(
                        competitor.get("evidence_ids", []),
                        citation_refs_by_evidence_id,
                    )
                    lines.append(f"- **{competitor.get('name', '未知竞品')}**")
                    lines.append(f"  - 产品/品牌：{competitor.get('product', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 官网：{website or '公开资料不足'}")
                    lines.append(f"  - 分类：{competitor.get('category', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 备注：{competitor.get('notes', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 主要引用：{', '.join(evidence_refs) or '公开资料不足'}")
                else:
                    lines.append(f"- **{competitor}**")
        else:
            lines.append("- 公开资料不足。")

        lines.extend(
            [
                "",
                "### 竞品分类表格",
                "",
                "| 竞品 | 产品/品牌 | 分类 | 官网 | 备注 | 主要引用 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        if competitors:
            for competitor in competitors:
                if isinstance(competitor, dict):
                    website = self._competitor_website(competitor)
                    evidence_refs = ", ".join(
                        self._citation_refs_for_evidence_ids(
                            competitor.get("evidence_ids", []),
                            citation_refs_by_evidence_id,
                        )[:3]
                    )
                    lines.append(
                        self._markdown_table_row(
                            [
                                competitor.get("name", "") or "未知竞品",
                                competitor.get("product", "") or "公开资料不足",
                                competitor.get("category", "") or "公开资料不足",
                                website or "公开资料不足",
                                competitor.get("notes", "") or "公开资料不足",
                                evidence_refs or "公开资料不足",
                            ]
                        )
                    )
                else:
                    lines.append(
                        self._markdown_table_row(
                            [
                                competitor,
                                "公开资料不足",
                                "公开资料不足",
                                "公开资料不足",
                                "公开资料不足",
                                "公开资料不足",
                            ]
                        )
                    )
        else:
            lines.append("| 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 |")
        return "\n".join(lines)

    def _fallback_summary_chapter(
        self,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> str:
        evidence_ids = ", ".join(self._ordered_evidence_ids(claims, evidence_items)) or "无"
        return "\n".join(
            [
                "## 第四章：总结",
                "",
                "### SWOT 因素矩阵",
                "",
                "| S 优势 | W 劣势 |",
                "| --- | --- |",
                f"| 基于已接受证据的综合判断。{evidence_ids} | 未覆盖或证据不足的维度需继续补充。 |",
                "",
                "| O 机会 | T 威胁 |",
                "| --- | --- |",
                f"| 可围绕证据充分的差异化维度进一步定位。 | 竞品已有公开信号可能形成竞争压力。{evidence_ids} |",
                "",
                "### TOWS 战略矩阵",
                "",
                "|  | O 机会 | T 威胁 |",
                "| --- | --- | --- |",
                f"| **S 优势** | SO 增长型: 竞品可能以优势领域为核心扩展增量市场。{evidence_ids} | ST 多点型: 竞品可能通过多线布局对冲外部风险。{evidence_ids} |",
                "| **W 劣势** | WO 扭转型: 竞品可能借市场机会调整弱势领域。 | WT 防御型: 竞品弱势领域在外部压力下可能成为突破口。 |",
                "",
                "### 总结论述",
                "",
                "整体来看，当前报告优先呈现已有证据支持的竞争差异；对公开资料不足的维度，结论保持保守，并在附录中保留信息索引以便复核。",
            ]
        )

    def _strip_leading_markdown_heading(self, report: str) -> str:
        lines = (report or "").strip().splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and lines[0].lstrip().startswith("#"):
            lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines).strip()

    def _unique_items_by_id(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique_items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in items:
            item_id = item.get("id", "")
            if item_id:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
            elif item in unique_items:
                continue
            unique_items.append(item)
        return unique_items

    def _compact_competitors_for_context(
        self,
        competitors: list[Any],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> list[Any]:
        compact_competitors = []
        for competitor in competitors:
            if not isinstance(competitor, dict):
                compact_competitors.append(competitor)
                continue
            evidence_ids = competitor.get("evidence_ids", [])
            compact_competitors.append(
                {
                    "name": competitor.get("name", ""),
                    "product": competitor.get("product", ""),
                    "website": self._competitor_website(competitor),
                    "category": competitor.get("category", ""),
                    "notes": competitor.get("notes", ""),
                    "evidence_ids": evidence_ids,
                    "citation_refs": self._citation_refs_for_evidence_ids(
                        evidence_ids,
                        citation_refs_by_evidence_id,
                    ),
                }
            )
        return compact_competitors

    def _task_for_report_context(
        self,
        state: CompetitorAnalysisState,
        citation_refs_by_evidence_id: dict[str, str],
    ) -> dict[str, Any]:
        task = dict(state.get("task", {}) or {})
        competitors = task.get("competitors")
        if isinstance(competitors, list):
            task["competitors"] = self._compact_competitors_for_context(
                competitors,
                citation_refs_by_evidence_id,
            )
        return task

    def _competitor_website(self, competitor: dict[str, Any]) -> str:
        return str(competitor.get("website") or "").strip()

    def _dump_context_with_budget(
        self,
        payload: dict[str, Any],
        max_chars: int,
    ) -> str:
        context = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(context) <= max_chars:
            return context

        compression_steps = [
            {
                "string_chars": 320,
                "excerpt_chars": 320,
                "claim_chars": 320,
                "evidence_limit": 10,
                "claim_limit": 10,
                "competitor_limit": 12,
                "dimension_limit": 10,
            },
            {
                "string_chars": 180,
                "excerpt_chars": 180,
                "claim_chars": 220,
                "evidence_limit": 8,
                "claim_limit": 8,
                "competitor_limit": 8,
                "dimension_limit": 8,
            },
            {
                "string_chars": 100,
                "excerpt_chars": 100,
                "claim_chars": 140,
                "evidence_limit": 5,
                "claim_limit": 5,
                "competitor_limit": 5,
                "dimension_limit": 5,
            },
            {
                "string_chars": 50,
                "excerpt_chars": 60,
                "claim_chars": 80,
                "evidence_limit": 3,
                "claim_limit": 3,
                "competitor_limit": 3,
                "dimension_limit": 3,
            },
        ]

        compressed_payload = payload
        for step in compression_steps:
            compressed_payload = self._compress_context_payload(payload, **step)
            context = json.dumps(compressed_payload, ensure_ascii=False, indent=2)
            if len(context) <= max_chars:
                return context

        minimal_payload = self._minimal_context_payload(compressed_payload)
        return json.dumps(minimal_payload, ensure_ascii=False, indent=2)

    def _compress_context_payload(
        self,
        payload: dict[str, Any],
        *,
        string_chars: int,
        excerpt_chars: int,
        claim_chars: int,
        evidence_limit: int,
        claim_limit: int,
        competitor_limit: int,
        dimension_limit: int,
    ) -> dict[str, Any]:
        return self._compress_context_value(
            payload,
            "",
            string_chars=string_chars,
            excerpt_chars=excerpt_chars,
            claim_chars=claim_chars,
            evidence_limit=evidence_limit,
            claim_limit=claim_limit,
            competitor_limit=competitor_limit,
            dimension_limit=dimension_limit,
        )

    def _compress_context_value(
        self,
        value: Any,
        key: str,
        *,
        string_chars: int,
        excerpt_chars: int,
        claim_chars: int,
        evidence_limit: int,
        claim_limit: int,
        competitor_limit: int,
        dimension_limit: int,
    ) -> Any:
        if isinstance(value, dict):
            return {
                child_key: self._compress_context_value(
                    child_value,
                    child_key,
                    string_chars=string_chars,
                    excerpt_chars=excerpt_chars,
                    claim_chars=claim_chars,
                    evidence_limit=evidence_limit,
                    claim_limit=claim_limit,
                    competitor_limit=competitor_limit,
                    dimension_limit=dimension_limit,
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            value = self._limit_context_list(
                key,
                value,
                evidence_limit=evidence_limit,
                claim_limit=claim_limit,
                competitor_limit=competitor_limit,
                dimension_limit=dimension_limit,
            )
            return [
                self._compress_context_value(
                    item,
                    key,
                    string_chars=string_chars,
                    excerpt_chars=excerpt_chars,
                    claim_chars=claim_chars,
                    evidence_limit=evidence_limit,
                    claim_limit=claim_limit,
                    competitor_limit=competitor_limit,
                    dimension_limit=dimension_limit,
                )
                for item in value
            ]
        if isinstance(value, str):
            return self._truncate_context_string(
                key,
                value,
                string_chars=string_chars,
                excerpt_chars=excerpt_chars,
                claim_chars=claim_chars,
            )
        return value

    def _limit_context_list(
        self,
        key: str,
        value: list[Any],
        *,
        evidence_limit: int,
        claim_limit: int,
        competitor_limit: int,
        dimension_limit: int,
    ) -> list[Any]:
        limits = {
            "profile_evidence_items": evidence_limit,
            "evidence_items": evidence_limit,
            "analysis_claims": claim_limit,
            "competitors": competitor_limit,
            "analysis_dimensions": dimension_limit,
            "guiding_questions": 3,
            "evidence_ids": evidence_limit,
            "citation_refs": evidence_limit,
        }
        limit = limits.get(key)
        if limit is None:
            return value
        return value[:limit]

    def _truncate_context_string(
        self,
        key: str,
        value: str,
        *,
        string_chars: int,
        excerpt_chars: int,
        claim_chars: int,
    ) -> str:
        preserve_keys = {
            "id",
            "citation_ref",
            "source_type",
            "analysis_dimension_id",
            "report_section_id",
            "dimension_id",
            "branch_id",
            "collection_task_id",
            "evidence_review_id",
            "support_status",
            "number",
        }
        if key in preserve_keys:
            return value
        if key == "url":
            return self._truncate_text(value, 300)
        if key == "excerpt":
            return self._truncate_text(value, excerpt_chars)
        if key == "claim":
            return self._truncate_text(value, claim_chars)
        return self._truncate_text(value, string_chars)

    def _minimal_context_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        minimal = {
            "reporting_constraints": payload.get("reporting_constraints", [])[:4],
        }
        for key in ("task_query", "task", "competitors", "section"):
            if key in payload:
                minimal[key] = payload[key]
        for key in (
            "analysis_dimensions",
            "analysis_claims",
            "profile_evidence_items",
            "evidence_items",
        ):
            if key in payload:
                minimal[key] = payload[key][:2] if isinstance(payload[key], list) else payload[key]
        return minimal

    def _truncate_text(self, value: str, max_chars: int) -> str:
        text = " ".join(value.split())
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    def _build_report_context(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        report_evidence_ids = {
            evidence.get("id", "")
            for evidence in evidence_items
            if evidence.get("id")
        }
        payload = {
            "reporting_constraints": [
                "Use analysis_claims as the main claim set.",
                "Use citation_ref values like [1] for material claims in the report body.",
                "Use EvidenceItem.url values as source URLs.",
                "Do not use rejected evidence as support for claims.",
                "Let chapter three dimensions follow the available claims and evidence; do not use a preset product-dimension template.",
                "Do not write the appendix; the system appends the information index.",
            ],
            "dynamic_analysis_sections": self._dynamic_analysis_sections(
                claims,
                evidence_items,
                analysis_dimensions,
            ),
            "task": self._task_for_report_context(state, citation_refs_by_evidence_id),
            "competitors": self._compact_competitors_for_context(
                state.get("competitors") or state.get("task", {}).get("competitors", []),
                citation_refs_by_evidence_id,
            ),
            "industry_direction_plan": state.get("industry_direction_plan", {}),
            "analysis_dimensions": analysis_dimensions,
            "analysis_claims": [
                self._compact_claim(
                    claim,
                    report_evidence_ids,
                    citation_refs_by_evidence_id,
                )
                for claim in claims
            ],
            "competitor_knowledge": state.get("competitor_knowledge", []),
            "evidence_items": [
                self._compact_evidence_item(evidence, citation_refs_by_evidence_id)
                for evidence in evidence_items
            ],
            "evidence_reviews": [
                self._compact_evidence_review(review, report_evidence_ids)
                for review in state.get("evidence_reviews", [])
            ],
            "claim_support_reviews": [
                self._compact_claim_support_review(review)
                for review in state.get("claim_support_reviews", [])
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _supported_claims(
        self,
        claims: list[dict[str, Any]],
        claim_support_reviews: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not claim_support_reviews:
            return claims
        review_by_claim = {
            review.get("claim_id", ""): review
            for review in claim_support_reviews
            if review.get("claim_id")
        }
        filtered = []
        for claim in claims:
            review = review_by_claim.get(claim.get("id", ""), {})
            status = review.get("support_status", "")
            recommended_action = review.get("recommended_action", "")
            if status == "supported" and recommended_action in {"", "accept"}:
                filtered.append(
                    {
                        **claim,
                        "support_status": status,
                        "support_recommended_action": recommended_action or "accept",
                        "support_reviewer_notes": review.get("reviewer_notes", ""),
                    }
                )
        return filtered

    def _analysis_dimensions(
        self,
        state: CompetitorAnalysisState,
        evidence_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        dimensions = state.get("analysis_dimensions", [])
        if dimensions:
            return dimensions

        dimension_by_id: dict[str, dict[str, Any]] = {}
        for evidence in evidence_items:
            dimension_id = self._item_dimension_id(evidence)
            if not dimension_id or dimension_id == "competitor_profile":
                continue
            dimension_by_id[dimension_id] = {
                "id": dimension_id,
                "name": evidence.get("dimension_name") or dimension_id.replace("_", " "),
                "description": "Evidence-derived analysis dimension.",
                "priority": "P1",
                "guiding_questions": [],
            }
        if dimension_by_id:
            return list(dimension_by_id.values())[:10]

        return []

    def _dynamic_analysis_overview_markdown(
        self,
        sections: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
        citation_refs_by_evidence_id: dict[str, str] | None = None,
    ) -> str:
        evidence_items = evidence_items or []
        citation_refs_by_evidence_id = citation_refs_by_evidence_id or {}
        lines = [
            "### 分析维度总览",
            "",
            "| 章节 | 动态维度 | 证据覆盖 | 主要竞品 | 主要引用 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for section in sections:
            section_claims = self._claims_for_dynamic_section(claims, section, 10_000)
            section_evidence = [
                evidence
                for evidence in evidence_items
                if self._matches_dynamic_section(evidence, section)
            ]
            section_evidence_ids = list(
                dict.fromkeys(
                    [
                        evidence_id
                        for claim in section_claims
                        for evidence_id in claim.get("evidence_ids", [])
                        if evidence_id
                    ]
                    + [
                        evidence.get("id", "")
                        for evidence in section_evidence
                        if evidence.get("id")
                    ]
                )
            )
            citation_refs = [
                citation_refs_by_evidence_id[evidence_id]
                for evidence_id in section_evidence_ids
                if evidence_id in citation_refs_by_evidence_id
            ]
            if section_claims:
                coverage = f"{len(section_claims)} 条可追溯 claim"
                if section_evidence:
                    coverage += f"，{len(section_evidence)} 项公开证据"
            elif section_evidence:
                coverage = f"{len(section_evidence)} 项公开证据，需复核"
            else:
                coverage = "公开证据不足"
            lines.append(
                self._markdown_table_row(
                    [
                        section["number"],
                        section["title"],
                        coverage,
                        ", ".join(section.get("competitors", [])) or "综合",
                        "".join(citation_refs[:5]) or "公开证据不足",
                    ]
                )
            )
        if not sections:
            lines.append("| 公开证据不足 | 公开证据不足 | 0 条可追溯 claim | 综合 | 公开证据不足 |")
        return "\n".join(lines)

    def _dynamic_analysis_sections(
        self,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }
        dimension_meta = self._dimension_metadata(
            analysis_dimensions,
            evidence_items,
        )
        dimension_order: list[str] = []
        for claim in claims:
            dimension_id = self._claim_dimension_id(claim, evidence_by_id)
            if dimension_id and dimension_id not in dimension_order:
                dimension_order.append(dimension_id)
        for evidence in evidence_items:
            dimension_id = self._item_dimension_id(evidence)
            if (
                dimension_id
                and dimension_id != "competitor_profile"
                and dimension_id not in dimension_order
            ):
                dimension_order.append(dimension_id)

        sections: list[dict[str, Any]] = []
        for index, dimension_id in enumerate(
            dimension_order[:DYNAMIC_ANALYSIS_SECTION_LIMIT],
            start=1,
        ):
            meta = dimension_meta.get(dimension_id, {})
            title = (
                str(meta.get("name") or "").strip()
                or self._humanize_dimension_id(dimension_id)
            )
            section_claims = [
                claim
                for claim in claims
                if self._claim_dimension_id(claim, evidence_by_id) == dimension_id
            ]
            section_evidence = [
                evidence
                for evidence in evidence_items
                if self._item_dimension_id(evidence) == dimension_id
            ]
            sections.append(
                {
                    "number": f"3.{index}",
                    "id": self._section_id(dimension_id),
                    "title": title,
                    "guiding_question": (
                        str(meta.get("description") or "").strip()
                        or f"基于已有公开证据，对比竞品在“{title}”维度上的表现、差异和可验证信号。"
                    ),
                    "source_dimension_ids": [dimension_id],
                    "competitors": self._section_competitors(
                        section_claims,
                        section_evidence,
                    ),
                }
            )
        return sections

    def _dimension_metadata(
        self,
        analysis_dimensions: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        metadata: dict[str, dict[str, Any]] = {}
        for dimension in analysis_dimensions:
            dimension_id = str(dimension.get("id", "") or "")
            if not dimension_id:
                continue
            metadata[dimension_id] = {
                "name": dimension.get("name") or dimension_id,
                "description": (
                    dimension.get("description")
                    or "；".join(dimension.get("guiding_questions", [])[:2])
                ),
            }
        for evidence in evidence_items:
            dimension_id = self._item_dimension_id(evidence)
            if not dimension_id or dimension_id in metadata:
                continue
            metadata[dimension_id] = {
                "name": evidence.get("dimension_name") or dimension_id,
                "description": "",
            }
        return metadata

    def _claim_dimension_id(
        self,
        claim: dict[str, Any],
        evidence_by_id: dict[str, dict[str, Any]],
    ) -> str:
        dimension_id = str(claim.get("analysis_dimension_id", "") or "")
        if dimension_id and dimension_id != "competitor_profile":
            return dimension_id
        for evidence_id in claim.get("evidence_ids", []):
            evidence = evidence_by_id.get(evidence_id, {})
            evidence_dimension = self._item_dimension_id(evidence)
            if evidence_dimension and evidence_dimension != "competitor_profile":
                return evidence_dimension
        return "evidence_supported_findings"

    def _item_dimension_id(self, item: dict[str, Any]) -> str:
        return str(
            item.get("analysis_dimension_id")
            or item.get("dimension_id")
            or ""
        )

    def _section_competitors(
        self,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        competitors: list[str] = []
        for claim in claims:
            for competitor in claim.get("competitors", []) or []:
                competitor_text = str(competitor)
                if competitor_text and competitor_text not in competitors:
                    competitors.append(competitor_text)
        for evidence in evidence_items:
            competitor_text = str(evidence.get("competitor", "") or "")
            if competitor_text and competitor_text not in competitors:
                competitors.append(competitor_text)
        return competitors

    def _section_id(self, dimension_id: str) -> str:
        cleaned = "".join(
            character if character.isalnum() or character == "_" else "_"
            for character in dimension_id.strip().lower()
        ).strip("_")
        return cleaned or "dynamic_analysis"

    def _humanize_dimension_id(self, dimension_id: str) -> str:
        if dimension_id == "evidence_supported_findings":
            return "证据支持发现"
        text = dimension_id.removeprefix("direction_").replace("_", " ").strip()
        return text.title() if text else "动态分析维度"

    def _compact_claim(
        self,
        claim: dict[str, Any],
        report_evidence_ids: set[str],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> dict[str, Any]:
        evidence_ids = [
            evidence_id
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id in report_evidence_ids
        ]
        return {
            "id": claim.get("id", ""),
            "analysis_dimension_id": claim.get("analysis_dimension_id", ""),
            "knowledge_fact_ids": claim.get("knowledge_fact_ids", []),
            "report_section_id": claim.get("report_section_id", ""),
            "claim_source": claim.get("claim_source", ""),
            "branch_id": claim.get("branch_id", ""),
            "evidence_review_id": claim.get("evidence_review_id", ""),
            "claim": claim.get("claim", ""),
            "competitors": claim.get("competitors", []),
            "evidence_ids": evidence_ids,
            "citation_refs": [
                citation_refs_by_evidence_id[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in citation_refs_by_evidence_id
            ],
            "reasoning": claim.get("reasoning", ""),
            "support_status": claim.get("support_status", ""),
            "support_reviewer_notes": claim.get("support_reviewer_notes", ""),
            "confidence": claim.get("confidence", 0.5),
        }

    def _compact_evidence_item(
        self,
        evidence: dict[str, Any],
        citation_refs_by_evidence_id: dict[str, str],
        excerpt_chars: int = 1200,
    ) -> dict[str, Any]:
        excerpt = " ".join(str(evidence.get("excerpt", "")).split())
        evidence_id = evidence.get("id", "")
        return {
            "id": evidence_id,
            "citation_ref": citation_refs_by_evidence_id.get(evidence_id, ""),
            "competitor": evidence.get("competitor", ""),
            "branch_id": evidence.get("branch_id", ""),
            "collection_task_id": evidence.get("collection_task_id", ""),
            "analysis_dimension_id": evidence.get("analysis_dimension_id", ""),
            "schema_field_ids": evidence.get("schema_field_ids", []),
            "report_section_id": evidence.get("report_section_id", ""),
            "dimension_id": evidence.get("dimension_id", ""),
            "dimension_name": evidence.get("dimension_name", ""),
            "title": evidence.get("title", ""),
            "url": evidence.get("url", ""),
            "source_type": evidence.get("source_type", ""),
            "published_at": evidence.get("published_at"),
            "retrieved_at": evidence.get("retrieved_at", ""),
            "excerpt": excerpt[:excerpt_chars],
            "confidence": evidence.get("confidence", 0.5),
        }

    def _compact_evidence_review(
        self,
        review: dict[str, Any],
        report_evidence_ids: set[str],
    ) -> dict[str, Any]:
        return {
            "id": review.get("id", ""),
            "branch_id": review.get("branch_id", ""),
            "collection_task_id": review.get("collection_task_id", ""),
            "accepted": review.get("accepted", False),
            "score": review.get("score", 0.0),
            "accepted_evidence_ids": [
                evidence_id
                for evidence_id in review.get("accepted_evidence_ids", [])
                if evidence_id in report_evidence_ids
            ],
            "rejected_evidence_count": len(review.get("rejected_evidence_ids", [])),
            "required_action": review.get("required_action", ""),
        }

    def _compact_claim_support_review(self, review: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": review.get("id", ""),
            "claim_id": review.get("claim_id", ""),
            "analysis_dimension_id": review.get("analysis_dimension_id", ""),
            "report_section_id": review.get("report_section_id", ""),
            "support_status": review.get("support_status", ""),
            "recommended_action": review.get("recommended_action", ""),
            "evidence_ids": review.get("evidence_ids", []),
            "knowledge_fact_ids": review.get("knowledge_fact_ids", []),
            "unsupported_phrases": review.get("unsupported_phrases", []),
            "suggested_revision": review.get("suggested_revision", ""),
            "reviewer_notes": review.get("reviewer_notes", ""),
            "confidence": review.get("confidence", 0.5),
        }

    def _report_evidence_items(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence_items = state.get("evidence_items", [])
        evidence_by_id = {
            evidence.get("id", ""): evidence
            for evidence in evidence_items
            if evidence.get("id")
        }
        rejected_ids = {
            evidence_id
            for review in state.get("evidence_reviews", [])
            for evidence_id in review.get("rejected_evidence_ids", [])
        }
        claim_evidence_ids = [
            evidence_id
            for claim in claims
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id in evidence_by_id and evidence_id not in rejected_ids
        ]
        if claim_evidence_ids:
            return [
                evidence_by_id[evidence_id]
                for evidence_id in dict.fromkeys(claim_evidence_ids)
            ]

        accepted_ids = [
            evidence_id
            for review in state.get("evidence_reviews", [])
            for evidence_id in review.get("accepted_evidence_ids", [])
            if evidence_id in evidence_by_id
        ]
        if accepted_ids:
            return [
                evidence_by_id[evidence_id]
                for evidence_id in dict.fromkeys(accepted_ids)
            ]

        return [
            evidence
            for evidence in evidence_items
            if evidence.get("id", "") not in rejected_ids
        ]

    def _ordered_evidence_ids(
        self,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        report_evidence_ids = {
            evidence.get("id", "")
            for evidence in evidence_items
            if evidence.get("id")
        }
        ordered_ids = [
            evidence_id
            for claim in claims
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id in report_evidence_ids
        ]
        ordered_ids.extend(
            evidence.get("id", "")
            for evidence in evidence_items
            if evidence.get("id")
        )
        return list(dict.fromkeys(ordered_ids))

    def _citation_refs_by_evidence_id(
        self,
        evidence_ids: list[str],
    ) -> dict[str, str]:
        return {
            evidence_id: f"[{index}]"
            for index, evidence_id in enumerate(evidence_ids, start=1)
            if evidence_id
        }

    def _ensure_dynamic_analysis_chapter(
        self,
        report: str,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
    ) -> str:
        citation_refs_by_evidence_id = self._citation_refs_by_evidence_id(
            self._ordered_evidence_ids(claims, evidence_items)
        )
        if self._has_dynamic_analysis_chapter_format(report):
            return self._replace_dynamic_analysis_overview(
                report,
                claims,
                evidence_items,
                analysis_dimensions,
                citation_refs_by_evidence_id,
            )

        chapter = self._dynamic_analysis_chapter(
            claims,
            evidence_items,
            analysis_dimensions,
            citation_refs_by_evidence_id,
        ).strip()
        chapter_start = report.find("## 第三章：竞品分析")
        chapter_end = report.find("## 第四章", chapter_start if chapter_start >= 0 else 0)

        if chapter_start >= 0 and chapter_end > chapter_start:
            return (
                report[:chapter_start].rstrip()
                + "\n\n"
                + chapter
                + "\n\n"
                + report[chapter_end:].lstrip()
            )
        if chapter_start >= 0:
            return report[:chapter_start].rstrip() + "\n\n" + chapter
        if chapter_end >= 0:
            return (
                report[:chapter_end].rstrip()
                + "\n\n"
                + chapter
                + "\n\n"
                + report[chapter_end:].lstrip()
            )
        return report.rstrip() + "\n\n" + chapter

    def _has_dynamic_analysis_chapter_format(self, report: str) -> bool:
        if "## 第三章：竞品分析" not in report:
            return False
        return "### 分析维度总览" in report

    def _replace_dynamic_analysis_overview(
        self,
        report: str,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        sections = self._dynamic_analysis_sections(
            claims,
            evidence_items,
            analysis_dimensions,
        )
        overview = self._dynamic_analysis_overview_markdown(
            sections,
            claims,
            evidence_items,
            citation_refs_by_evidence_id,
        ).strip()
        overview_start = report.find("### 分析维度总览")
        if overview_start < 0:
            return report

        chapter_end = report.find("## 第四章", overview_start)
        if chapter_end < 0:
            chapter_end = len(report)
        next_section = report.find("### 3.", overview_start + len("### 分析维度总览"))
        overview_end = next_section if 0 <= next_section < chapter_end else chapter_end
        return (
            report[:overview_start].rstrip()
            + "\n\n"
            + overview
            + "\n\n"
            + report[overview_end:].lstrip()
        )

    def _dynamic_analysis_chapter(
        self,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str] | None = None,
    ) -> str:
        if citation_refs_by_evidence_id is None:
            citation_refs_by_evidence_id = self._citation_refs_by_evidence_id(
                self._ordered_evidence_ids(claims, evidence_items)
            )
        sections = self._dynamic_analysis_sections(
            claims,
            evidence_items,
            analysis_dimensions,
        )
        lines = [
            "## 第三章：竞品分析",
            "",
            self._dynamic_analysis_overview_markdown(
                sections,
                claims,
                evidence_items,
                citation_refs_by_evidence_id,
            ),
        ]
        for section in sections:
            section_claims = self._claims_for_dynamic_section(
                claims,
                section,
                SECTION_CLAIM_LIMIT,
            )
            section_evidence = [
                evidence
                for evidence in evidence_items
                if self._matches_dynamic_section(evidence, section)
            ]
            lines.extend(
                [
                    "",
                    *self._dynamic_analysis_section_lines(
                        section,
                        section_claims,
                        section_evidence,
                    ),
                ]
            )
        if not sections:
            lines.extend(
                [
                    "",
                    "### 3.1 证据覆盖概览",
                    "",
                    "| 动态维度 | 竞品/对象 | 结论 | 引用 |",
                    "| --- | --- | --- | --- |",
                    "| 公开证据不足 | 综合 | 当前缺少可追溯 claim，无法生成动态分析维度。 | 无 |",
                    "",
                    "分析：该报告保留公开证据不足状态，需要补充采集或人工校验后再生成动态维度。",
                ]
            )
        return "\n".join(lines)

    def _dynamic_analysis_section_lines(
        self,
        section: dict[str, Any],
        section_claims: list[dict[str, Any]],
        section_evidence: list[dict[str, Any]],
    ) -> list[str]:
        report_evidence_ids = {
            evidence.get("id", "")
            for evidence in section_evidence
            if evidence.get("id")
        }
        report_evidence_ids.update(
            evidence_id
            for claim in section_claims
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id
        )
        lines = [
            f"### {section['number']} {section['title']}",
            "",
            "| 动态维度 | 竞品/对象 | 结论 | 引用 |",
            "| --- | --- | --- | --- |",
        ]
        if section_claims:
            for claim in section_claims:
                support_label = (
                    "（证据较弱，需复核）"
                    if claim.get("support_status") == "weak"
                    else ""
                )
                lines.append(
                    self._markdown_table_row(
                        [
                            section["title"],
                            ", ".join(claim.get("competitors", [])) or "综合",
                            f"{claim.get('claim', '') or '公开证据不足'}{support_label}",
                            ", ".join(
                                evidence_id
                                for evidence_id in claim.get("evidence_ids", [])
                                if evidence_id in report_evidence_ids
                            )
                            or "无",
                        ]
                    )
                )
            lines.append("")
            lines.append(
                "分析："
                + " ".join(
                    claim.get("claim", "")
                    for claim in section_claims[:3]
                    if claim.get("claim")
                )
            )
        elif section_evidence:
            for evidence in section_evidence[:3]:
                evidence_text = (
                    evidence.get("excerpt")
                    or evidence.get("title")
                    or "公开证据显示该维度存在可复核信息。"
                )
                lines.append(
                    self._markdown_table_row(
                        [
                            section["title"],
                            evidence.get("competitor", "") or "综合",
                            evidence_text,
                            evidence.get("id", "") or "无",
                        ]
                    )
                )
            lines.append("")
            lines.append(
                "分析：该小节仅引用已采集证据中的可观察信息，仍需结合更多公开来源复核竞争差异。"
            )
        else:
            lines.append(
                self._markdown_table_row(
                    [
                        section["title"],
                        "综合",
                        "公开证据不足",
                        "无",
                    ]
                )
            )
            lines.append("")
            lines.append("分析：该动态维度目前缺少足够的公开证据，需要补充采集或人工校验。")
        return lines

    def _claims_for_dynamic_section(
        self,
        claims: list[dict[str, Any]],
        section: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        matched_claims = [
            claim for claim in claims if self._matches_dynamic_section(claim, section)
        ]
        return self._fair_sample_claims_by_competitor(matched_claims, limit)

    def _fair_sample_claims_by_competitor(
        self,
        claims: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or len(claims) <= limit:
            return claims

        grouped_claims: dict[str, list[dict[str, Any]]] = {}
        competitor_order: list[str] = []
        for claim in claims:
            competitor_key = self._claim_competitor_key(claim)
            if competitor_key not in grouped_claims:
                grouped_claims[competitor_key] = []
                competitor_order.append(competitor_key)
            grouped_claims[competitor_key].append(claim)

        sampled_claims: list[dict[str, Any]] = []
        while len(sampled_claims) < limit and any(grouped_claims.values()):
            for competitor_key in competitor_order:
                competitor_claims = grouped_claims[competitor_key]
                if not competitor_claims:
                    continue
                sampled_claims.append(competitor_claims.pop(0))
                if len(sampled_claims) >= limit:
                    break
        return sampled_claims

    def _claim_competitor_key(self, claim: dict[str, Any]) -> str:
        competitors = claim.get("competitors", [])
        if isinstance(competitors, list) and competitors:
            return ", ".join(str(competitor) for competitor in competitors if competitor) or "综合"
        if isinstance(competitors, str) and competitors:
            return competitors
        return "综合"

    def _matches_dynamic_section(
        self,
        item: dict[str, Any],
        section: dict[str, Any],
    ) -> bool:
        source_dimension_ids = set(section.get("source_dimension_ids", []))
        dimension_id = self._item_dimension_id(item)
        if not dimension_id and ("name" in item or "description" in item):
            dimension_id = str(item.get("id", "") or "")
        if dimension_id and dimension_id in source_dimension_ids:
            return True
        if not dimension_id and "evidence_supported_findings" in source_dimension_ids:
            return True
        return False

    def _fallback_report(
        self,
        state: CompetitorAnalysisState,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        analysis_dimensions: list[dict[str, Any]],
    ) -> str:
        task = state.get("task", {})
        competitors = state.get("competitors") or task.get("competitors", [])
        lines = [
            "# 竞品分析报告",
            "",
            "## 第一章：分析目的",
            "",
            f"本次分析围绕用户提出的问题展开：{task.get('query', '竞品分析')}。报告基于已采集并通过质量检查的公开证据，比较竞品在关键维度上的差异，并保留正文引用编号与附录来源 URL 以便复核。",
            "",
            "## 第二章：确定竞品",
            "",
            "### 竞品信息卡片",
            "",
        ]
        if competitors:
            for competitor in competitors:
                if isinstance(competitor, dict):
                    website = self._competitor_website(competitor)
                    lines.append(f"- **{competitor.get('name', '未知竞品')}**")
                    lines.append(f"  - 产品/品牌：{competitor.get('product', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 官网：{website or '公开资料不足'}")
                    lines.append(f"  - 分类：{competitor.get('category', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 备注：{competitor.get('notes', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 主要引用：{', '.join(competitor.get('evidence_ids', [])[:3]) or '公开资料不足'}")
                else:
                    lines.append(f"- **{competitor}**")
        else:
            lines.append("- 公开资料不足。")

        lines.extend(
            [
                "",
                "### 竞品分类表格",
                "",
                "| 竞品 | 产品/品牌 | 分类 | 官网 | 备注 | 主要引用 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        if competitors:
            for competitor in competitors:
                if isinstance(competitor, dict):
                    website = self._competitor_website(competitor)
                    evidence_ids = ", ".join(competitor.get("evidence_ids", [])[:3])
                    lines.append(
                        "| "
                        f"{competitor.get('name', '') or '未知竞品'} | "
                        f"{competitor.get('product', '') or '公开资料不足'} | "
                        f"{competitor.get('category', '') or '公开资料不足'} | "
                        f"{website or '公开资料不足'} | "
                        f"{competitor.get('notes', '') or '公开资料不足'} |"
                        f"{evidence_ids or '公开资料不足'} |"
                    )
                else:
                    lines.append(f"| {competitor} | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 |")
        else:
            lines.append("| 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 |")

        lines.append(
            self._dynamic_analysis_chapter(
                claims,
                evidence_items,
                analysis_dimensions,
            )
        )

        lines.extend(
            [
                "",
                "## 第四章：总结",
                "",
                "### SWOT 因素矩阵",
                "",
                "| S 优势 | W 劣势 |",
                "| --- | --- |",
                f"| 基于已接受证据的综合判断。{', '.join(self._ordered_evidence_ids(claims, evidence_items)) or '无'} | 未覆盖或证据不足的维度需继续补充。 |",
                "",
                "| O 机会 | T 威胁 |",
                "| --- | --- |",
                f"| 可围绕证据充分的差异化维度进一步定位。 | 竞品已有公开信号可能形成竞争压力。{', '.join(self._ordered_evidence_ids(claims, evidence_items)) or '无'} |",
                "",
                "### TOWS 战略矩阵",
                "",
                "|  | O 机会 | T 威胁 |",
                "| --- | --- | --- |",
                f"| **S 优势** | SO 增长型: 竞品可能以优势领域为核心扩展增量市场。{', '.join(self._ordered_evidence_ids(claims, evidence_items)) or '无'} | ST 多点型: 竞品可能通过多线布局对冲外部风险。{', '.join(self._ordered_evidence_ids(claims, evidence_items)) or '无'} |",
                "| **W 劣势** | WO 扭转型: 竞品可能借市场机会调整弱势领域。 | WT 防御型: 竞品弱势领域在外部压力下可能成为突破口。 |",
                "",
                "### 总结论述",
                "",
                "整体来看，当前报告优先呈现已有证据支持的竞争差异；对公开资料不足的维度，结论保持保守，并在附录中保留信息索引以便复核。",
            ]
        )
        return "\n".join(lines)

    def _append_information_index_appendix(
        self,
        report: str,
        claims: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        lines = [
            "",
            "## 附录：信息索引表格",
            "",
            "| 引用标号 | 信息 ID | 关联 Claim ID | 竞品 | 分析维度 | 标题 | 来源类型 | URL | 摘要 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        if evidence_items:
            claim_ids_by_evidence_id = self._claim_ids_by_evidence_id(claims)
            for evidence in evidence_items:
                evidence_id = evidence.get("id", "")
                url = evidence.get("url", "")
                title = evidence.get("title") or url or "Untitled source"
                excerpt = " ".join(str(evidence.get("excerpt", "")).split())[:160]
                lines.append(
                    self._markdown_table_row(
                        [
                            citation_refs_by_evidence_id.get(evidence_id, "无"),
                            evidence_id or "无",
                            ", ".join(claim_ids_by_evidence_id.get(evidence_id, []))
                            or "无",
                            evidence.get("competitor", "") or "综合",
                            evidence.get("dimension_name")
                            or evidence.get("analysis_dimension_id", "")
                            or "未分类",
                            title,
                            evidence.get("source_type", "") or "other",
                            url or "无",
                            excerpt or "无",
                        ]
                    )
                )
        else:
            lines.append("| 无 | 无 | 无 | 无 | 无 | 无 | 无 | 无 | 无 |")
        return f"{report.rstrip()}\n" + "\n".join(lines)

    def _apply_inline_citations(
        self,
        report: str,
        claims: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> str:
        if not citation_refs_by_evidence_id:
            return report

        cited_report = report
        for evidence_id in sorted(citation_refs_by_evidence_id, key=len, reverse=True):
            citation_ref = citation_refs_by_evidence_id[evidence_id]
            cited_report = self._replace_evidence_id_with_citation_ref(
                cited_report,
                evidence_id,
                citation_ref,
            )

        lines = cited_report.splitlines()
        lines = self._append_claim_citations_to_matching_lines(
            lines,
            claims,
            citation_refs_by_evidence_id,
        )
        if not self._contains_any_citation_ref(
            "\n".join(lines),
            citation_refs_by_evidence_id,
        ):
            lines = self._append_first_available_citation_to_body(
                lines,
                citation_refs_by_evidence_id,
            )
        return "\n".join(lines)

    def _replace_evidence_id_with_citation_ref(
        self,
        report: str,
        evidence_id: str,
        citation_ref: str,
    ) -> str:
        import re

        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-]){re.escape(evidence_id)}(?![A-Za-z0-9_-])"
        )
        return pattern.sub(citation_ref, report)

    def _append_claim_citations_to_matching_lines(
        self,
        lines: list[str],
        claims: list[dict[str, Any]],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> list[str]:
        result = list(lines)
        for claim in claims:
            claim_text = " ".join(str(claim.get("claim", "")).split())
            if not claim_text:
                continue
            citation_refs = self._citation_refs_for_evidence_ids(
                claim.get("evidence_ids", []),
                citation_refs_by_evidence_id,
            )
            if not citation_refs:
                continue
            for index, line in enumerate(result):
                compact_line = " ".join(line.split())
                if claim_text in compact_line and not self._line_has_any_ref(
                    line,
                    citation_refs,
                ):
                    result[index] = self._append_refs_to_markdown_line(
                        line,
                        citation_refs,
                    )
        return result

    def _append_first_available_citation_to_body(
        self,
        lines: list[str],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> list[str]:
        result = list(lines)
        citation_ref = next(iter(citation_refs_by_evidence_id.values()), "")
        if not citation_ref:
            return result
        for index, line in enumerate(result):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("|"):
                continue
            result[index] = self._append_refs_to_markdown_line(line, [citation_ref])
            break
        return result

    def _citation_refs_for_evidence_ids(
        self,
        evidence_ids: list[str],
        citation_refs_by_evidence_id: dict[str, str],
    ) -> list[str]:
        return [
            citation_refs_by_evidence_id[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in citation_refs_by_evidence_id
        ]

    def _contains_any_citation_ref(
        self,
        report: str,
        citation_refs_by_evidence_id: dict[str, str],
    ) -> bool:
        return any(
            citation_ref in report
            for citation_ref in citation_refs_by_evidence_id.values()
        )

    def _line_has_any_ref(self, line: str, citation_refs: list[str]) -> bool:
        return any(citation_ref in line for citation_ref in citation_refs)

    def _append_refs_to_markdown_line(
        self,
        line: str,
        citation_refs: list[str],
    ) -> str:
        refs = " ".join(citation_refs)
        if not refs:
            return line
        stripped = line.rstrip()
        if stripped.startswith("|") and stripped.endswith("|"):
            return f"{stripped[:-1].rstrip()} {refs} |"
        return f"{stripped} {refs}"

    def _markdown_table_row(self, values: list[Any]) -> str:
        cells = [self._markdown_table_cell(value) for value in values]
        return "| " + " | ".join(cells) + " |"

    def _markdown_table_cell(self, value: Any) -> str:
        text = " ".join(str(value).split())
        if not text:
            return "无"
        return text.replace("|", "\\|")

    def _claim_ids_by_evidence_id(
        self,
        claims: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        claim_ids_by_evidence_id: dict[str, list[str]] = {}
        for claim in claims:
            claim_id = claim.get("id", "")
            for evidence_id in claim.get("evidence_ids", []):
                if not evidence_id:
                    continue
                claim_ids_by_evidence_id.setdefault(evidence_id, []).append(claim_id)
        return claim_ids_by_evidence_id
