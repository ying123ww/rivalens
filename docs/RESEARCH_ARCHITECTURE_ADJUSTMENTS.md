# Research Architecture Adjustments

本文档记录 Rivalens 当前 research control 的架构取舍。目标是保留端到端证据追溯链路，同时避免把已确认的分析维度再次交给独立 discovery 阶段拆解。

## 当前结论

`CollectionAgent` 只保留一个 active `ResearchTask.search_stage`：

- `focused`: 默认阶段。每个 confirmed competitor x analysis dimension 都直接进入 focused evidence collection。

已删除独立 `landscape` 阶段。维度 ID 由 planning 阶段确认，collection 不再通过 pre-evidence source-universe scan 生成 `LandscapeAssessment`、候选 URL 投影或 split child dimensions。

## 当前实现状态

- `PlanningAgent` 从 L0/L1/L2 行业方向生成并确认 analysis dimensions，写入 `CompetitorAnalysisState.analysis_dimensions`，并映射回固定 10 个报告小节。
- `CollectionAgent` 将 competitor x confirmed dimension 展开成 root branches，所有 root branches 使用 `search_stage=focused`。
- `ResearchEngineEvidenceCollector` 对 focused collection 使用 `ResearchMode.STANDARD_EVIDENCE`，并归一化为 `EvidenceItem`。
- `EvidenceQualityReviewer` 对每次 standard evidence result 做 source-level accept / reject。
- `CoverageReviewer` 负责显式传入的 guiding question / success criteria 覆盖，并把 LLM source-gap advisor 的裁决物化成 gap-driven follow-up tasks；它不再按 dimension id 兜底生成 guiding questions 或 coverage terms。
- `CoverageReviewer` 的 follow-up task 继续使用结构化 `decision_action`、`decision_subtype`、`generated_from_gap`、`target_source_types` 和 `search_stage` 字段。
- `BranchCoverageStateBuilder` 将 root branch 及其 follow-up children 汇总成 `branch_coverage_states`，记录当前 open gap codes、resolved/blocked gap records，并把最终 `coverage_status` 回写到 root branch。
- `ClaimSupportReviewer` 只做 claim-level citation support review，不再通过 collection 专用 verification 通道回到 `source_collection`。

## Collection Loop

```text
PlanningAgent
-> CollectionAgent
   -> ResearchBranch frontier
   -> ResearchBrief / ResearchTask queue
   -> focused evidence collection
   -> EvidenceQualityReviewer
   -> CoverageReviewer
   -> gap-driven focused child branches when budget allows
   -> BranchCoverageStateBuilder
-> KnowledgeStructuringAgent
-> AnalysisAgent
-> ClaimSupportReviewer
-> ReportWriterAgent
-> PublisherAgent
```

## Schema Boundary

Collection state should keep these traceable objects:

- `research_branches`
- `research_briefs`
- `research_tasks`
- `evidence_items`
- `evidence_reviews`
- `coverage_assessments`
- `branch_coverage_states`
- `research_artifacts`
- `agent_events`

There is no `landscape_assessments` state collection. Candidate sources only matter once they are collected as source-backed `EvidenceItem` records.

Collection input fields have separate meanings:

- `success_criteria` are required content coverage criteria for deciding whether a branch can move to analysis.
- `guiding_questions` must be explicit on the branch when question-level coverage is required. `CoverageReviewer` does not keep a dimension-id fallback policy for guiding questions or coverage terms.
- Branch `source_hints` are preferred source targets for initial query building, not hard requirements by themselves.
- An LLM source-gap advisor decides whether the accepted evidence source mix needs targeted follow-up. `CoverageReviewer` records that decision as explicit `SourceCoverageGap` entries. Only those gaps and their follow-up tasks carry `target_source_types`.
- Missing preferred source types do not automatically trigger follow-up collection. Source gaps are opened only by the structured LLM advisor decision; advisor failures do not fall back to the old preferred-source rules.
- Unresolved non-blocking source gaps do not block a branch when the content criteria are satisfied.
- `expected_claim_types` is carried through branch, brief, task, and collection-task payloads as analysis typing context. Collection does not carry an implicit `risk_level`; claim risk is assigned later on `AnalysisClaim.claim_risk_level` and consumed by `ClaimSupportReviewer`.

## Routing Policy

`ResearchRoutingAction` remains a shared routing vocabulary:

- `source_discovery` is still valid for coverage-driven criterion searches and LLM-advised source coverage follow-up.
- `stop` records sufficient coverage or budget-limited stopping conditions.

The stage boundary is not the routing action. Consumers should read `ResearchTask.search_stage` and `CoverageAssessment.stage_contract` for collection state; the active collection path is focused evidence collection.

## Traceability Rule

Important analysis claims must bind to accepted `EvidenceItem.id` values and source URLs. Coverage gaps can trigger more collection, but they are not evidence by themselves.
