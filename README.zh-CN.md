# Rivalens — 可溯源多智能体竞品分析系统

<p align="right">
  <a href="./README.md">English</a>
</p>

<p align="center">
  <strong>AI 驱动的竞品分析智能体系统，具备全链路可溯源的证据工作流</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue?style=flat-square" alt="version">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="python">
  <img src="https://img.shields.io/badge/fastapi-0.104+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="fastapi">
  <img src="https://img.shields.io/badge/langgraph-0.2.x-orange?style=flat-square" alt="langgraph">
  <img src="https://img.shields.io/badge/next.js-14-black?style=flat-square&logo=nextdotjs" alt="nextjs">
  <img src="https://img.shields.io/badge/react-18-61DAFB?style=flat-square&logo=react" alt="react">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square" alt="license">
  <img src="https://img.shields.io/badge/docker-compose-blue?style=flat-square&logo=docker" alt="docker">
</p>

## 概述

Rivalens 是一个基于 LangGraph 的可溯源多智能体竞品分析系统。它编排多个专业智能体，依次完成研究范围规划、公开证据收集、知识结构化、带引用支撑的分析论断生成，以及结构化报告输出——整个过程具备端到端的溯源追踪能力。

核心包 `rivalens` 按以下领域组织：

- `rivalens/workflows` — 基于 LangGraph 的竞品分析 DAG 编排
- `rivalens/agents` — 专业智能体：规划、收集、证据审查、分支控制、知识结构化、分析、写作与发布
- `rivalens/file_context` — 可复用的 CSV、Excel、JSON 和截图上下文处理
- `rivalens/schema` — 结构化竞品知识与证据的 Pydantic 数据模型
- `rivalens/research` — 证据收集适配器、检索器、爬虫及底层研究引擎
- `rivalens/industry_templates` — 基于 GICS 行业分类的分析方向模板
- `rivalens/retrieval` — 基于 pgvector 的证据 RAG，用于报告生成后的问答

## 核心特性

- **多智能体 DAG** — 规划 → 收集 → 知识结构化 → 分析 → 论断支撑审查 → 写作 → 发布，各节点通过类型化的 Pydantic 消息传递
- **证据溯源** — 每条分析论断引用 `KnowledgeFact` 原子事实，后者引用附带源 URL 的 `EvidenceItem` 记录
- **收集质量闭环** — `EvidenceQualityReviewer` 逐源接受/拒绝证据，`CoverageReviewer` 追踪成功标准覆盖缺口，跟进分支解决覆盖不足
- **确定性知识提取** — 基于规则的事实归一化与原子化（如定价证据拆分为免费版、套餐价、按量计费等），再交由 LLM 分析
- **论断支撑门禁** — `ClaimSupportReviewer` 在写作前验证引用支撑；无支撑的论断可修订一次或直接抑制
- **行业方向规划** — GICS 行业匹配配合 L0/L1/L2 分层模板；竞品提取不依赖已选行业模板；覆盖半导体、GPU 与 AI 芯片；无行业信号时显式返回“待确认”
- **多检索器搜索** — 每个收集任务可配置检索器链（Tavily、UniFuncs DeepSearch、Serper、Exa、DuckDuckGo 等）
- **PostgreSQL + pgvector** — 用户认证、会话持久化、溯源追踪及证据嵌入向量 RAG
- **结构化智能体消息** — 经验证的 JSON 消息（`research_plan`、`evidence`、`schema`、`analysis`、`claim_support`、`report`、`publish`）取代自由文本
- **Docker Compose 一键部署** — 五服务栈：API 服务器、Celery Worker、Next.js 前端、PostgreSQL (pgvector)、Redis

## 系统架构

```mermaid
flowchart TB
    User["用户 / 产品团队"] --> Workflow["rivalens.workflows\nLangGraph DAG"]

    Workflow --> Planner["PlanningAgent\n研究范围与行业方向"]
    Workflow --> Collector["CollectionAgent\n公开证据收集"]
    Workflow --> Knowledge["KnowledgeStructuringAgent\nEvidenceItem → KnowledgeFact"]
    Workflow --> Analyst["AnalysisAgent\nKnowledgeFact → AnalysisClaim"]
    Workflow --> ClaimSupport["ClaimSupportReviewer\n论断引用支撑门禁"]
    Workflow --> Writer["ReportWriterAgent\n结构化报告生成"]
    Workflow --> Publisher["PublisherAgent\n产物导出"]

    Planner --> MsgSelection["AgentMessage(type=research_plan)"]
    Collector --> MsgEvidence["AgentMessage(type=evidence)"]
    Knowledge --> MsgSchema["AgentMessage(type=schema)"]
    Analyst --> MsgAnalysis["AgentMessage(type=analysis)"]
    ClaimSupport --> MsgClaimSupport["AgentMessage(type=claim_support)"]

    Collector --> EvidenceCollector["ResearchEngineEvidenceCollector\nEvidenceItem 适配器"]
    Collector --> EvidenceReview["EvidenceQualityReviewer\n接受/拒绝证据"]
    Collector --> SourceMetrics["SourceMetricsBuilder\n来源独立性指标"]
    Collector --> CoverageReview["CoverageReviewer\n覆盖缺口 / 跟进任务"]
    EvidenceCollector --> Modes["ResearchMode\n标准证据模式"]
    Modes --> Engine["ResearchEngine\n搜索、爬取、上下文"]
    Engine --> Retrievers["检索器\nTavily / Exa / Serper / MCP 等"]
    Engine --> SourceCache["ScrapedSourceCache\n按规范 URL 缓存原始页面"]

    Planner --> State["CompetitorAnalysisState"]
    Collector --> State
    Knowledge --> State
    Analyst --> State
    ClaimSupport --> State
    Writer --> State
    Publisher --> State

    State --> Evidence["EvidenceItem"]
    State --> EvidenceReviews["EvidenceReviewResult"]
    State --> DirectionPlan["IndustryDirectionPlan"]
    State --> Dimensions["AnalysisDimension[]"]
    State --> KnowledgeState["CompetitorKnowledge"]
    State --> Claims["AnalysisClaim"]
    State --> ClaimReviews["ClaimSupportReview"]
    State --> Messages["AgentMessage[]"]
    State --> Artifacts["research_artifacts / agent_events"]
```

### 当前工作流 DAG

LangGraph 入口为 `rivalens/workflows/agent.py`：

```mermaid
flowchart LR
    A["scope_planner\nPlanningAgent"] --> B["source_collection\nCollectionAgent"]
    B --> C["knowledge_structuring\nKnowledgeStructuringAgent"]
    C --> D["dimension_analysis\nAnalysisAgent"]
    D --> G["claim_support_review\nClaimSupportReviewer"]
    G -->|"接受 / 超过最大修订次数后抑制"| E["report_writer\nReportWriterAgent"]
    G -->|"修订论断措辞（一次）"| D
    E --> F["publisher\nPublisherAgent"]
```

## 项目结构

```
rivalens/
├── main.py                          # FastAPI 入口 (uvicorn)
├── cli.py                           # 独立研究报告命令行工具
├── pyproject.toml                   # Poetry 项目配置
├── requirements.txt                 # Pip 依赖
├── setup.py                         # setuptools 打包
├── Dockerfile                       # 多阶段 Python 镜像
├── docker-compose.yml               # 五服务 Docker 编排
├── langgraph.json                   # LangGraph CLI 配置
├── alembic.ini                      # 数据库迁移配置
├── LICENSE                          # Apache 2.0
├── rivalens/                        # 核心 Python 包
│   ├── workflows/                   # LangGraph DAG 定义
│   │   ├── agent.py                 # 图入口
│   │   └── competitive_analysis.py  # 完整 DAG 构建器
│   ├── agents/                      # 专业智能体（19 个模块）
│   │   ├── planning.py              # 范围与行业方向规划
│   │   ├── collection.py            # 证据收集编排
│   │   ├── knowledge_structuring.py # 基于规则的事实提取
│   │   ├── analysis.py              # 从事实生成论断
│   │   ├── claim_support.py         # 引用支撑审查门禁
│   │   ├── writing.py               # 结构化报告生成
│   │   ├── publishing.py            # 产物导出
│   │   ├── evidence_review.py       # 逐源质量审查
│   │   ├── coverage_review.py       # 分支级覆盖控制
│   │   ├── coverage_state.py        # 根分支覆盖台账
│   │   ├── source_metrics.py        # 已接受来源独立性指标
│   │   ├── source_gap_advisor.py    # LLM 辅助来源缺口建议
│   │   ├── industry_direction.py    # GICS 行业模板匹配
│   │   ├── industry_llm_fallback.py # 模糊行业 LLM 回退
│   │   ├── search_query_builder.py  # 确定性子查询生成
│   │   ├── success_criteria.py      # 分支成功标准
│   │   ├── evidence_snippets.py     # 句子级证据支撑
│   │   ├── specificity.py           # 论断具体性提示
│   │   └── messages.py              # 类型化智能体消息
│   ├── research/                    # 研究引擎
│   │   ├── agent.py                 # ResearchAgent
│   │   ├── evidence_collector.py    # ResearchEngineEvidenceCollector
│   │   ├── modes.py                 # ResearchMode 定义
│   │   ├── source_cache.py          # ScrapedSourceCache (SQLite)
│   │   ├── retrievers/              # 18 种搜索检索器
│   │   ├── scraper/                 # 页面爬取与内容清洗
│   │   ├── context/                 # 上下文压缩
│   │   ├── skills/                  # 研究技能
│   │   ├── mcp/                     # MCP 客户端与工具选择器
│   │   ├── llm_provider/            # LLM 提供商抽象
│   │   └── utils/                   # 枚举与工具函数
│   ├── schema/                      # Pydantic 数据模型
│   │   └── competitive.py           # 状态、证据、论断、知识
│   ├── industry_templates/          # GICS 行业方向模板
│   ├── file_context/                # CSV/Excel/JSON/截图输入
│   ├── retrieval/                   # pgvector 证据 RAG
│   └── report_export.py             # Markdown/HTML/PDF/DOCX 导出
├── backend/                         # FastAPI 应用
│   ├── server/
│   │   ├── app.py                   # 路由、WebSocket、生命周期
│   │   ├── auth.py                  # JWT 认证, scrypt 密码
│   │   ├── user_store.py            # PostgreSQL 用户 CRUD
│   │   ├── trace_store.py           # 溯源追踪持久化
│   │   ├── session_store.py         # 聊天会话持久化
│   │   ├── report_store.py          # 报告持久化
│   │   ├── evidence_vector_store.py # pgvector 嵌入索引
│   │   ├── rivalens_runner.py       # 工作流执行
│   │   ├── websocket_manager.py     # WebSocket 连接管理
│   │   ├── celery_app.py            # Celery 配置
│   │   ├── celery_tasks.py          # 后台报告生成
│   │   └── sql_table_create/        # SQL DDL 脚本
│   ├── chat/                        # 带记忆的聊天智能体
│   ├── memory/                      # 草稿与研究记忆
│   └── report_type/                 # 报告类型定义
├── frontend/                        # 静态 HTML + Next.js 应用
│   ├── index.html                   # 主页面
│   └── nextjs/                      # Next.js 14 应用
│       ├── app/                     # App Router 页面
│       ├── components/              # React 组件
│       ├── hooks/                   # 自定义 Hooks
│       ├── helpers/                 # 工具函数
│       └── config/                  # 前端配置
├── tests/                           # 测试套件（8 个测试文件）
├── docs/                            # 架构与设计文档
├── scripts/                         # 工具脚本
│   ├── run_agent_flow.py            # 仅智能体的本地运行
│   └── langsmith_smoke.py           # LangSmith 连通性测试
└── alembic/                         # 数据库迁移
    └── versions/                    # 迁移脚本
```

## 技术栈

| 层级 | 技术 |
|------|------|
| **语言** | Python 3.11+ |
| **智能体框架** | LangGraph 0.2.x, LangChain 1.x |
| **API 服务器** | FastAPI, Uvicorn |
| **前端** | Next.js 14, React 18, Tailwind CSS 3, ECharts 5 |
| **数据库** | PostgreSQL 16 + pgvector |
| **缓存/队列** | Redis 7, Celery |
| **数据迁移** | Alembic |
| **包管理** | Poetry |
| **LLM 提供商** | OpenAI, Anthropic（通过 LangChain 适配器） |
| **搜索检索器** | Tavily, UniFuncs DeepSearch, Serper, Exa, DuckDuckGo, Arxiv, Bing, Bocha, Google, PubMed Central, SearchAPI, Searx, Semantic Scholar, SerpAPI, MCP, Xquik, Custom |
| **页面爬取** | BeautifulSoup4, lxml, Playwright, PyMuPDF, Firecrawl, Tavily Extract |
| **导出格式** | Markdown, HTML, PDF (WeasyPrint), DOCX |
| **追踪** | LangSmith |
| **容器化** | Docker, Docker Compose |

## 前端体验

Next.js 应用提供三个主要用户入口：

| 路由 | 用途 |
|------|------|
| `/` | 品牌入口、登录注册、竞品输入、行业方向确认与分析工作台 |
| `/research/{id}` | 历史报告查看、基于来源的报告问答、分享及返回工作台 |
| `/monitoring` | 跨运行记录的监控与溯源看板 |

Monitoring 看板直接使用报告接口返回的结构化上下文，提供以下能力：

- 展示证据、结论、一手来源、支撑复核、置信度和 Agent 流水线进度；
- 与上一轮运行对比，识别新增来源、新增结论、支撑状态变化和置信度波动；
- 通过关键词、复核状态和分析维度筛选 Claim Explorer 结论库；
- 按“竞品 → 分析维度 → 结论 → 来源 URL”查看证据关系；
- 完整展示待复核结论，并使用面向用户的自然语言标签；底层追踪数据仍保留原始结论与证据标识。

登录用户可通过 `/api/auth/me` 修改显示名称。个人资料弹窗还支持不超过 3 MB 的可选头像，头像按用户保存在浏览器 `localStorage` 中并显示于工作台顶部，不会上传到后端。

## 快速开始

### 环境要求

- Python 3.11 或更高版本
- Node.js 18+（前端开发）
- Docker 与 Docker Compose（全栈部署）
- PostgreSQL 16 含 pgvector 扩展（Docker Compose 已包含）
- Redis 7（Docker Compose 已包含）

### 安装

**Poetry（推荐）：**

```bash
git clone https://github.com/rivalens/rivalens.git
cd rivalens
poetry install
```

**pip：**

```bash
git clone https://github.com/rivalens/rivalens.git
cd rivalens
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**前端：**

```bash
cd frontend/nextjs
npm install
```

### 配置

复制示例环境文件并填入你的密钥：

```bash
cp .env.langsmith.example .env
```

关键环境变量：

```env
# LLM
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1

# 搜索（至少配置一个检索器）
TAVILY_API_KEY=tvly-your-key
RETRIEVER=tavily

# 数据库（Docker Compose 默认值）
DATABASE_URL=postgresql://rivalens:123456@localhost:5433/rivalens

# 认证（生产环境务必修改）
AUTH_JWT_SECRET=replace-with-a-long-random-secret
AUTH_ACCESS_TOKEN_TTL_SECONDS=86400

# 可选：LangSmith 追踪
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2-your-key
LANGSMITH_PROJECT=rivalens-local
```

### 运行

**Docker Compose 全栈部署：**

```bash
docker compose up -d
```

启动全部五个服务：
- `rivalens` API 服务器，端口 8000
- `rivalens-worker` Celery Worker，后台报告生成
- `rivalens-nextjs` 前端，端口 3000
- `postgres` PostgreSQL 16 + pgvector，端口 5433
- `redis` Redis 7，端口 6380

**仅后端（开发模式）：**

```bash
python main.py
# FastAPI 服务器运行在 http://localhost:8000
```

**仅前端（开发模式）：**

```bash
cd frontend/nextjs
npm run dev
# Next.js 开发服务器运行在 http://localhost:3000
```

**仅智能体本地运行（无需后端、无需 Docker）：**

```bash
.venv/bin/python scripts/run_agent_flow.py "比较飞书和钉钉的企业协同能力"
```

指定竞品范围：

```bash
.venv/bin/python scripts/run_agent_flow.py "分析飞书和钉钉的企业协同竞争格局" \
  --competitor 飞书 \
  --competitor 钉钉
```

可选参数：`--full-budget` 使用正常收集预算，`--print-report` 在终端打印最终报告。输出位于 `outputs/agent_runs/`。

**独立 CLI 研究报告：**

```bash
python cli.py "你的研究问题" --report_type research_report --tone objective
```

> **部署**：使用 Docker Compose + Nginx 反向代理，详见 `nginx-server.conf` 和 `docker-compose.yml`。

### 测试

```bash
poetry run pytest
# 或
python -m pytest tests/ -v
```

## API 接口

后端路由定义在 `backend/server/app.py`。后端使用 FastAPI 搭配 JWT Bearer Token 认证。Next.js 应用通过 `frontend/nextjs/app/api` 提供同源 Route Handler，并将 access token 存储在 HTTP-only cookie 中。

### Next.js Route Handler

| 方法 | 前端路径 | 代理的后端能力 |
|------|----------|----------------|
| POST | `/api/auth/register` | 注册用户并建立浏览器登录会话 |
| POST | `/api/auth/login` | 完成认证并设置 access-token cookie |
| POST | `/api/auth/logout` | 清除浏览器登录会话 |
| GET、PATCH | `/api/auth/me` | 获取或更新当前用户资料 |
| GET、POST | `/api/reports` | 获取报告列表或创建/更新报告 |
| GET、PUT、DELETE | `/api/reports/{id}` | 获取、更新或删除单个报告 |
| GET | `/api/reports/{id}/status` | 查询报告生成状态 |
| GET、POST | `/api/reports/{id}/chat` | 获取或追加报告问答消息 |
| POST | `/api/industry-directions` | 预览识别出的行业与分析方向 |
| POST | `/api/chat` | 提交基于报告与证据的问答请求 |

### 认证

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| POST | `/api/auth/register` | 注册新用户（email, display_name, password） |
| POST | `/api/auth/login` | 登录，返回 JWT access token |
| GET | `/api/auth/me` | 获取当前认证用户信息 |
| PATCH | `/api/auth/me` | 更新当前用户显示名称 |

### 报告

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| POST | `/report/` | 生成新的研究报告（后台或同步） |
| GET | `/api/reports` | 列出所有报告 |
| GET | `/api/reports/{research_id}` | 获取单个报告及完整上下文 |
| GET | `/api/reports/{research_id}/status` | 查询报告生成状态 |
| POST | `/api/reports` | 创建或更新报告 |
| PUT | `/api/reports/{research_id}` | 更新已有报告 |
| DELETE | `/api/reports/{research_id}` | 删除报告及其证据向量 |
| GET | `/api/reports/{research_id}/chat` | 获取报告的聊天消息 |
| POST | `/api/reports/{research_id}/chat` | 向报告追加聊天消息 |
| GET | `/report/{research_id}` | 下载报告 DOCX 文件 |
| GET | `/api/download/{file_path}` | 下载输出产物 |

### 会话

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| GET | `/api/sessions` | 列出用户的聊天会话 |
| POST | `/api/sessions` | 创建新会话 |
| GET | `/api/sessions/{session_id}` | 获取会话详情 |
| PATCH | `/api/sessions/{session_id}` | 更新会话元数据（标题） |
| PUT | `/api/sessions/{session_id}/memory` | 更新会话记忆 |
| POST | `/api/sessions/{session_id}/messages` | 向会话追加消息 |
| DELETE | `/api/sessions/{session_id}` | 删除会话 |

### 溯源追踪

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| GET | `/api/trace/runs/{run_id}` | 获取工作流图及完整溯源数据包 |

### 分析

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| POST | `/api/rivalens` | 执行 Rivalens 竞品分析工作流 |
| POST | `/api/industry-directions` | 完整分析前预览行业方向计划 |

### 其他

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| GET | `/` | 提供前端 HTML 页面 |
| POST | `/api/chat` | 与报告对话（基于证据 + 报告上下文的 RAG） |
| POST | `/upload/` | 上传文件到文档目录 |
| DELETE | `/files/{filename}` | 从文档目录删除文件 |
| GET | `/files/` | 列出已上传文件 |
| WebSocket | `/ws` | 实时工作流通信 |

## 智能体工作流

### 智能体角色

**scope_planner**（PlanningAgent）端到端负责规划阶段：归一化竞品输入，从查询文本中独立提取明确的竞品组合，使用 GICS 行业匹配（L0/L1/L2 分层模板）选择行业，组合确认的分析方向，并向 `source_collection` 发送 `research_plan` 消息。完全没有确定性行业信号时，系统返回带通用 L0 分析方向的“待确认”计划，不再继承首个行业模板。

**source_collection**（CollectionAgent）将确认的分析维度展开为"竞品 × 维度"收集分支，通过 `ResearchEngineEvidenceCollector` 并发执行。为每个选定竞品创建 `competitor_profile` 任务，确保报告信息卡片有明确的公开资料证据支撑。

**knowledge_structuring**（KnowledgeStructuringAgent）使用确定性规则将已接受证据归一化、去重，生成引用 `EvidenceItem.id` 的 `KnowledgeFact` 原子事实。当证据中存在定价信号时，自动拆分为免费版、套餐价、询价制、按量计费和年度折扣等原子事实。

**dimension_analysis**（AnalysisAgent）按竞品、维度、论断类型、主题、谓词和归一化事实键对事实进行分组，生成可溯源的 `AnalysisClaim` 记录。可通过 `RIVALENS_ANALYSIS_LLM` 配置可选的 LLM 模式来组织候选论断。

**claim_support_review**（ClaimSupportReviewer）在写作前检查每条论断的引用支撑。当措辞过于宽泛或过于强烈时，要求 `AnalysisAgent` 将论断收紧到所引用证据的范围内；无可溯源绑定的论断在写作前被抑制。

**report_writer**（ReportWriterAgent）将 Rivalens 论断、`CompetitorKnowledge` 和已接受的 `EvidenceItem` 记录适配到共享的 `ReportGenerator` 写作路径，包含 SWOT/TOWS 矩阵骨架。

**publisher**（PublisherAgent）将最终报告导出为 Markdown、HTML、PDF 和 DOCX 产物。

### 结构化智能体消息

智能体通过 `CompetitorAnalysisState.messages` 交换经验证的 JSON 消息。每条 `AgentMessage` 包含 `sender`、`receiver`、`type`、`payload`、`artifact_ids`、`evidence_ids` 和 `created_at`。消息载荷在追加到状态之前须通过 Pydantic 模型验证：

```
research_plan  → ResearchPlanMessagePayload
evidence       → EvidenceMessagePayload
schema         → SchemaMessagePayload
analysis       → AnalysisMessagePayload
claim_support  → ClaimSupportMessagePayload
report         → ReportMessagePayload
publish        → PublishMessagePayload
```

## 证据收集

搜索由 `CollectionAgent` 独有。其他智能体消费结构化状态和消息，不直接调用研究引擎。

```
CollectionAgent
  → ResearchBranch 前沿队列
  → ResearchBrief / ResearchTask 队列（含成功标准）
  → ResearchEngineEvidenceCollector（显式 ResearchMode）
  → ResearchEngine
  → EvidenceItem[]
  → EvidenceQualityReviewer（源级别接受/拒绝证据）
  → SourceMetricsBuilder（来源独立性指标）
  → CoverageReviewer（标准覆盖缺口）
  → BranchCoverageStateBuilder（根分支覆盖台账）
```

### 收集质量闭环

- **EvidenceQualityReviewer** 在每次标准搜索后立即运行，生成包含接受/拒绝证据 ID、成功标准匹配、发现、评分和所需操作的 `EvidenceReviewResult` 记录。
- **SourceMetricsBuilder** 计算确定性的已接受来源指标：唯一规范 URL 数、唯一域名数、独立来源数、主要来源数及重复来源组。
- **CoverageReviewer** 控制分支级覆盖：来源类型缺口、已满足/部分满足/缺失的标准，以及缺口驱动的跟进任务规格。LLM 来源缺口顾问判断已接受证据的来源组合是否需要针对性跟进。
- **BranchCoverageStateBuilder** 将每个根分支及其跟进子分支聚合为 `branch_coverage_states`。

### 收集限制

```env
RIVALENS_MAX_ROOT_BRANCHES=20        # 每个竞品最大初始分析维度分支数
RIVALENS_MAX_BRANCH_DEPTH=0          # 设为 0 禁用跟进收集分支
RIVALENS_MAX_EXPANSION_BRANCHES=0    # 覆盖缺口产生的最大跟进分支数
RIVALENS_MAX_CONCURRENT_COLLECTIONS=3 # 并发收集分支数
RIVALENS_MAX_SUBQUERY_CONCURRENCY=2  # 每分支子查询并发数
```

### 爬取来源缓存

`ScrapedSourceCache`（SQLite）按规范 URL（去除片段和常见追踪参数）缓存页面内容。缓存命中返回与实时爬取相同的原始页面结构，但缓存页面仍须正常通过质量审查和覆盖审查。

```env
RIVALENS_SCRAPED_SOURCE_CACHE_ENABLED=true
RIVALENS_SCRAPED_SOURCE_CACHE_PATH=cache/scraped_sources.db
RIVALENS_SCRAPED_SOURCE_CACHE_TTL_SECONDS=86400
```

## 搜索检索器

Rivalens 可为同一收集任务运行多个搜索检索器。通过逗号分隔的 `RETRIEVER` 值配置：

```env
RETRIEVER=unifuncs_deepsearch,tavily
SCRAPER=tavily_extract

# UniFuncs Deep Search（中文生态发现）
UNIFUNCS_API_KEY=sk-your-unifuncs-key
UNIFUNCS_DEEPSEARCH_BASE_URL=https://api.unifuncs.com/deepsearch/v1
UNIFUNCS_DEEPSEARCH_MODEL=s3
UNIFUNCS_DEEPSEARCH_LANGUAGE=zh

# Tavily（英文网络发现）
TAVILY_API_KEY=tvly-your-tavily-key
```

## PostgreSQL 数据

PostgreSQL 存储用户认证和持久化业务溯源。LangSmith 负责详细的执行可观测性（模型/工具跨度、提示、输出、延迟、Token 用量、成本）。

### 溯源链

`backend/server/trace_store.py` 管理溯源表。每次 Rivalens 运行在执行前获得 `running` 记录；完成的运行在工作流边界事务性存储。

```
analysis_runs
  → workflow_step_executions / workflow_transitions / agent_messages
  → analysis_dimensions → research_branches → research_tasks
  → evidence_items → knowledge_facts → analysis_claims
  → report_sections → artifacts
```

关键多对多溯源关系表：

- `knowledge_fact_evidence` — 事实到来源证据
- `claim_evidence` — 论断到来源证据
- `claim_knowledge_facts` — 论断到结构化事实
- `report_section_claims` — 报告章节到论断

### 证据 RAG（pgvector）

`evidence_embeddings` 表索引精简的 `EvidenceItem` 文本及元数据（证据 ID、来源 URL、竞品、维度、来源类型）。报告持久化时索引已完成报告的证据，"追问证据"聊天功能在利用报告正文之前从此表检索。

```env
RIVALENS_ENABLE_EVIDENCE_RAG=true
```

## LangSmith 追踪

Rivalens 使用 LangGraph 和 LangChain 组件，可通过标准 `LANGSMITH_*` 环境变量启用 LangSmith 追踪：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2-your-langsmith-key
LANGSMITH_PROJECT=rivalens-local
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=
LANGCHAIN_CALLBACKS_BACKGROUND=false
```

连通性测试：

```bash
.venv/bin/python scripts/langsmith_smoke.py
```

## 可选 LLM 分析

`AnalysisAgent` 默认基于规则。启用 LLM 驱动的论断组织：

```env
RIVALENS_ANALYSIS_LLM=openai:gpt-4.1-mini
RIVALENS_ANALYSIS_LLM_CONCURRENCY=4
RIVALENS_ANALYSIS_LLM_MAX_TOKENS=900
RIVALENS_ANALYSIS_LLM_FACTS_PER_PACKAGE=18
```

失败的包回退至规则生成的论断。

## 报告导出

报告通过 `backend/report_type/` 和 `rivalens/report_export.py` 以多种格式导出：

- **Markdown** — 主要格式
- **HTML** — 使用 `backend/styles/pdf_styles.css` 样式
- **PDF** — 通过 WeasyPrint（Linux）或替代渲染器
- **DOCX** — 通过 python-docx

报告类型（通过 API 请求的 `report_type` 参数配置）：`research_report`（摘要型报告）、`custom_report`（自定义模板报告）。

## 安全与隐私

项目默认配置只保留运行所需的配置结构。生产环境中的模型 Key、数据库密码和追踪服务凭据应通过环境变量或私有配置注入，不建议写入仓库。

系统处理竞品研究查询、公开网页证据和生成的分析内容。演示、测试和截图时请使用非敏感的竞品场景。如启用追踪或第三方模型服务，需要根据部署场景确认数据留存和审计要求。

认证使用 scrypt 密码哈希加每用户独立盐值。JWT access token 具有可配置的 TTL，由 Next.js 前端存储在 HTTP-only cookie 中。带 `user_id` 的运行仅对其所有者或管理员可见。

## 许可证

本仓库采用 Apache License 2.0 许可。详见 [LICENSE](./LICENSE)。
