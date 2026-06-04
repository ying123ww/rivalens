# Traceable Analysis Dimension Architecture

本文档是 Rivalens 后续重构 `PlanningAgent -> CollectionAgent -> KnowledgeStructuringAgent -> AnalysisAgent -> ReportWriterAgent` 链路的指导大纲。目标是把调研方向、知识结构、证据、分析结论和动态报告章节拆成语义清楚的对象，并通过显式 ID 保持可追溯。

## 背景

Rivalens 的核心目标不是生成一篇普通报告，而是保留这条可信链路：

```text
public source URL
-> EvidenceItem
-> structured competitor knowledge
-> AnalysisClaim
-> report section and citation
```

当前系统已经有 Planning、Collection、Knowledge、Analysis、ClaimSupport、Writer 等 Agent，但维度身份、证据归属和报告章节在多个对象之间复用同一个字符串字段，导致职责边界变模糊。

## 当前真实链路

当前 DAG 顺序是：

```text
PlanningAgent
-> CollectionAgent
-> KnowledgeStructuringAgent
-> AnalysisAgent
-> ClaimSupportReviewer
-> ReportWriterAgent
-> PublisherAgent
```

当前维度和章节链路大致如下：

```text
IndustryDirectionPlan.final_directions[].direction_id
-> PlanningAgent._analysis_dimensions()
-> AnalysisDimension.id / schema_field_ids / report_targets
-> CollectionAgent._collection_dimensions()
-> ResearchBranch.analysis_dimension_id / report_section_id
-> EvidenceCollectionTask.analysis_dimension_id
-> EvidenceItem.analysis_dimension_id
-> KnowledgeFact.analysis_dimension_id / report_section_id
-> AnalysisClaim.analysis_dimension_id / report_section_id
-> ReportWriterAgent dynamic section routing
```

证据支持链路大致如下：

```text
EvidenceItem.id
-> EvidenceReviewResult.accepted_evidence_ids
-> AnalysisClaim.evidence_ids
-> ClaimSupportReview.evidence_ids
-> ReportWriterAgent citation refs
-> appendix URL
```

这两条链在 `AnalysisClaim` 处临时汇合：

```text
AnalysisClaim.analysis_dimension_id = claim 属于哪个分析维度
AnalysisClaim.report_section_id     = claim 进入哪个任务级动态报告小节
AnalysisClaim.evidence_ids          = claim 由哪些 EvidenceItem 支撑
```

## 已修正的问题背景

### 1. 一个字符串 ID 承担太多语义

旧链路中这些字段经常靠同一个字符串值串起来：

```text
AnalysisDimension.schema_field_ids
ResearchBranch.dimension_id
EvidenceItem.dimension_id
AnalysisClaim.dimension  # removed
ReportWriterAgent section id
```

它们分别代表 schema 字段、采集维度、证据归属、claim 归属和报告展示章节。语义不同但字段未显式区分，导致下游只能猜。

### 2. `ActiveKnowledgeSchema` / `SchemaExtension` 已移除

旧版 `ActiveKnowledgeSchema`、`SchemaExtension` 和 `ActiveKnowledgeSchema.industry_extensions` 容易被误读成证据链或 collection 入口。这些对象已移除；行业选择归属 `IndustryDirectionPlan.industry`，方向派生字段 ID 只保留在 `AnalysisDimension.schema_field_ids`。

### 3. `CompetitorKnowledge.industry_extensions` 已移除

旧版 `KnowledgeStructuringAgent` 会给每个 competitor 的每个 extension 填 evidence IDs。该字段不是主链路需要的证据聚合对象，已经移除；精确证据绑定由 `KnowledgeFact.evidence_ids` 和 `AnalysisClaim.evidence_ids` 承担。

### 4. Knowledge 没有成为主路径

当前 `AnalysisAgent` 优先从 accepted evidence 直接生成 claims。只有当 evidence-review path 没有生成 claims 时，才 fallback 到 `CompetitorKnowledge`。这让 KnowledgeStructuringAgent 更像旁路存档，而不是主分析输入。

### 5. Writer 曾经按固定产品小节猜测第三章路由

旧版 `ReportWriterAgent` 主要遍历固定产品分析小节，再用 mapping / aliases 把 claim 塞进去。行业特定维度或用户自定义方向可能无法进入正文第三章，只剩附录或总结中残留。新的第三章不应继续依赖固定 10 小节，而应由本次任务的 `AnalysisDimension` 和显式章节规划生成。

## 目标架构

Rivalens 应以 `AnalysisDimension` 作为端到端主轴：

```text
AnalysisDimension
-> EvidenceItem
-> KnowledgeFact / CompetitorKnowledge
-> AnalysisClaim
-> ReportSectionMapping
-> dynamic report section
```

核心原则：

- `AnalysisDimension` 表示这次任务要研究什么，不直接等于报告第三章的小节。
- `IndustryDirectionPlan` 表示本次任务选中的行业和最终分析方向；不再单独维护 `ActiveKnowledgeSchema`。
- 报告第三章由动态分析维度总览和任务级动态章节组成，不再固定为 10 个产品分析小节。
- 每个 `AnalysisDimension` 必须显式映射到 1 个 primary report section，可选映射到少量 secondary report sections。
- `report_section_id` 必须来自本次任务的章节规划或 `AnalysisDimension.report_targets`，而不是来自全局固定小节 taxonomy。
- `EvidenceItem` 必须显式绑定到 `analysis_dimension_id`。
- `KnowledgeFact` 应把 accepted evidence 结构化成可分析事实。
- `AnalysisClaim` 应优先基于 KnowledgeFact 生成，同时保留 evidence IDs。
- `ReportWriterAgent` 应按动态章节规划生成第三章，并通过显式 mapping 选择 claims，而不是依赖 aliases 猜测。

## 当前目标实现落点

- `PlanningAgent` 负责从 `IndustryDirectionPlan.final_directions` 生成 `state["analysis_dimensions"]`，并为每个维度写入 `report_targets`。
- `AnalysisDimension.report_targets` 是当前运行时的章节 mapping 存储；如果后续新增 `ReportSectionPlan`，它应从这些 target 归一化生成，而不是绕过维度主轴。
- `rivalens/report_routing.py` 只负责动态章节路由：默认把每个分析维度映射到自己的任务级 section id，不维护全局固定产品小节 taxonomy。
- `CollectionAgent` 只消费 `analysis_dimensions` 生成非 profile 搜索分支；行业搜索词从 `industry_direction_plan.industry` 读取。
- `EvidenceItem`、`KnowledgeFact`、`AnalysisClaim` 和 ClaimSupport verification task 均应保留 `analysis_dimension_id`；报告正文路由使用 `report_section_id`。
- `ReportWriterAgent` 输出“动态分析维度总览 + 动态章节正文”，并只按 `report_section_id` / `report_targets` 选择 claims，不再使用 aliases 或 dimension string 猜测章节。

## 推荐对象模型

### AnalysisDimension

`AnalysisDimension` 是主线对象，由 PlanningAgent 写入 state。

```python
{
    "id": "baseline_trust_security_compliance",
    "name": "信任、安全与合规",
    "description": "比较竞品在隐私、数据安全、权限、通用合规和采购信任门槛上的公开能力。",
    "objective": "研究竞品是否具备可验证的安全和合规公开信号。",
    "guiding_questions": [
        "竞品公开披露了哪些安全和合规能力？",
        "这些能力是否来自稳定的官方或标准组织来源？"
    ],
    "source_hints": ["trust_center", "official_site", "docs", "standards_body"],
    "success_criteria": [],
    "origin": "industry_template",
    "required": True,
    "direction_id": "baseline_trust_security_compliance",
    "schema_field_ids": ["direction_baseline_trust_security_compliance"],
    "report_order": 9,
    "report_targets": [
        {
            "section_id": "trust_security_compliance",
            "role": "primary",
            "reason": "安全、权限、隐私和合规披露是本次任务需要单独展开的核心分析章节。"
        },
        {
            "section_id": "enterprise_adoption_barriers",
            "role": "secondary",
            "reason": "如果安全合规直接影响企业采购、迁移或准入门槛，可作为企业采用章节的 secondary material。"
        },
        {
            "section_id": "differentiation_moat",
            "role": "secondary",
            "reason": "如果安全合规形成明显差异化护城河，可作为差异化章节的 secondary material。"
        }
    ],
}
```

它回答：

```text
这次任务要研究什么，以及研究结果应该落到哪些任务级动态报告小节？
```

### IndustryDirectionPlan

`IndustryDirectionPlan` 回答：

```text
本任务选中了哪个行业？最终要研究哪些方向？
```

方向派生字段不再建模为独立 `SchemaExtension`；它们由
`AnalysisDimension.schema_field_ids` 承载。

```python
{
    "industry": {"industry_id": "saas_collaboration", "name": "SaaS / 协作文档工具"},
    "candidate_industries": [],
    "final_directions": [...],
    "selection_method": "rule_template",
}
```

### ResearchBranch / ResearchTask

CollectionAgent 应消费 `analysis_dimensions`。

```python
{
    "id": "collect_acme_baseline_trust_security_compliance",
    "analysis_dimension_id": "baseline_trust_security_compliance",
    "schema_field_ids": ["direction_baseline_trust_security_compliance"],
    "competitor": "Acme",
    "research_goal": "...",
    "success_criteria": [],
    "source_hints": ["trust_center", "official_site", "docs"],
}
```

`dimension_id` 可以作为 research/evidence trace alias 暂时保留，但 KnowledgeStructuring、Analysis 和 Writer 不应再用它反推 `analysis_dimension_id`。

### EvidenceItem

EvidenceItem 应显式绑定分析维度。

```python
{
    "id": "ev_1",
    "analysis_dimension_id": "baseline_trust_security_compliance",
    "schema_field_ids": ["direction_baseline_trust_security_compliance"],
    "branch_id": "collect_acme_baseline_trust_security_compliance",
    "competitor": "Acme",
    "title": "...",
    "url": "...",
    "excerpt": "...",
}
```

它回答：

```text
这个公开来源支持哪个分析维度？
```

### KnowledgeFact

建议新增或等价强化一个事实层对象。它是 KnowledgeStructuringAgent 的主产物。

```python
{
    "id": "fact_1",
    "competitor": "Acme",
    "analysis_dimension_id": "baseline_trust_security_compliance",
    "schema_field_id": "direction_baseline_trust_security_compliance",
    "statement": "Acme publicly documents SSO and audit log controls.",
    "value": {
        "capability": "SSO and audit logs",
        "source_type": "trust_center"
    },
    "evidence_ids": ["ev_1"],
    "confidence": 0.82,
}
```

它回答：

```text
accepted evidence 能沉淀出什么结构化事实？
```

### AnalysisClaim

AnalysisClaim 应主要从 KnowledgeFact 生成，并保留证据绑定。

```python
{
    "id": "claim_1",
    "analysis_dimension_id": "baseline_trust_security_compliance",
    "knowledge_fact_ids": ["fact_1", "fact_2"],
    "evidence_ids": ["ev_1", "ev_2"],
    "report_section_id": "trust_security_compliance",
    "claim": "Acme 在安全合规公开透明度上强于 X，因为其公开披露了 SSO、审计日志和合规认证。",
    "competitors": ["Acme"],
    "confidence": 0.78,
}
```

它回答：

```text
这些结构化事实支持什么分析判断？
```

### ReportSectionPlan / ReportSectionMapping

第三章的展示结构应由本次任务动态生成。Writer 可以先输出一个“分析维度总览”，再根据 `AnalysisDimension.report_targets` 或归一化后的 `ReportSectionPlan` 生成若干动态章节。

`ReportSectionPlan` 回答：

```text
本次报告第三章应该有哪些动态章节，顺序是什么，每节由哪些分析维度支撑？
```

```python
[
    {
        "section_id": "trust_security_compliance",
        "number": "3.1",
        "title": "信任、安全与合规",
        "description": "比较竞品在安全、权限、隐私、合规和企业采购信任门槛上的公开证据。",
        "analysis_dimension_ids": ["baseline_trust_security_compliance"],
        "source": "analysis_dimension_primary_target",
    },
    {
        "section_id": "enterprise_adoption_barriers",
        "number": "3.2",
        "title": "企业采用与迁移门槛",
        "description": "比较竞品在部署、集成、迁移、SLA、采购准入等方面的公开信号。",
        "analysis_dimension_ids": ["migration_switching_cost", "sla_reliability"],
        "source": "analysis_dimension_grouping",
    },
]
```

`ReportSectionMapping` 是 `AnalysisDimension` 和动态报告章节之间的桥。

```python
{
    "analysis_dimension_id": "baseline_trust_security_compliance",
    "primary_section_id": "trust_security_compliance",
    "secondary_section_ids": ["enterprise_adoption_barriers", "differentiation_moat"],
    "schema_field_ids": ["direction_baseline_trust_security_compliance"],
    "mapping_reason": "该维度本身足以形成独立章节；当它影响企业采用或差异化护城河时，可作为 secondary material 进入对应动态章节。",
}
```

它回答：

```text
一个动态研究维度应该进入本次报告第三章里的哪些位置？
```

LLM 可以参与生成 mapping，但输出必须受限和可校验：

- `primary_section_id` 必须来自本次任务的 `ReportSectionPlan`，或由 `AnalysisDimension.report_targets` 显式创建。
- 每个 `AnalysisDimension` 必须有且只能有 1 个 primary section。
- `secondary_section_ids` 应控制数量，避免同一 claim 被重复写进多个小节。
- Writer 不应临时自由改写 mapping；发现未映射维度时应记录质量问题或进入诊断输出。
- 动态章节数量不要求固定，但应受信息覆盖和可读性约束；没有证据支撑的章节不应被强行展开。

### ReportSection

Report section 是一个任务级动态章节的一次渲染结果。它聚合映射到该章节的 dimensions、claims 和 evidence。

```python
{
    "id": "report_section_trust_security_compliance",
    "section_id": "trust_security_compliance",
    "number": "3.1",
    "title": "信任、安全与合规",
    "mapped_analysis_dimension_ids": ["baseline_trust_security_compliance"],
    "claim_ids": ["claim_1", "claim_2"],
    "evidence_ids": ["ev_1", "ev_2"],
}
```

它回答：

```text
第三章动态章节如何汇总映射进来的分析维度和证据化 claims？
```

## 推荐端到端链路

```text
PlanningAgent
  -> IndustryDirectionPlan
  -> AnalysisDimension[]

CollectionAgent
  -> ResearchBranch.analysis_dimension_id
  -> ResearchTask.analysis_dimension_id
  -> EvidenceItem.analysis_dimension_id
  -> EvidenceReviewResult.accepted_evidence_ids

KnowledgeStructuringAgent
  -> KnowledgeFact.analysis_dimension_id
  -> KnowledgeFact.schema_field_id
  -> KnowledgeFact.evidence_ids
  -> CompetitorKnowledge

AnalysisAgent
  -> AnalysisClaim.analysis_dimension_id
  -> AnalysisClaim.knowledge_fact_ids
  -> AnalysisClaim.evidence_ids

ClaimSupportReviewer
  -> ClaimSupportReview.claim_id
  -> ClaimSupportReview.evidence_ids
  -> verification task keeps analysis_dimension_id

ReportWriterAgent
  -> dynamic analysis dimension overview
  -> ReportSectionPlan / ReportSectionMapping from AnalysisDimension.report_targets
  -> section claims by report_section_id and analysis_dimension_id
  -> citation refs by AnalysisClaim.evidence_ids -> EvidenceItem.url
```

## Agent Responsibilities

### PlanningAgent

- Select industry and confirmed analysis directions.
- Build `AnalysisDimension[]` as the canonical task dimensions.
- Preserve provenance from `IndustryDirectionPlan.final_directions` into `AnalysisDimension.direction_id`.
- Map every `AnalysisDimension` to one primary dynamic report section and optional secondary report sections.
- Keep dynamic section IDs stable inside the task so Collection, Analysis, ClaimSupport and Writer can share the same `report_section_id`.

### CollectionAgent

- Expand competitor x `AnalysisDimension` into root branches.
- Attach `analysis_dimension_id` to branches, tasks, artifacts and evidence.
- Keep coverage gap follow-up tasks inside the same analysis dimension unless the reviewer explicitly creates a derived dimension.

### KnowledgeStructuringAgent

- Turn accepted EvidenceItem records into KnowledgeFact records.
- Attach every KnowledgeFact to one analysis dimension and one optional schema field.
- Populate CompetitorKnowledge from KnowledgeFact, not from broad competitor-level evidence buckets.

### AnalysisAgent

- Generate claims from KnowledgeFact first.
- Fall back to direct evidence-derived claims only when KnowledgeFact is unavailable, and record that source explicitly.
- Preserve `analysis_dimension_id`, `knowledge_fact_ids`, and `evidence_ids`.
- Attach `report_section_id` from the dimension mapping when producing or normalizing claims.

### ClaimSupportReviewer

- Review only claim-bound evidence.
- Keep verification tasks tied to the original claim and `analysis_dimension_id`.
- Do not rewrite dimensions through natural language.

### ReportWriterAgent

- Generate chapter three from a dynamic analysis dimension overview and task-specific dynamic report sections.
- Select section claims by exact `report_section_id`, then validate against `analysis_dimension_id`.
- Do not infer report sections from aliases, `dimension`, or `dimension_id`.
- Preserve citations by resolving `claim.evidence_ids -> EvidenceItem.url`.

## Migration Plan

### Phase 1: Make AnalysisDimension the runtime backbone

- Add `analysis_dimensions` to PlanningAgent output.
- Add `report_targets` or equivalent `ReportSectionMapping` to each analysis dimension.
- Ensure report target section IDs are task-level dynamic IDs, not global fixed product-section IDs.
- Add `analysis_dimension_id` to ResearchBranch, ResearchTask, EvidenceCollectionTask, EvidenceItem and AnalysisClaim.
- Add `report_section_id` to AnalysisClaim or build an equivalent normalized claim-to-section index before writing.
- Remove `AnalysisClaim.dimension`; keep lower-level `dimension_id` fields only where research/evidence trace contracts still read them.
- Remove `ActiveKnowledgeSchema`, `SchemaExtension` and `active_knowledge_schema.industry_extensions`.
- Add tests that prove `analysis_dimension_id` survives Planning -> Collection -> Analysis -> Writer.

### Phase 2: Make KnowledgeStructuringAgent meaningful

- Introduce `KnowledgeFact` or an equivalent structured fact collection in `CompetitorAnalysisState`.
- Build facts from accepted evidence.
- Change AnalysisAgent to generate claims from facts before direct evidence.
- Keep direct evidence-derived claims as a fallback with observable `claim_source`.

### Phase 3: Make Writer mapping-driven

- Generate chapter three from a dynamic analysis dimension overview and a task-level `ReportSectionPlan`.
- Generate section contents from claims mapped by `report_section_id`.
- Use `AnalysisDimension.report_targets` or `ReportSectionMapping` as the only primary routing source.
- Add an "unmapped claims" section only for migration diagnostics, not as normal output.

### Phase 4: Tighten traceability and observability

- Add agent events recording dimension counts, fact counts, claim counts, and unmapped IDs.
- Make claim-support verification preserve `analysis_dimension_id`.
- Add backend/frontend support for replaying:

```text
ReportSection -> AnalysisClaim -> KnowledgeFact -> EvidenceItem -> URL
```

## Acceptance Criteria

A future implementation of this architecture should prove:

- Planner writes non-empty `analysis_dimensions` for normal runs.
- Every AnalysisDimension maps to exactly one primary dynamic report section.
- Every non-profile EvidenceItem has an `analysis_dimension_id`.
- Every important AnalysisClaim has `analysis_dimension_id` and non-empty `evidence_ids`.
- Writer chapter three contains a dynamic analysis dimension overview and dynamically generated sections.
- Writer places claims through explicit `report_section_id` / `ReportSectionMapping`, not alias guessing.
- KnowledgeStructuringAgent produces facts or structured knowledge that AnalysisAgent actually consumes.
- A report citation can be traced back through claim, fact, evidence and URL.
- Verification tasks keep the original claim and analysis dimension identity.

## Design Rule

Do not reintroduce `ActiveKnowledgeSchema` or `active_knowledge_schema.industry_extensions` as the report, collection, or evidence-traceability backbone.

Do not use the old fixed 10 product sections as the research backbone or presentation backbone.

The end-to-end research backbone should be `AnalysisDimension`; the third-chapter presentation backbone should be the task-specific `ReportSectionPlan`; the bridge between them should be explicit `ReportSectionMapping` / `AnalysisDimension.report_targets`.
