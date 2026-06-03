# Traceable Analysis Dimension Architecture

本文档是 Rivalens 后续重构 `PlanningAgent -> CollectionAgent -> KnowledgeStructuringAgent -> AnalysisAgent -> ReportWriterAgent` 链路的指导大纲。目标是把调研方向、知识结构、证据、分析结论和报告章节拆成语义清楚的对象，并通过显式 ID 保持可追溯。

## 背景

Rivalens 的核心目标不是生成一篇普通报告，而是保留这条可信链路：

```text
public source URL
-> EvidenceItem
-> structured competitor knowledge
-> AnalysisClaim
-> report section and citation
```

当前系统已经有 Planning、Collection、Knowledge、Analysis、ClaimSupport、Writer 等 Agent，但维度身份在多个对象之间复用同一个字符串字段，导致职责边界变模糊。

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

当前维度链路大致如下：

```text
IndustryDirectionPlan.final_directions[].direction_id
-> PlanningAgent._direction_schema_extensions()
-> ActiveKnowledgeSchema.industry_extensions[].id
-> CollectionAgent._schema_dimensions()
-> ResearchBranch.dimension_id
-> EvidenceCollectionTask.dimension_id
-> EvidenceItem.dimension_id
-> AnalysisClaim.dimension
-> ReportWriterAgent fixed product section matching
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
AnalysisClaim.dimension    = claim 属于哪个维度
AnalysisClaim.evidence_ids = claim 由哪些 EvidenceItem 支撑
```

## 当前问题

### 1. 一个字符串 ID 承担太多语义

当前这些字段经常靠同一个字符串值串起来：

```text
SchemaExtension.id
ResearchBranch.dimension_id
EvidenceItem.dimension_id
AnalysisClaim.dimension
ReportWriterAgent section id
```

它们分别代表 schema 字段、采集维度、证据归属、claim 归属和报告展示章节。语义不同但字段未显式区分，导致下游只能猜。

### 2. `industry_extensions.evidence_ids` 看起来像证据链，但实际不是

`SchemaExtension` 有 `evidence_ids` 字段，但 Planning 阶段通常写入空数组。它不应被当作当前版本的证据绑定来源。

### 3. `CompetitorKnowledge.industry_extensions` 不是精准证据聚合

当前 `KnowledgeStructuringAgent` 会给每个 competitor 的每个 extension 填 evidence IDs，但这些 evidence IDs 可能是该 competitor 的全部 accepted evidence，而不是该 extension 的精确 evidence。它不适合作为 claim 级引用来源。

### 4. Knowledge 没有成为主路径

当前 `AnalysisAgent` 优先从 accepted evidence 直接生成 claims。只有当 evidence-review path 没有生成 claims 时，才 fallback 到 `CompetitorKnowledge`。这让 KnowledgeStructuringAgent 更像旁路存档，而不是主分析输入。

### 5. Writer 仍然按固定产品小节组织第三章

`ReportWriterAgent` 当前主要遍历固定产品分析小节，再用 mapping / aliases 把 claim 塞进去。行业特定维度或用户自定义方向可能无法进入正文第三章，只剩附录或总结中残留。

## 目标架构

Rivalens 应以 `AnalysisDimension` 作为端到端主轴：

```text
AnalysisDimension
-> EvidenceItem
-> KnowledgeFact / CompetitorKnowledge
-> AnalysisClaim
-> ReportSectionMapping
-> fixed product analysis section
```

核心原则：

- `AnalysisDimension` 表示这次任务要研究什么，不直接等于报告第三章的小节。
- `ActiveKnowledgeSchema` 表示结构化知识的存储字段，不直接充当报告章节。
- 报告第三章仍然保留固定 10 个产品分析小节，保证输出结构稳定。
- 每个 `AnalysisDimension` 必须显式映射到 1 个 primary product section，可选映射到少量 secondary product sections。
- `EvidenceItem` 必须显式绑定到 `analysis_dimension_id`。
- `KnowledgeFact` 应把 accepted evidence 结构化成可分析事实。
- `AnalysisClaim` 应优先基于 KnowledgeFact 生成，同时保留 evidence IDs。
- `ReportWriterAgent` 应按固定 10 小节生成第三章，并通过显式 mapping 选择 claims，而不是依赖 aliases 猜测。

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
            "section_id": "product_features",
            "role": "primary",
            "reason": "安全、权限、隐私和合规披露属于可观察的产品能力和企业级能力。"
        },
        {
            "section_id": "strategic_positioning",
            "role": "secondary",
            "reason": "如果竞品把安全合规作为企业级信任定位，则可进入战略定位。"
        },
        {
            "section_id": "signature_features",
            "role": "secondary",
            "reason": "如果安全合规能力形成明显差异化卖点，则可进入特色功能。"
        }
    ],
}
```

它回答：

```text
这次任务要研究什么，以及研究结果应该落到哪些固定报告小节？
```

### ActiveKnowledgeSchema / SchemaExtension

`ActiveKnowledgeSchema` 只回答：

```text
结构化知识应该沉淀到哪些字段？
```

`SchemaExtension` 可以由 `AnalysisDimension.schema_field_ids` 引用，但不应取代 `AnalysisDimension`。

```python
{
    "id": "direction_baseline_trust_security_compliance",
    "name": "信任、安全与合规",
    "description": "安全、隐私、权限、合规和信任背书相关字段。",
    "origin": "schema_registry",
    "source_hints": ["trust_center", "official_site", "docs"],
    "approved": True,
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

`dimension_id` 可以在迁移期保留为兼容字段，但新逻辑应优先读 `analysis_dimension_id`。

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
    "report_section_id": "product_features",
    "report_section_role": "primary",
    "claim": "Acme 在安全合规公开透明度上强于 X，因为其公开披露了 SSO、审计日志和合规认证。",
    "competitors": ["Acme"],
    "confidence": 0.78,
}
```

它回答：

```text
这些结构化事实支持什么分析判断？
```

### ProductAnalysisSection / ReportSectionMapping

第三章的展示结构应继续使用固定 10 个 product sections。它们是报告 UI 和读者认知上的稳定槽位，不是调研维度本身。

```text
3.1 strategic_positioning
3.2 target_users
3.3 business_model
3.4 operation_strategy
3.5 product_features
3.6 product_flow
3.7 product_structure
3.8 interaction_design
3.9 signature_features
3.10 user_reputation
```

`ReportSectionMapping` 是 `AnalysisDimension` 和固定 10 小节之间的桥。

```python
{
    "analysis_dimension_id": "baseline_trust_security_compliance",
    "primary_section_id": "product_features",
    "secondary_section_ids": ["strategic_positioning", "signature_features"],
    "schema_field_ids": ["direction_baseline_trust_security_compliance"],
    "mapping_reason": "该维度主要描述可观察的产品级信任能力；当它构成定位或差异化卖点时，可作为 secondary material 进入对应小节。",
}
```

它回答：

```text
一个动态研究维度应该进入固定 10 小节里的哪些位置？
```

LLM 可以参与生成 mapping，但输出必须受限和可校验：

- `primary_section_id` 必须属于固定 10 个 section id。
- 每个 `AnalysisDimension` 必须有且只能有 1 个 primary section。
- `secondary_section_ids` 应控制数量，避免同一 claim 被重复写进多个小节。
- Writer 不应临时自由改写 mapping；发现未映射维度时应记录质量问题或进入迁移诊断输出。

### ReportSection

Report section 是固定 product section 的一次渲染结果。它聚合映射到该小节的 dimensions、claims 和 evidence。

```python
{
    "id": "report_section_product_features",
    "section_id": "product_features",
    "number": "3.5",
    "title": "产品功能",
    "mapped_analysis_dimension_ids": ["baseline_trust_security_compliance", "core_product_supply"],
    "claim_ids": ["claim_1", "claim_2"],
    "evidence_ids": ["ev_1", "ev_2"],
}
```

它回答：

```text
固定第三章小节如何汇总映射进来的分析维度和证据化 claims？
```

## 推荐端到端链路

```text
PlanningAgent
  -> IndustryDirectionPlan
  -> AnalysisDimension[]
  -> ActiveKnowledgeSchema

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
  -> fixed product sections
  -> ReportSectionMapping from AnalysisDimension.report_targets
  -> section claims by report_section_id and analysis_dimension_id
  -> citation refs by AnalysisClaim.evidence_ids -> EvidenceItem.url
```

## Agent Responsibilities

### PlanningAgent

- Select industry and confirmed analysis directions.
- Build `AnalysisDimension[]` as the canonical task dimensions.
- Build `ActiveKnowledgeSchema` as the knowledge storage schema.
- Preserve provenance from `IndustryDirectionPlan.final_directions` into `AnalysisDimension.direction_id`.
- Map every `AnalysisDimension` to one primary fixed product section and optional secondary product sections.

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

- Generate chapter three from the fixed 10 product sections.
- Select section claims by exact `report_section_id`, then validate against `analysis_dimension_id`.
- Use aliases only as a compatibility fallback, never as the primary matching mechanism.
- Preserve citations by resolving `claim.evidence_ids -> EvidenceItem.url`.

## Migration Plan

### Phase 1: Add explicit fields without breaking compatibility

- Add `analysis_dimensions` to PlanningAgent output.
- Add `report_targets` or equivalent `ReportSectionMapping` to each analysis dimension.
- Add `analysis_dimension_id` to ResearchBranch, ResearchTask, EvidenceCollectionTask, EvidenceItem and AnalysisClaim.
- Add `report_section_id` to AnalysisClaim or build an equivalent normalized claim-to-section index before writing.
- Keep current `dimension_id` and `dimension` fields as compatibility aliases.
- Add tests that prove `analysis_dimension_id` survives Planning -> Collection -> Analysis -> Writer.

### Phase 2: Make KnowledgeStructuringAgent meaningful

- Introduce `KnowledgeFact` or an equivalent structured fact collection in `CompetitorAnalysisState`.
- Build facts from accepted evidence.
- Change AnalysisAgent to generate claims from facts before direct evidence.
- Keep direct evidence-derived claims as a fallback with observable `claim_source`.

### Phase 3: Make Writer mapping-driven

- Keep fixed 10 product sections as the default third-chapter structure.
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
- Every AnalysisDimension maps to exactly one primary fixed product section.
- Every non-profile EvidenceItem has an `analysis_dimension_id`.
- Every important AnalysisClaim has `analysis_dimension_id` and non-empty `evidence_ids`.
- Writer chapter three remains the fixed 10-section structure.
- Writer places claims through explicit `report_section_id` / `ReportSectionMapping`, not alias guessing.
- KnowledgeStructuringAgent produces facts or structured knowledge that AnalysisAgent actually consumes.
- A report citation can be traced back through claim, fact, evidence and URL.
- Verification tasks keep the original claim and analysis dimension identity.

## Design Rule

Do not use `active_knowledge_schema.industry_extensions` as the report or evidence-traceability backbone. Use it as the knowledge schema.

Do not use the fixed 10 product sections as the research backbone either. They are presentation slots.

The end-to-end research backbone should be `AnalysisDimension`; the third-chapter presentation backbone should be the fixed 10 product sections; the bridge between them should be explicit `ReportSectionMapping`.
