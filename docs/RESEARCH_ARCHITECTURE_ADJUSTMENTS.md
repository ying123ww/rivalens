# Research Architecture Adjustments

本文档记录 Rivalens 当前 research control 的架构取舍。目标是保留端到端证据追溯链路，同时避免把已确认的分析维度再次交给独立 discovery 阶段拆解。

## 当前结论

`CollectionAgent` 只保留两个 `ResearchTask.search_stage`：

- `focused`: 默认阶段。每个 confirmed competitor x analysis dimension 都直接进入 focused evidence collection。
- `verification`: 由 `ClaimSupportReviewer` 针对 weak / unverifiable claim 生成的一次性 claim-driven verification pass。

已删除独立 `landscape` 阶段。维度 ID 由 planning 阶段确认，collection 不再通过 pre-evidence source-universe scan 生成 `LandscapeAssessment`、候选 URL 投影或 split child dimensions。

## 当前实现状态

- `PlanningAgent` 生成并确认 10 个 analysis dimensions，写入 `CompetitorAnalysisState.analysis_dimensions`。
- `CollectionAgent` 将 competitor x confirmed dimension 展开成 root branches，所有 root branches 使用 `search_stage=focused`。
- `ResearchEngineEvidenceCollector` 对 focused 和 verification 都使用 `ResearchMode.STANDARD_EVIDENCE`，并归一化为 `EvidenceItem`。
- `EvidenceQualityReviewer` 对每次 standard evidence result 做 source-level accept / reject。
- `CoverageReviewer` 负责 expected source type、guiding question 覆盖和 gap-driven follow-up tasks。
- `CoverageReviewer` 的 follow-up task 继续使用结构化 `decision_action`、`decision_subtype`、`generated_from_gap`、`target_source_types` 和 `search_stage` 字段。
- `ClaimSupportReviewer` 可以生成 bounded `verification_task_queue`，由 LangGraph conditional edge 回到 `source_collection` 执行 verification。

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
-> KnowledgeStructuringAgent
-> AnalysisAgent
-> ClaimSupportReviewer
   -> optional verification_task_queue
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
- `research_artifacts`
- `agent_events`

There is no `landscape_assessments` state collection. Candidate sources only matter once they are collected as source-backed `EvidenceItem` records.

## Routing Policy

`ResearchRoutingAction` remains a shared routing vocabulary:

- `source_discovery` is still valid for coverage-driven missing source type searches.
- `claim_verification` is used for verification tasks.
- `stop` records sufficient coverage or budget-limited stopping conditions.

The stage boundary is not the routing action. Consumers should read `ResearchTask.search_stage` and `CoverageAssessment.stage_contract` to distinguish focused evidence collection from claim verification.

## Traceability Rule

Important analysis claims must bind to accepted `EvidenceItem.id` values and source URLs. Coverage gaps can trigger more collection, but they are not evidence by themselves.
