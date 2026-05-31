"""Report writer for structured competitor analysis output."""

import json
from typing import Any, Callable

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState
from rivalens.research.config import Config
from rivalens.research.prompts import get_prompt_family
from rivalens.research.skills.writer import ReportGenerator
from rivalens.research.utils.enum import ReportSource, ReportType, Tone


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
        researcher = _ReportResearcherAdapter(
            query=query,
            context=context,
            cfg=cfg,
            role=self._writer_role_prompt(),
            custom_prompt=custom_prompt,
        )
        generator = self.report_generator_factory(researcher)

        generation_error = None
        try:
            generated_report = await generator.write_report(custom_prompt=custom_prompt)
        except Exception as exc:
            generated_report = ""
            generation_error = str(exc)
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
                        "report_generator": generator.__class__.__name__,
                        "report_type": researcher.report_type,
                        "report_source": researcher.report_source,
                        "prompt_family": researcher.prompt_family.__class__.__name__,
                        "context_length": len(context),
                        "custom_prompt_length": len(custom_prompt),
                        "model": getattr(cfg, "smart_llm_model", None),
                        "token_limit": getattr(cfg, "smart_token_limit", None),
                    },
                    "output": {
                        "generated_report_length": generated_report_length,
                        "report_length": report_length,
                        "fallback_used": not bool(generated_report),
                        "cost": researcher.research_costs,
                        "step_costs": researcher.step_costs,
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
        dimension_lines = "\n".join(
            f"- 3.{index} {dimension.get('name', dimension.get('id', ''))}: "
            f"{dimension.get('description', '')}"
            for index, dimension in enumerate(analysis_dimensions, start=1)
        )
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
- 如果字段由公开证据推导，必须展示对应 citation_ref，例如 [1]；不要无证据扩写。

### 竞品分类表格
- 输出 Markdown 表格。
- 推荐列：竞品、产品/品牌、分类、官网、备注、主要证据 ID。

## 第三章：竞品分析
必须按以下 10 个小节输出，每个小节都必须包含：
1. 一个正式对比表格。
2. 一段对应的分析文字。
3. 表格或段落中要保留相关 citation_ref，例如 [1]。

固定 10 个小节如下：
{dimension_lines}

## 第四章：总结
### SWOT 分析矩阵
- 输出 SWOT 分析矩阵表。
- 如果 Context 没有显式 SWOT，请基于 analysis_claims、competitor_knowledge 和 evidence_items 综合归纳。
- 不足的信息写“公开证据不足”，不要编造。

### 总结论述
- 输出一段综合结论。
- 必须说明主要竞争差异、机会和风险。

不要输出附录。附录将由系统基于 EvidenceItem 自动追加。
所有重要判断必须绑定 citation_ref。不要使用 Context 之外的信息。不要把原始 evidence ID 当作正文引用输出。
"""

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
                "Do not write the appendix; the system appends the information index.",
            ],
            "task": state.get("task", {}),
            "competitors": state.get("competitors")
            or state.get("task", {}).get("competitors", []),
            "active_knowledge_schema": state.get("active_knowledge_schema", {}),
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
            evidence_ids = claim.get("evidence_ids", []) or review.get("evidence_ids", [])
            if status == "supported" or (status == "weak" and evidence_ids):
                filtered.append(
                    {
                        **claim,
                        "support_status": status,
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
            dimension_id = evidence.get("dimension_id", "")
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

        fallback_names = [
            "战略定位",
            "目标用户",
            "产品能力",
            "定价与商业模式",
            "市场与增长",
            "渠道与分发",
            "客户案例与口碑",
            "技术与集成",
            "合规与风险",
            "竞争壁垒",
        ]
        return [
            {
                "id": f"fallback_dimension_{index}",
                "name": name,
                "description": "搜索阶段维度计划缺失，使用默认报告维度。",
                "priority": "P1",
                "guiding_questions": [],
            }
            for index, name in enumerate(fallback_names, start=1)
        ]

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
            "dimension": claim.get("dimension", ""),
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
    ) -> dict[str, Any]:
        excerpt = " ".join(str(evidence.get("excerpt", "")).split())
        evidence_id = evidence.get("id", "")
        return {
            "id": evidence_id,
            "citation_ref": citation_refs_by_evidence_id.get(evidence_id, ""),
            "competitor": evidence.get("competitor", ""),
            "branch_id": evidence.get("branch_id", ""),
            "collection_task_id": evidence.get("collection_task_id", ""),
            "dimension_id": evidence.get("dimension_id", ""),
            "dimension_name": evidence.get("dimension_name", ""),
            "title": evidence.get("title", ""),
            "url": evidence.get("url", ""),
            "source_type": evidence.get("source_type", ""),
            "published_at": evidence.get("published_at"),
            "retrieved_at": evidence.get("retrieved_at", ""),
            "excerpt": excerpt[:1200],
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
            "support_status": review.get("support_status", ""),
            "evidence_ids": review.get("evidence_ids", []),
            "unsupported_phrases": review.get("unsupported_phrases", []),
            "verification_task_count": len(review.get("required_follow_up_tasks", [])),
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
                    lines.append(f"- **{competitor.get('name', '未知竞品')}**")
                    lines.append(f"  - 产品/品牌：{competitor.get('product', '公开资料不足') or '公开资料不足'}")
                    lines.append(f"  - 官网：{competitor.get('website', '公开资料不足') or '公开资料不足'}")
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
                    evidence_ids = ", ".join(competitor.get("evidence_ids", [])[:3])
                    lines.append(
                        "| "
                        f"{competitor.get('name', '') or '未知竞品'} | "
                        f"{competitor.get('product', '') or '公开资料不足'} | "
                        f"{competitor.get('category', '') or '公开资料不足'} | "
                        f"{competitor.get('website', '') or '公开资料不足'} | "
                        f"{competitor.get('notes', '') or '公开资料不足'} |"
                        f"{evidence_ids or '公开资料不足'} |"
                    )
                else:
                    lines.append(f"| {competitor} | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 |")
        else:
            lines.append("| 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 | 公开资料不足 |")

        lines.extend(["", "## 第三章：竞品分析"])
        for index, dimension in enumerate(analysis_dimensions[:10], start=1):
            dimension_id = dimension.get("id", "")
            dimension_claims = [
                claim
                for claim in claims
                if claim.get("dimension") == dimension_id
            ]
            lines.extend(
                [
                    "",
                    f"### 3.{index} {dimension.get('name', dimension_id)}",
                    "",
                    "| 对比项 | 竞品/对象 | 结论 | 引用 |",
                    "| --- | --- | --- | --- |",
                ]
            )
            if dimension_claims:
                for claim in dimension_claims:
                    support_label = (
                        "（证据较弱，需复核）"
                        if claim.get("support_status") == "weak"
                        else ""
                    )
                    lines.append(
                        "| "
                        f"{dimension.get('name', dimension_id)} | "
                        f"{', '.join(claim.get('competitors', [])) or '综合'} | "
                        f"{claim.get('claim', '') or '公开证据不足'}{support_label} | "
                        f"{', '.join(claim.get('evidence_ids', [])) or '无'} |"
                    )
                lines.append("")
                lines.append(
                    " ".join(claim.get("claim", "") for claim in dimension_claims[:3])
                )
            else:
                lines.append(
                    f"| {dimension.get('name', dimension_id)} | 综合 | 公开证据不足 | 无 |"
                )
                lines.append("")
                lines.append("该维度目前缺少足够的公开证据，需要补充采集或人工校验。")

        lines.extend(
            [
                "",
                "## 第四章：总结",
                "",
                "### SWOT 分析矩阵",
                "",
                "| 类型 | 内容 | 引用 |",
                "| --- | --- | --- |",
                "| Strengths 优势 | 基于已接受证据，部分竞品已形成可观察的公开竞争信号。 | "
                f"{', '.join(self._ordered_evidence_ids(claims, evidence_items)) or '无'} |",
                "| Weaknesses 劣势 | 未覆盖或证据不足的维度需要继续补充。 | 无 |",
                "| Opportunities 机会 | 可围绕证据充分的差异化维度进一步定位产品机会。 | 无 |",
                "| Threats 威胁 | 竞品已有公开定位、定价、客户或能力信号，可能形成直接竞争压力。 | "
                f"{', '.join(self._ordered_evidence_ids(claims, evidence_items)) or '无'} |",
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
                            or evidence.get("dimension_id", "")
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
