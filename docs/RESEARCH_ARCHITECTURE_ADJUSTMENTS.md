# Research Architecture Adjustments

本文档给出 Rivalens 现有结构与 Anthropic-style multi-agent research control 的最佳融合方案。目标不是重写系统，而是在保留 Rivalens 证据追溯链路的前提下，修正当前 research tree 容易被粗糙 subquery 放大的问题。

参考：

- Anthropic, "How we built our multi-agent research system": https://www.anthropic.com/engineering/multi-agent-research-system
- Local reference: `AdvancedResearch/`
- Current Rivalens paths:
  - `rivalens/workflows/competitive_analysis.py`
  - `rivalens/agents/planning.py`
  - `rivalens/agents/collection.py`
  - `rivalens/agents/evidence_review.py`
  - `rivalens/agents/coverage_review.py`
  - `rivalens/agents/knowledge_structuring.py`
  - `rivalens/agents/analysis.py`
  - `rivalens/agents/writing.py`
  - `rivalens/schema/competitive.py`

## 核心结论

最佳融合点不是在现有 workflow 外面再套一个完整 deep research agent，而是改造 `CollectionAgent` 内部的 research control，并调整 collection 之后的 agent 顺序。

## 当前实现状态

当前代码已落地以下调整：

- `source_collection -> knowledge_structuring -> dimension_analysis -> claim_support_review -> report_writer` 的主链路。
- `ClaimSupportReviewer` 作为 claim-level support gate，输出 `ClaimSupportReview` 和一次性的 `verification_task_queue`。
- `claim_support_review` 可通过 LangGraph conditional edge 回到 `source_collection` 执行 claim-driven `verification` 搜索阶段。
- `CollectionAgent` 区分 initial/gap collection 与 verification pass，verification pass 只消费 `verification_task_queue`，不会重建 root branches。
- landscape 不再使用 `next_action` 兜底；`LandscapeAssessment.decision` 是 landscape routing 控制字段。
- landscape 的 query refinement、competitor disambiguation、dimension decomposition 不再直接吞掉；已转为带血缘的后续 task。
- `ResearchTask.parent_task_id` 已贯通 landscape/focused/split follow-up 任务，便于回放阶段衔接。
- landscape candidate source 会写入 `target_urls`，对应 focused child task 下推为 `ResearchEngine.source_urls` 定向 URL 抽取。
- `competitor_disambiguation` 会生成专用 follow-up task，而不是落回通用 refinement。
- `dimension_split_suggestions` 会生成 split child dimensions，例如 `competitive_moat.switching_cost`。
- landscape follow-up allocator 会在固定预算内保留 best candidate URL 和高优先级 missing source type，避免简单 `specs[:3]` 挤掉关键补采。
- 6 类 action 已降级为通用 `ResearchRoutingDecision` taxonomy：`scope_refinement`、`entity_resolution`、`source_discovery`、`evidence_extraction`、`claim_verification`、`stop`；landscape 和 focused 都可使用，follow-up specs 也携带 `decision_action` 和 `decision_subtype`。
- `coverage_gap_search` 已用于 coverage review 产生的补采 task；landscape depth/branch budget 阻断扩展时会显式记录 `stop / budget_stop`。
- `ResearchEngineEvidenceCollector` 不再暴露 `deep=True/False`；调用方显式传入 `ResearchMode`。landscape 使用 `SOURCE_DISCOVERY`，focused 和 verification 使用 `STANDARD_EVIDENCE`。

原始问题是：

```text
PlanningAgent
-> CollectionAgent
-> AnalysisAgent
-> KnowledgeStructuringAgent
-> ReportWriterAgent
-> PublisherAgent
```

目标演进为：

```text
PlanningAgent / Schema Architect
-> CollectionAgent
   ├─ ResearchTaskPlanner
   ├─ EvidenceCollector
   ├─ EvidenceSourceReviewer
   ├─ CoverageReviewer
   └─ gap-driven follow-up loop
-> KnowledgeStructuringAgent
-> DimensionAnalysisAgent
-> ClaimSupportReviewer
-> ReportWriterAgent
-> FinalQAAgent
-> PublisherAgent
```

关键变化：

- 保留 `PlanningAgent` 作为当前的 Schema Architect 基础。
- 保留 `CollectionAgent` 对搜索和证据采集的唯一所有权。
- 把“覆盖率自检”前移到 collection 内部，发生在 analysis 之前。
- 删除“分析后才发现覆盖率不足再粗暴回采”的结构。
- 删除 `BranchReviewAgent`，由 `CoverageReviewer` 输出补采任务，由 `CollectionAgent` 直接执行 depth/budget guard。
- 将 `EvidenceQualityReviewer` 从 pass/fail 质检升级为 source-level + coverage-level review。
- 将 `AnalysisAgent` 移到 `KnowledgeStructuringAgent` 之后，让分析消费结构化知识和证据，而不是只基于 accepted evidence 生成浅 claim。
- 新增 `ClaimSupportReviewer`，在写作前做 claim-level citation verification。
- 终审 `FinalQAAgent` 只做格式、覆盖和溯源完整性检查，不再承担主要事实校验。

## 当前结构的问题

### 1. Root branch 覆盖强，但 query 容易粗

`PlanningAgent` 已经生成 10 个确认维度，`CollectionAgent` 再展开为 `competitor x dimension` root branches。这保证了覆盖，但每个维度只有一个 schema-aware query。粗 query 会导致粗搜索，后续 coverage review 只能在粗结果上补救。

问题位置：

```text
PlanningAgent._build_analysis_dimensions
CollectionAgent._build_root_branches
CollectionAgent._schema_aware_query
```

### 2. Evidence review 过早承担“完成判断”

`EvidenceQualityReviewer` 当前主要判断 evidence 是否有 URL、competitor/dimension 是否匹配、source count 是否足够。它适合做 source-level filter，但不适合作为 branch 是否研究充分的唯一依据。

应保留：

- `missing_source_url`
- `competitor_mismatch`
- `dimension_mismatch`
- accepted/rejected evidence ids

应新增：

- expected source type coverage
- guiding question coverage
- missing questions
- contradiction signals
- next action

### 3. Branch decision 和 coverage decision 不应并存

旧结构里 `BranchReviewAgent` 根据 gap code 生成 child query，并返回 `expand/retry/stop`。引入 `CoverageReviewer` 后，如果继续保留 branch decision，会出现两个控制面：

- `CoverageAssessment.next_action`
- branch-level `expand/retry/stop`

这会让系统难以解释“到底是谁决定补采”。因此应删除 `BranchReviewAgent`，把决策收敛到：

```text
CoverageReviewer:
  输出 missing_source_types、missing_questions、next_action、follow_up_task_specs。

CollectionAgent:
  直接执行 max_depth、max_expansion_branches、root hard limit 等 guard。
```

注意：这里的 `next_action` 只保留在 focused evidence coverage loop。landscape 阶段不再读取或回退到 `next_action`，只读取 `LandscapeAssessment.decision`。

### 4. AnalysisAgent 在 KnowledgeStructuringAgent 前运行

当前 workflow 是：

```text
source_collection -> dimension_analysis -> knowledge_structuring
```

但 `AnalysisAgent` 代码里实际尝试读取 `knowledge_structuring` 的 schema message；由于它运行在 knowledge 之前，通常只能走 accepted evidence fallback，生成的 claim 会比较浅。

建议改为：

```text
source_collection -> knowledge_structuring -> dimension_analysis
```

这样 `AnalysisAgent` 能消费：

- accepted evidence
- evidence reviews
- coverage assessments
- competitor knowledge
- analysis dimensions

分析质量会更接近“逐维度对比”，而不是“这个 branch 有 accepted evidence”。

## 与目标产品流程的最佳融合

用户目标流程：

```text
[用户输入]
-> [Intent Parser]
-> [Competitor Discovery Agent]
-> [Competitor Classifier]
-> [用户确认竞品]
-> [Schema Architect]
-> [用户确认维度]
-> [采集Agent × N]
-> [分析Agent]
-> [覆盖率自检]
-> [综合分析Agent]
-> [写作Agent]
-> [质检Agent]
-> [输出]
```

建议调整为：

```text
[用户输入]
  │
  ▼
[Intent Parser]
  │
  ▼
[Competitor Discovery Agent]  条件触发
  │
  ▼
[Competitor Classifier]
  │
  ▼
[用户确认竞品]
  │
  ▼
[Schema Architect / PlanningAgent]
  │ 生成维度、guiding questions、expected source types、minimum coverage
  ▼
[用户确认维度]
  │
  ▼
[CollectionAgent]
  ├─ [ResearchTaskPlanner] 按需生成 landscape / focused tasks
  ├─ [采集Agent × N] 并行采集 EvidenceItem
  ├─ [EvidenceSourceReviewer] 过滤坏证据
  ├─ [CoverageReviewer] 判断维度覆盖和缺口
  └─ 不合格？生成 gap-driven follow-up tasks，继续采集
  │
  ▼
[KnowledgeStructuringAgent]
  │
  ▼
[DimensionAnalysisAgent]
  │ 逐维度对比，生成 AnalysisClaim[] 和 section summaries
  ▼
[ClaimSupportReviewer]
  │ weak / contradicted / unverifiable 可触发 verification task
  ▼
[SynthesisAnalysisAgent]
  │ SWOT / 优缺点 / 结论 / 预测
  ▼
[ReportWriterAgent]
  │
  ▼
[FinalQAAgent]
  │ 格式、覆盖率、溯源附录、claim support 状态
  ▼
[PublisherAgent]
```

最重要的移动：

```text
覆盖率自检
```

从 analysis 之后移动到 collection 内部。原因是覆盖率不足是“研究没采够”，不是“分析没写好”。越晚发现，补救成本越高。

## 保留、删除、降级

### 保留

#### `PlanningAgent`

保留为当前的 Schema Architect 基础。它已经负责：

- competitor normalization
- active schema selection
- 10 个 analysis dimensions
- dimension confirmation artifact

建议扩展：

```text
AnalysisDimension:
  expected_source_types
  minimum_coverage
  risk_level
  expected_claim_types
```

#### `CollectionAgent`

保留为唯一搜索所有者。所有 web search、ResearchEngine 调用、evidence ID 分配仍在这里发生。

它是最佳融合点，因为当前它已经拥有：

- root branch frontier
- collection task creation
- concurrent evidence collection
- EvidenceQualityReviewer
- CoverageReviewer
- research artifacts
- agent_events

#### `EvidenceItem -> EvidenceReviewResult -> AnalysisClaim`

保留这条追溯链。所有新增结构都必须挂在这条链上，不能绕过 `rivalens/schema/competitive.py`。

### 删除或移动

#### 删除“分析后覆盖率自检”作为主闭环

不建议采用：

```text
采集 -> 分析 -> 覆盖率自检 -> 回采
```

应改为：

```text
采集 -> source review -> coverage review -> gap follow-up -> 采集完成 -> 分析
```

分析阶段可以发现 claim 证据不足，但那属于 claim verification，不是普通覆盖率自检。

#### 调整 `AnalysisAgent` 顺序

建议把 workflow 从：

```text
source_collection -> dimension_analysis -> knowledge_structuring
```

改成：

```text
source_collection -> knowledge_structuring -> dimension_analysis
```

这会让 `AnalysisAgent` 真正使用结构化知识，而不是只能基于 evidence review fallback。

### 删除

#### `BranchReviewAgent`

删除。它的原有职责拆分为：

```text
CoverageReviewer:
  - gap detection
  - next_action
  - follow_up_task_specs

CollectionAgent:
  - max_depth guard
  - max_expansion_branches guard
  - root branch hard limit
  - task queue execution
```

#### 终审 `质检Agent`

不负责主要事实校验。主要事实校验前移为：

```text
EvidenceSourceReviewer / CoverageReviewer / ClaimSupportReviewer
```

终审只做 packaging QA：

- 结构是否完整。
- 用户确认维度是否全部覆盖。
- 是否存在无 evidence 的重要 claim。
- 溯源附录是否完整。
- weak/unverifiable claim 是否被标注或移除。

## CollectionAgent 内部新结构

建议 `CollectionAgent` 内部从当前：

```text
build_root_branches
-> collect
-> evidence_review
-> coverage_review
-> child_branches
```

演进为：

```text
build_root_branches
-> build_research_briefs
-> plan_research_tasks
-> collect tasks concurrently
-> source_review
-> coverage_review
-> if gaps and budget remains: plan follow-up tasks
-> finalize accepted evidence
```

### ResearchBrief

一个 `ResearchBrief` 对应一个 competitor × dimension 的研究目标。

```text
ResearchBrief:
  id
  branch_id
  competitor
  dimension_id
  dimension_name
  objective
  guiding_questions
  expected_source_types
  minimum_coverage
  effort_level: low | medium | high
  source_policy
  stop_condition
  rationale
```

### ResearchTask

一个 `ResearchBrief` 可以生成多个 `ResearchTask`。

```text
ResearchTask:
  id
  brief_id
  parent_task_id
  branch_id
  competitor
  dimension_id
  search_stage: landscape | focused | verification
  objective
  query
  expected_source_types
  generated_from_gap
  reason
  drift_risk
```

### Search stage policy

`landscape`、`focused`、`verification` 不应实现成固定三轮。它们应只是 `ResearchTask.search_stage` 的类型，由 `ResearchTaskPlanner` 按需选择。

```text
search_stage = landscape | focused | verification
```

推荐策略：

```text
focused:
  默认阶段。大多数 competitor × dimension 直接从 focused collection 开始。
  适合 source intent 明确的维度，例如 pricing、docs、security、reviews、marketplace。

landscape:
  可选 reconnaissance。只在 source universe 不清楚、行业/竞品较新、维度边界模糊、
  或用户问题很开放时触发。
  目标不是产出最终 claims，而是发现 source types、关键词、潜在线索和需要拆分的问题。

verification:
  claim-driven follow-up。只在 ClaimSupportReviewer 发现 weak、contradicted、
  unverifiable claims 时触发。
  目标是验证具体 claim，而不是扩大普通覆盖率。
```

因此不要写成：

```text
Round 0 landscape -> Round 1 focused -> Round 2 verification
```

应该写成：

```text
ResearchTaskPlanner chooses task stage:
  if source universe unclear -> landscape
  elif normal dimension collection -> focused
  elif claim support failed -> verification
```

这样既保留 Anthropic 的 start wide, then narrow 思路，也避免每个维度都机械跑三轮导致成本膨胀。

### Landscape assessment policy

`landscape` 是 source-universe discovery，不是 claim-ready evidence collection。

实现规则：

```text
Landscape task:
  -> run search for candidate source entrances
  -> LandscapeReviewer
  -> LandscapeAssessment
  -> follow_up_task_specs
  -> focused ResearchTask
```

Landscape 结果不进入 `EvidenceItem`，也不进入 `accepted_evidence_ids`。它只保存为：

```text
LandscapeAssessment:
  stage_contract(search_stage=landscape, produces_evidence=false)
  candidate_sources
  discovered_source_types
  missing_source_types
  source_universe_confidence
  competitor_disambiguation
  dimension_split_suggestions
  decision
  query_refinements
  follow_up_task_specs
  focused_task_specs        # compatibility alias
  split_task_specs
  selected_follow_up_specs
  decision_candidates
  arbitration
  user_visible_summary
```

`ResearchRoutingDecision` 使用六类动作，可被 landscape 和 focused 共用：

```text
scope_refinement     -> query_refinement / dimension_decomposition
entity_resolution    -> competitor_disambiguation
source_discovery     -> source_type_search / coverage_gap_search
evidence_extraction  -> targeted_url_extract
claim_verification   -> evidence_check
stop                 -> budget_stop / sufficient_stop / no_viable_followup
```

注意：`ResearchRoutingAction` 是共享路由词汇，不是阶段边界。阶段边界由
`search_stage` 和 `stage_contract` 表达：landscape 是 source-universe control
plane，`produces_evidence=false`；focused / verification 是 evidence plane，
`produces_evidence=true`。

原因：landscape 的输出是“信息入口”和“后续采集计划”，不是最终证据。只有后续 focused collection 深采后的内容才可以变成 `EvidenceItem` 并被 analysis 使用。

用户侧应展示：

```text
信息入口发现：
  - discovered source types
  - candidate source URLs
  - missing source types
  - competitor disambiguation status

后续采集计划：
  - follow_up_task_specs
```

不要把 landscape candidate sources 放入证据附录，除非它们已经通过 focused collection 转成 `EvidenceItem`。

`landscape_assessments` 是 routing decision 的唯一真源。`research_artifacts`
里的 landscape artifact 只保存可回放的轻量诊断投影，包括 observation、routing
和 `landscape_assessment_id` replay reference；不要从 artifact 反推或重新计算
workflow 决策。

`LandscapeAssessment.decision` 由 `decision_candidates` 规则评分映射产生，而不是
固定 `if/else` 优先级链。每个 candidate 记录 action、subtype、score、reasons
和关联 follow-up specs；`arbitration.method` 记录当前仲裁方式，例如
`rules_scorecard`。

### CoverageAssessment

`CoverageAssessment` 是 focused collection 的 evidence-quality + coverage observation。它保留 `next_action` 作为兼容摘要字段，但 focused 后续控制由同一套 `ResearchRoutingDecision` 字段表达：`decision_candidates`、`arbitration`、`decision`、`selected_follow_up_specs`。

```text
source_discovery -> coverage_gap_search
```

```text
CoverageAssessment:
  id
  stage_contract(search_stage=focused|verification, produces_evidence=true)
  branch_id
  brief_id
  research_task_ids
  accepted_evidence_ids
  rejected_evidence_ids
  found_source_types
  missing_source_types
  covered_questions
  missing_questions
  contradictions
  next_action: ready_for_analysis | collect_more | refine_query | split_dimension | stop_with_limit
  follow_up_task_specs
  selected_follow_up_specs
  decision_candidates
  arbitration
  decision
  confidence
```

### Query generation reason

每个 task 必须记录为什么存在：

```text
reason:
  "Initial landscape scan for confirmed pricing dimension."
  "Missing official pricing page after source review."
  "Claim claim_7 was weak because evidence excerpt did not mention enterprise packaging."
```

这对前端 replay 和答辩很关键。

## Evidence review 分层

### Source-level review

当前 `EvidenceQualityReviewer` 应继续负责：

- missing source URL
- competitor mismatch
- dimension mismatch
- basic source type checks
- accepted/rejected evidence ids

### Coverage-level review

新增 `CoverageReviewer`，或先扩展 `EvidenceQualityReviewer` 输出 coverage 字段。

它判断：

- expected source types 是否覆盖。
- guiding questions 是否覆盖。
- source diversity 是否足够。
- 是否存在 contradiction。
- 是否应该 collect more、refine query、split dimension、或 ready for analysis。

### Claim-level review

新增 `ClaimSupportReviewer`，在 `AnalysisAgent` 之后、`ReportWriterAgent` 之前。

```text
ClaimSupportReview:
  id
  claim_id
  evidence_ids
  support_status: supported | weak | contradicted | unverifiable
  unsupported_phrases
  required_follow_up_tasks
  reviewer_notes
```

V1 可以只降级或剔除 weak/unverifiable claims。V2 再加 conditional edge 回到 `CollectionAgent` 做 verification collection。

## 推荐 workflow 版本

### V1: 最小稳定版本

不引入复杂 LangGraph 回环，先把 collection 内部做成动态闭环：

```text
PlanningAgent
-> CollectionAgent
   └─ internal coverage/gap/follow-up loop
-> KnowledgeStructuringAgent
-> AnalysisAgent
-> ClaimSupportReviewer
-> ReportWriterAgent
-> PublisherAgent
```

V1 可以暂不加 `FinalQAAgent`，但 `ReportWriterAgent` 必须消费 claim support 状态，不写 unsupported claims。

### V2: 完整闭环版本

加入 claim verification 回采：

```text
PlanningAgent
-> CollectionAgent
-> KnowledgeStructuringAgent
-> AnalysisAgent
-> ClaimSupportReviewer
   ├─ needs_verification -> CollectionAgent
   └─ supported_enough -> ReportWriterAgent
-> FinalQAAgent
-> PublisherAgent
```

V2 需要 LangGraph conditional edge 和 verification task queue。

## 数据结构影响

建议在 `rivalens/schema/competitive.py` 新增：

```text
ResearchBrief
ResearchTask
CoverageAssessment
ClaimSupportReview
```

并在 `CompetitorAnalysisState` 增加：

```text
research_briefs: list[ResearchBrief]
research_tasks: list[ResearchTask]
coverage_assessments: list[CoverageAssessment]
claim_support_reviews: list[ClaimSupportReview]
```

建议扩展：

```text
AnalysisDimension:
  expected_source_types
  minimum_coverage
  risk_level
  expected_claim_types

EvidenceReviewResult:
  coverage_assessment_id
  found_source_types
  missing_source_types
  missing_questions
```

`EvidenceItem` 至少保留：

```text
branch_id
collection_task_id
dimension_id
url
excerpt
source_type
```

如果新增 `research_task_id`，不要替代 `collection_task_id`，应同时保留或让 `collection_task_id == research_task_id`，避免破坏现有 tests 和 trace。

## 具体文件改动建议

### `rivalens/schema/competitive.py`

新增 research planning 和 review schema。所有新增 agent handoff 或 state 字段都从这里出发。

### `rivalens/agents/planning.py`

扩展 `DEFAULT_ANALYSIS_DIMENSIONS`，为每个维度补：

- `expected_source_types`
- `minimum_coverage`
- `risk_level`

例如：

```text
pricing_business_model:
  expected_source_types: ["pricing_page", "official_site", "docs"]
  minimum_coverage: "official pricing or packaging source required"

compliance_risk:
  expected_source_types: ["docs", "official_site", "other"]
  minimum_coverage: "trust/security/privacy source required when available"
```

### `rivalens/agents/collection.py`

这是主改动文件。

新增内部步骤：

- `_build_research_briefs`
- `_plan_initial_research_tasks`
- `_plan_follow_up_research_tasks`
- `_run_research_task`
- `_review_coverage`

保留：

- `_build_root_branches`
- `_assign_evidence_ids`
- `_accepted_evidence_ids`
- `_rejected_evidence_ids`

调整：

- `frontier` 从 branch list 逐步改为 task queue。
- branch 继续表示 lineage 和 dimension coverage。
- task 表示一次具体搜索行动。
- `CoverageAssessment.next_action` 只保留为 focused coverage 的兼容摘要；focused loop 和 landscape loop 都应优先读取 `ResearchRoutingDecision` 风格的 `decision`、`decision_candidates` 和 `selected_follow_up_specs`。

### `rivalens/agents/evidence_review.py`

保留 source-level checks。可以先增加 coverage 字段，也可以新建 `coverage_review.py`。

推荐更清晰的做法：

```text
EvidenceQualityReviewer -> source-level
CoverageReviewer -> branch/task-level
```

### `rivalens/workflows/competitive_analysis.py`

V1 调整 node 顺序：

```text
scope_planner
-> source_collection
-> knowledge_structuring
-> dimension_analysis
-> claim_support_review
-> report_writer
-> publisher
```

这要求新增 `ClaimSupportReviewer` node。

### `rivalens/agents/analysis.py`

改为真正的 `DimensionAnalysisAgent`：

- 消费 `competitor_knowledge`。
- 消费 accepted evidence。
- 消费 coverage assessments。
- 按 dimension 生成 claims。
- 每条 claim 必须绑定 evidence ids。
- 不再生成 “has quality-reviewed evidence” 这种占位式 claim 作为主路径。

### `rivalens/agents/writing.py`

加入 claim support 状态到 report context。

写作约束：

- unsupported claims 不写。
- weak claims 必须标注“公开证据有限”。
- 不新增 search，不新增事实。

## 分阶段实施计划

### Phase 1: Collection 内部融合

目标：先解决“粗 query 导致粗 evidence，早期 pass/fail 误判”的问题。

改动：

- 扩展 `AnalysisDimension` 的 expected source policy。
- 新增 `ResearchBrief`、`ResearchTask`、`CoverageAssessment`。
- 在 `CollectionAgent` 内部加入 task planner 和 coverage reviewer。
- 删除 `BranchReviewAgent`，`CollectionAgent` 基于 `CoverageAssessment` 直接 enqueue follow-up tasks。
- 更新 collection tests。

验收：

- pricing dimension 缺 official/pricing source 时生成 focused follow-up task。
- no evidence 时生成 refine query，而不是直接失败。
- competitor mismatch 时 retry 并记录 reason。
- 每个 follow-up query 都能追溯到 gap。

### Phase 2: 调整 knowledge 与 analysis 顺序

目标：让分析基于结构化知识和 accepted evidence。

改动：

- workflow 改为 `collection -> knowledge_structuring -> analysis`。
- `AnalysisAgent` 消费 `competitor_knowledge` 和 `coverage_assessments`。
- 移除或降级浅层 fallback claim。

验收：

- 每个 confirmed dimension 至少有 section-level claims 或明确 “公开证据不足”。
- claim 绑定 evidence ids。
- writer context 中 claims 不再只是 evidence preview。

### Phase 3: Claim support review

目标：把最终事实质量门放在 claim 层，而不是报告终审。

改动：

- 新增 `ClaimSupportReviewer`。
- 新增 `ClaimSupportReview` schema。
- writer 过滤或标注 weak/unverifiable claims。

验收：

- claim 无 evidence ids 时不能作为 supported。
- claim 文本包含 evidence excerpt 未支持的信息时标为 weak/unverifiable。
- contradicted claim 不进入报告正文，或进入风险/争议说明。

### Phase 4: 完整 verification 回环和前端 replay

目标：支持 claim-level 补采和用户回放 research decision。

改动：

- LangGraph conditional edge: `claim_support_review -> source_collection`。
- verification task queue。
- 前端展示 research briefs、tasks、coverage gaps、claim support status。

验收：

- weak claim 可触发 verification collection。
- 用户能看到为什么搜、为什么补采、为什么停止。
- 溯源附录能从 claim 跳到 evidence URL/excerpt。

## 不建议做

- 不要把 `AdvancedResearch` 的字符串拼接结果直接接进 Rivalens。
- 不要让 `AnalysisAgent`、`ReportWriterAgent` 自己调用 web search。
- 不要把 coverage self-check 放在 analysis 之后作为主闭环。
- 不要恢复一个末端大而全的 QualityAgent 来承担事实校验。
- 不要用固定 child query 模板替代 gap-driven task planning。
- 不要删除 `EvidenceItem`、`EvidenceReviewResult`、`AnalysisClaim.evidence_ids` 的追溯链。

## 推荐的最小下一步

第一步只做 collection 内部融合：

1. 在 `AnalysisDimension` 中加入 expected source policy。
2. 新增 `ResearchBrief`、`ResearchTask`、`CoverageAssessment` schema。
3. 在 `CollectionAgent` 中引入 task queue，而不是直接对每个 branch 只跑一个 query。
4. 新增 `CoverageReviewer`，把 gaps 转成 follow-up task specs。
5. 由 `CollectionAgent` 直接执行 depth/budget guard。
6. 增加 tests 覆盖 no evidence、missing pricing page、missing official source、competitor mismatch、gap-driven follow-up。

这样不用立刻大改前端和完整 DAG，就能解决 research tree 最核心的问题。
