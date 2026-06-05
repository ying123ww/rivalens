# Rivalens Context Engineering

本文档用于 VS Code Copilot、Codex、TRAE 等 AI 编程工具理解 Rivalens 的项目目标、工程边界和验收标准。它不是产品运行时的 RAG 设计文档，而是面向“AI 如何协作开发本仓库”的项目级上下文。

## 项目定位

Rivalens 是一个可追溯的多 Agent 竞品分析系统。核心目标不是生成一篇普通调研报告，而是完成从数据采集、Agent 编排、结构化知识沉淀、质量审查到前端报告查看的一条可信链路。

任何代码、文档或方案变更都应服务于以下目标：

- 让采集、分析、撰写、质检等 Agent 职责更清晰。
- 让 Agent 间通信更结构化、可验证、可追踪。
- 让每条分析结论都能追溯到原始证据。
- 让产品可以现场演示端到端流程。
- 让系统具备可观测、可恢复、可迭代的工程完整度。

## 必读入口

- [README](../README.md): 当前项目架构、LangGraph DAG 和研究模式说明。
- [Workflow](../rivalens/workflows/competitive_analysis.py): 竞品分析主 DAG。
- [Schema](../rivalens/schema/competitive.py): 竞品知识、证据、消息和状态协议。
- [Agents](../rivalens/agents): 规划、采集、采集后证据 review、覆盖控制、结构化、分析、撰写、发布 Agent。
- [Evidence Collector](../rivalens/research/evidence_collector.py): CollectionAgent 使用的 ResearchEngine 证据采集适配器。
- [Scraped Source Cache](../rivalens/research/source_cache.py): scraper 前的 canonical URL raw page cache；缓存命中仍需生成当前任务的 EvidenceItem 并经过质检。
- [Evidence Review](../rivalens/agents/evidence_review.py): standard search 后的证据质量门，输出 accepted/rejected evidence 与 required action。
- [Source Metrics](../rivalens/agents/source_metrics.py): evidence review 后对 accepted evidence 构建 canonical URL / domain / independent source metrics，供 coverage/source-gap review 消费。
- [Coverage Review](../rivalens/agents/coverage_review.py): CollectionAgent 的覆盖审查器，输出 LLM-advised source coverage gap、mixed-quality stability gap、显式 guiding question / success criteria 缺口和 gap-driven follow-up tasks。
- [Branch Coverage State](../rivalens/agents/coverage_state.py): 汇总 root/follow-up branch 的 gap lifecycle，并记录 quality/source/success follow-up 的 before/after improvement assessment。
- [Claim Support Review](../rivalens/agents/claim_support.py): analysis 后的 claim-level citation support gate；当前不通过 CollectionAgent 专用 verification 通道触发复采。
- [Traceable Analysis Dimension Architecture](TRACEABLE_ANALYSIS_DIMENSION_ARCHITECTURE.md): 后续重构 Planning -> Collection -> Knowledge -> Analysis -> Writer 链路时的维度、知识、证据、claim 和报告章节主轴设计。
- [Report Export](../rivalens/report_export.py): Markdown / PDF / DOCX / HTML 报告导出的公共模块，后端 WebSocket 流程和 `PublisherAgent` 都应复用它。
- [Backend Runner](../backend/server/rivalens_runner.py): 后端调用 Rivalens 工作流的入口。

## 开发时的上下文优先级

AI agent 在修改本仓库时，应按以下顺序建立上下文：

1. 先确认任务属于 workflow、agent、schema、research engine、backend、frontend、docs 中的哪一类。
2. 读取对应模块的现有代码和测试，不凭空设计新抽象。
3. 检查变更是否影响 `CompetitorAnalysisState`、`AgentMessage` 或证据追溯链路。
4. 如果涉及用户可见行为，确认 backend 接口和 frontend 展示是否需要同步更新。
5. 如果涉及 Agent 输出，优先使用结构化 schema、明确字段和可验证 evidence IDs。

## 评价标准

以下标准是 Rivalens 的核心验收口径。计划、实现、复查和答辩材料都应主动对齐这些标准。

### 多 Agent 协作与输出可信度

- 角色划分清晰，多个专职 Agent 负责采集、分析、撰写、质检等任务，职责边界明确且无明显重叠。
- 编排框架使用合理。当前项目以 LangGraph 为主，DAG 任务流转应可视化、可追溯。
- Agent 间采用结构化消息传递，例如 function calling、标准 schema 或 Pydantic payload，不能依赖纯自然语言对话作为核心协议。
- 反馈闭环必须真实可触发。质检 Agent 应能识别问题并打回采集或分析 Agent 重做，且重做后输出应可证明有改善，不能只是伪闭环。
- 输出严格符合预定义竞品知识 Schema，包括功能树、定价模型、用户画像等字段，要求字段完整、格式一致。
- 信息溯源完整。每条分析结论应能定位到原始数据源，包括 URL、文档、访谈记录等，并支持一键跳转或溯源查看。

### 技术深度与工程完整度

- 端到端链路完整：数据采集 -> Agent 编排 -> 知识存储 -> 后端接口 -> 前端交互，应可支持现场演示。
- 可观测性达标：每个 Agent 的 prompt、输入、输出、决策过程、token 消耗应有日志或 trace 可查。
- 上下文管理、错误恢复、幻觉抑制有明确策略，例如自一致性校验、引用强制、超长上下文分片。
- 系统稳定性达标：异常处理、超时重试、降级机制完备，演示过程不应出现明显卡顿或崩溃。
- 技术方案体现独特或前瞻性思考，例如自适应任务拆分、Agent 自评估、动态 Schema 演化。

### 业务价值与产品体验

- 相比传统人工竞品分析，应在效率、覆盖度、一致性上有可量化提升。
- 产品形态贴合企业竞品分析真实工作流，具备可落地性和可扩展性，例如可换行业、可换竞品对象。
- 交互设计流畅。报告查看、溯源跳转、人工介入修正、Agent 决策回放等核心动作应易用直观。
- 业务闭环清晰，包含关键指标，例如准确率、覆盖率、人工修正率，并支持后续运营迭代。

### 代码质量与文档

- 代码风格规范、模块化清晰、关键逻辑注释充分、可读性高。
- 项目文档齐全，包括 README、架构图、Agent 角色与协议文档、部署说明。
- Git 提交记录规范，分支管理清晰。
- TRAE、Copilot、Codex 等 AI 编程工具的使用痕迹清晰，体现深度协作，而不是简单生成代码。

### 合规、材料与答辩

- 信息采集合规，遵守目标站点 robots.txt 与服务条款，对外部数据来源有明确授权或公开声明。
- 数据隐私与安全达标。用户访谈、问卷数据应脱敏处理，无敏感信息泄露。
- 工具、模型、数据的使用符合公司及挑战赛“工具与资源使用规范”。
- 提交材料完整，包括方案文档、演示视频、代码库。
- 答辩讲解清晰有条理，演示直观，问答应对得当。

## 非协商约束

- 不要绕过 `rivalens/schema/competitive.py` 中的结构化状态和消息协议。
- 不要生成没有 `evidence_ids` 的关键分析结论。
- 不要恢复末端“删 claim 即通过”的伪质检闭环。review 应优先在 standard search 后作为 source-level evidence gate 和 success-criteria coverage gap detector 运行，由 `CoverageReviewer` 输出只针对缺失标准的补采任务，`CollectionAgent` 直接控制 depth 和 budget。
- 不要把大段原始网页内容直接传给下游 Agent。应保留证据摘要、URL、source metadata 和必要 excerpt。
- 不要在 backend 或 Agent 内重复实现报告文件导出。报告导出应复用 `rivalens/report_export.py`，发布状态和 publish 消息应使用结构化 artifact payload。
- 不要为了演示效果隐藏失败。失败、重试、降级应进入可观测日志或 agent events。

## 计划任务时必须回答

在开始复杂实现前，计划文档至少应回答：

- 这次变更对应哪一项评价标准？
- 影响哪些 Agent、schema、workflow edge、backend API 或 frontend 视图？
- 哪些字段或 evidence IDs 必须保持可追溯？
- 是否需要新增或调整日志、trace、token/cost 记录？
- 失败时如何重试、降级或给用户可理解的状态？
- 用哪些测试或演示步骤证明变更有效？

## 实现任务时必须检查

实现完成前，AI agent 应检查：

- 结构化 payload 是否仍通过 Pydantic 校验。
- DAG 是否仍按预期流转，条件边是否真实触发。
- EvidenceItem、CompetitorKnowledge、AnalysisClaim 是否保持引用链。
- 后端返回和前端展示是否仍能支持溯源查看。
- 新增逻辑是否有 targeted tests 或最小可复现验证。
- 文档是否需要同步更新。

## 复查任务时必须关注

代码复查应优先寻找：

- Agent 职责重叠或职责遗漏。
- 自然语言中转替代结构化消息的问题。
- 没有证据绑定的 claim。
- 质量闭环无法触发或触发后没有改善证据的问题。
- 日志、trace、token/cost 缺失。
- 异常处理、超时、重试和降级不足。
- 前端无法查看证据来源或 Agent 决策过程的问题。

## 推荐输出格式

计划输出建议包含：

- 目标与评价标准映射
- 当前代码路径
- 设计方案
- 任务清单
- 数据与 schema 影响
- 可观测性与错误恢复
- 测试与演示验收
- 开放问题

复查输出建议包含：

- 阻塞问题
- 高风险问题
- 中低风险问题
- 缺失测试或演示风险
- 与评价标准的差距
