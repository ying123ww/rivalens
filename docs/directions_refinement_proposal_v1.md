# Directions 细化方案 v1

> 作者：Seiya + Claude | 日期：2026-05-29
> 状态：初版草案，待团队 review

---

## 一、现有问题诊断

### 1.1 AI 行业方向几乎全是"模型层"

当前 `ai_tools_llm` 的 13 个方向（model_capabilities、benchmarks、inference_speed 等）适合比较底层模型 API，但如果用户要分析的是 **AI 产品**（如 Cursor vs Windsurf、Perplexity vs ChatGPT Search、Midjourney vs DALL-E），这些方向完全覆盖不到产品层面的差异。

**缺失的产品级覆盖：** 旧方案需要补足能由 Agent 按行业、用户问题和已采证据动态选择的产品层分析方向，而不是绑定到固定维度清单。

### 1.2 行业粒度不均匀

- 金融（11 个方向）和本地生活（10 个方向）相对完善
- SaaS（10 个方向）缺少"迁移成本"和"竞争格局/市场定位"
- 电商（8 个方向）缺少"跨境与合规"和"用户留存/复购机制"
- 所有行业都缺少一个通用的**"战略定位与竞争格局"**维度

### 1.3 缺少跨行业通用方向

某些维度几乎对所有行业都有价值（市场定位、团队与融资、增长策略），但现在每个行业各写各的，没有复用机制。

---

## 二、方案：AI 产品行业拆分

### 核心思路

将现有 `ai_tools_llm` 拆成两个行业模板：

| 新 industry_id | 适用场景 | 示例竞品 |
|---|---|---|
| `ai_model_platform` | 模型 API / 基础设施层竞品分析 | OpenAI API vs Claude API vs Gemini API |
| `ai_product_application` | AI 驱动的终端产品竞品分析 | ChatGPT vs Kimi、Cursor vs Windsurf、Perplexity vs Google AI Overview |

### 2.1 `ai_model_platform`（AI 模型与平台）

保留现有方向，小幅调整：

| direction_id | 名称 | required | 变更说明 |
|---|---|---|---|
| model_capabilities | 模型能力与适用任务 | 是 | 保留 |
| pricing_usage_limits | 价格、计费与额度 | 是 | 保留 |
| benchmarks_evaluations | 评测与基准表现 | 是 | 保留 |
| developer_experience | 开发者体验与 API | 是 | 保留 |
| safety_compliance | 安全、合规与治理 | 是 | 保留 |
| data_usage_training_policy | 数据使用与企业边界 | 是 | 保留 |
| deployment_options | 部署与访问方式 | 是 | 保留 |
| context_window_long_context | 上下文窗口与长文处理 | 是 | **升为必选** |
| inference_speed_latency | 推理速度与延迟 | 是 | **升为必选** |
| multimodal_capabilities | 多模态能力覆盖 | 否 | 保留 |
| finetuning_rag_customization | 微调与 RAG 定制化 | 否 | 保留 |
| ecosystem_adoption | 生态采用与社区热度 | 否 | 保留 |
| model_update_cadence | **新增：模型迭代节奏与路线图** | 否 | 模型发布频率、版本淘汰策略、功能预告 |
| reliability_rate_limits | **新增：可靠性与限流策略** | 是 | 可用性 SLA、限流机制、降级策略、状态页 |

### 2.2 `ai_product_application`（AI 产品与应用）— 重点新增

这是你提到的核心需求，按产品分析框架设计：

| direction_id | 名称 | reason | source_hints | required |
|---|---|---|---|---|
| strategic_positioning | 战略定位与市场卡位 | 产品定位（通用 vs 垂直）、目标市场（C 端/B 端/开发者）、差异化叙事和品牌主张决定竞争维度选择。 | official_site, news, social, analyst_report | 是 |
| target_users_personas | 目标用户与使用场景 | 核心用户群体画像、典型使用场景、Jobs-to-be-done 和用户迁移路径决定产品设计优先级。 | official_site, review, social, news | 是 |
| core_feature_matrix | 核心功能矩阵 | 逐功能对比各竞品的功能覆盖、功能深度、功能限制和版本差异，是产品竞品分析的基础框架。 | official_site, docs, review, marketplace | 是 |
| signature_features | 特色功能与差异化能力 | 各竞品独有或领先的功能（如 ChatGPT 的 GPTs、Cursor 的 Tab 补全、Perplexity 的引用链接），这些是用户选择的决定性因素。 | official_site, docs, review, social, news | 是 |
| product_flow_experience | 产品流程与交互体验 | 新手引导、核心操作流程的步骤数和流畅度、错误处理、多端一致性和响应速度决定用户留存。 | review, official_site, social | 是 |
| ai_output_quality | AI 输出质量与可控性 | 输出准确性、幻觉率、指令遵循能力、输出格式控制和结果一致性是 AI 产品的核心体验指标。 | review, benchmark, social, docs | 是 |
| pricing_business_model | 定价与商业模式 | 免费版/付费版功能差异、订阅价格、用量限制、企业版定价和增值服务决定获客与变现效率。 | pricing_page, official_site, review, news | 是 |
| data_privacy_trust | 数据隐私与用户信任 | 用户数据是否用于训练、数据存储位置、删除权、企业隔离和隐私政策透明度直接影响企业和高隐私需求用户的采用意愿。 | trust_center, official_site, docs, news | 是 |
| ecosystem_integrations | 生态集成与工作流嵌入 | 插件、API、第三方集成、浏览器扩展和与现有工具链的兼容性决定用户迁移成本。 | docs, marketplace, official_site, review | 是 |
| growth_retention_strategy | 增长与留存策略 | 获客渠道（口碑/SEO/社媒/合作）、免费层转化漏斗、使用习惯培养和流失原因分析反映增长健康度。 | social, news, review, official_site | 否 |
| platform_device_coverage | 平台覆盖与多端体验 | Web、桌面、移动、IDE 插件、API 和浏览器扩展的覆盖情况及各端功能完整度差异。 | official_site, review, marketplace, social | 否 |
| user_sentiment_pain_points | 用户评价与核心痛点 | 公开评论中反映的高频好评点和差评点，如速度、准确性、价格、限制和稳定性。 | review, social, marketplace | 是 |
| content_moderation_limits | 内容审核与使用限制 | 各竞品的内容政策、拒答范围、使用限制和封号机制影响用户可用性感知。 | official_site, docs, review, social | 否 |
| team_funding_momentum | 团队、融资与发展势能 | 创始团队背景、融资轮次与估值、招聘方向和合作伙伴信号反映竞品的资源禀赋和战略方向。 | news, job_posting, social, official_site | 否 |

---

## 三、其他行业补充建议

### 3.1 跨行业通用方向（建议作为可选方向注入所有行业）

| direction_id | 名称 | reason |
|---|---|---|
| market_positioning_landscape | 市场定位与竞争格局 | 竞品的目标市场定位（高端/中端/下沉）、市场份额和竞争策略（差异化/成本领先/聚焦）是竞品分析的起点框架。 |
| team_funding_signal | 团队与融资信号 | 创始人背景、核心团队、融资历史、招聘方向和投资人构成可推断竞品的资源优势和战略走向。 |
| regulatory_risk_overview | 监管与政策风险概览 | 行业准入政策、近期监管动态和合规风险对竞品经营稳定性的影响。 |

### 3.2 SaaS / 协作文档 — 建议新增

| direction_id | 名称 | reason | required |
|---|---|---|---|
| migration_switching_cost | 迁移成本与锁定风险 | 数据导出能力、API 开放度、格式兼容性和官方迁移工具决定用户被锁定程度和竞品替换难度。 | 否 |
| enterprise_adoption_signal | 企业采用信号与标杆客户 | 公开的企业客户案例、行业渗透率、大客户背书和 G2/Gartner 评级影响 B2B 采购决策。 | 否 |

### 3.3 电商 / 零售 — 建议新增

| direction_id | 名称 | reason | required |
|---|---|---|---|
| cross_border_compliance | 跨境电商与合规 | 跨境物流、关税、本地化支付、语言支持和各国合规要求决定国际化竞争力。 | 否 |
| user_retention_repurchase | 用户留存与复购机制 | 个性化推荐、购后关怀、复购提醒、订阅制和购物车唤回策略影响 LTV。 | 否 |

### 3.4 教育科技 — 建议新增

| direction_id | 名称 | reason | required |
|---|---|---|---|
| b2b_enterprise_training | 企业培训与 B2B 场景 | 企业版功能、LMS 集成、团队管理、学习路径定制和 ROI 报告决定企业采购价值。 | 否 |
| content_localization | 内容本地化与多语言 | 课程语言覆盖、字幕、本地讲师和区域合作决定非英语市场渗透力。 | 否 |

### 3.5 医疗健康 — 建议新增

| direction_id | 名称 | reason | required |
|---|---|---|---|
| ai_clinical_decision | AI 辅助诊断与临床决策 | AI 影像、辅助诊断、用药推荐和临床决策支持的准确率、审批状态和实际应用场景。 | 否 |
| patient_experience_nps | 患者体验与满意度 | 预约便利性、等待时间、沟通质量、随访体验和 NPS 分数反映服务差异。 | 否 |

### 3.6 汽车 / 新能源 — 建议新增

| direction_id | 名称 | reason | required |
|---|---|---|---|
| brand_community_loyalty | 品牌社区与用户忠诚度 | 车主社区活跃度、官方 App 功能、车主活动和转介绍率反映品牌粘性和口碑传播力。 | 否 |
| used_car_residual_value | 二手残值与保值率 | 1-3 年保值率、二手交易活跃度和官方认证二手车计划影响购买决策和品牌长期价值。 | 否 |

### 3.7 企业服务 / B2B — 建议新增

| direction_id | 名称 | reason | required |
|---|---|---|---|
| ai_capability_roadmap | AI 能力与产品路线图 | AI Copilot、自动化、预测分析和 AI 集成路线图是 2025 年后企业软件的核心差异化趋势。 | 否 |
| partner_channel_ecosystem | 合作伙伴与渠道生态 | ISV、SI、咨询公司和分销渠道的广度和质量影响企业软件的市场覆盖和实施能力。 | 否 |

---

## 四、实施优先级建议

| 优先级 | 任务 | 原因 |
|---|---|---|
| P0 | 拆分 `ai_tools_llm` → `ai_model_platform` + `ai_product_application` | 这是当前最大的覆盖缺口，且你们团队明确需要 |
| P1 | 为所有行业补充 `market_positioning_landscape` 通用方向 | 几乎所有竞品分析都需要定位分析作为起点 |
| P2 | 各行业逐步补充 3.2-3.7 的方向 | 渐进式完善，每个行业增加 1-2 个方向 |
| P3 | 建立"通用方向"机制 | 目前 directions.py 没有跨行业复用结构，后续需要设计 |

---

## 五、待团队讨论的问题

1. **AI 行业是否真的要拆成两个？** 还是保持一个 `ai_tools_llm` 但按场景动态调整方向？
2. **通用方向（市场定位、团队融资）是写进每个行业的 directions 里，还是做一个独立的 `common_directions` 列表？** 后者需要改 IndustryDirectionSkill 的合并逻辑。
3. **`ai_product_application` 的 aliases 怎么设计？** 需要能匹配"AI 产品"、"智能体"、"Copilot"、"AI 应用"等关键词，但不要和 `ai_model_platform` 混淆。
4. **direction 的 reason 字段是否要区分"为什么调研"和"具体调研什么"？** 当前两者混在一起，后续 CollectorAgent 可能需要更精确的 search_focus。
