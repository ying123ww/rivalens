# Rivalens — Traceable Multi-Agent Competitor Analysis

<p align="right">
  <a href="./README.zh-CN.md">中文</a>
</p>

<p align="center">
  <strong>AI-driven competitor analysis agent system with traceable evidence workflows</strong>
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

## Overview

Rivalens is a traceable multi-agent competitor analysis system built on LangGraph. It orchestrates specialist agents that plan research scope, collect public evidence, structure knowledge, generate analysis claims with citation support, and produce structured reports — all with end-to-end provenance tracking.

The main package `rivalens` is organized into these domains:

- `rivalens/workflows` — LangGraph DAG orchestration for competitor analysis
- `rivalens/agents` — specialist agents for planning, collection, evidence review, branch control, knowledge structuring, analysis, writing, and publishing
- `rivalens/file_context` — reusable CSV, Excel, JSON, and screenshot context helpers
- `rivalens/schema` — structured competitor knowledge and evidence Pydantic models
- `rivalens/research` — evidence collection adapters, retrievers, scrapers, and the underlying research engine
- `rivalens/industry_templates` — GICS-based industry direction templates for analysis planning
- `rivalens/retrieval` — pgvector-based evidence RAG for post-report Q&A

## Features

- **Multi-agent DAG** — Planner → Collector → Knowledge Structuring → Analyst → Claim Support Reviewer → Writer → Publisher, with typed Pydantic message handoffs
- **Evidence traceability** — every analysis claim cites `KnowledgeFact` atoms, which cite accepted `EvidenceItem` records with source URLs
- **Collection quality loop** — `EvidenceQualityReviewer` accepts/rejects per-source, `CoverageReviewer` tracks success-criteria gaps, follow-up branches resolve coverage gaps
- **Deterministic knowledge extraction** — rule-based fact normalization and atomization (pricing split into free-tier, plan-price, usage-based-billing, etc.) before LLM analysis
- **Claim support gate** — `ClaimSupportReviewer` validates citation support before writing; unsupported claims are revised once or suppressed
- **Industry direction planning** — GICS sector matching with L0/L1/L2 facet templates, LLM fallback for ambiguous industries
- **Multi-retriever search** — configurable retriever chain (Tavily, UniFuncs DeepSearch, Serper, Exa, DuckDuckGo, and more) per collection task
- **PostgreSQL + pgvector** — user auth, session persistence, traceability provenance, and evidence embedding RAG
- **Structured agent messages** — validated JSON handoffs (`research_plan`, `evidence`, `schema`, `analysis`, `claim_support`, `report`, `publish`) replace free-form text between agents
- **Docker Compose** — five-service stack: API server, Celery worker, Next.js frontend, PostgreSQL (pgvector), Redis

## Architecture

```mermaid
flowchart TB
    User["User / product team"] --> Workflow["rivalens.workflows\nLangGraph DAG"]

    Workflow --> Planner["PlanningAgent\nscope, industry directions"]
    Workflow --> Collector["CollectionAgent\npublic evidence collection"]
    Workflow --> Knowledge["KnowledgeStructuringAgent\nEvidenceItem → KnowledgeFact"]
    Workflow --> Analyst["AnalysisAgent\nKnowledgeFact → AnalysisClaim"]
    Workflow --> ClaimSupport["ClaimSupportReviewer\nclaim citation support gate"]
    Workflow --> Writer["ReportWriterAgent\nstructured report"]
    Workflow --> Publisher["PublisherAgent\nartifacts"]

    Planner --> MsgSelection["AgentMessage(type=research_plan)"]
    Collector --> MsgEvidence["AgentMessage(type=evidence)"]
    Knowledge --> MsgSchema["AgentMessage(type=schema)"]
    Analyst --> MsgAnalysis["AgentMessage(type=analysis)"]
    ClaimSupport --> MsgClaimSupport["AgentMessage(type=claim_support)"]

    Collector --> EvidenceCollector["ResearchEngineEvidenceCollector\nEvidenceItem adapter"]
    Collector --> EvidenceReview["EvidenceQualityReviewer\naccepted/rejected evidence"]
    Collector --> SourceMetrics["SourceMetricsBuilder\nsource independence metrics"]
    Collector --> CoverageReview["CoverageReviewer\ncoverage gaps / follow-up tasks"]
    EvidenceCollector --> Modes["ResearchMode\nstandard evidence"]
    Modes --> Engine["ResearchEngine\nsearch, scrape, context"]
    Engine --> Retrievers["Retrievers\nTavily / Exa / Serper / MCP / etc."]
    Engine --> SourceCache["ScrapedSourceCache\ncanonical URL raw page cache"]

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

### Active Workflow DAG

The LangGraph entry point is `rivalens/workflows/agent.py`:

```mermaid
flowchart LR
    A["scope_planner\nPlanningAgent"] --> B["source_collection\nCollectionAgent"]
    B --> C["knowledge_structuring\nKnowledgeStructuringAgent"]
    C --> D["dimension_analysis\nAnalysisAgent"]
    D --> G["claim_support_review\nClaimSupportReviewer"]
    G -->|"accept / suppress after max revision"| E["report_writer\nReportWriterAgent"]
    G -->|"revise claim wording once"| D
    E --> F["publisher\nPublisherAgent"]
```

## Project Structure

```
rivalens/
├── main.py                          # FastAPI entry point (uvicorn)
├── cli.py                           # CLI for standalone research reports
├── pyproject.toml                   # Poetry project config
├── requirements.txt                 # Pip dependencies
├── setup.py                         # setuptools packaging
├── Dockerfile                       # Multi-stage Python image
├── docker-compose.yml               # 5-service stack
├── langgraph.json                   # LangGraph CLI config
├── alembic.ini                      # Database migration config
├── LICENSE                          # Apache 2.0
├── rivalens/                        # Core Python package
│   ├── workflows/                   # LangGraph DAG definitions
│   │   ├── agent.py                 # Graph entry point
│   │   └── competitive_analysis.py  # Full DAG builder
│   ├── agents/                      # Specialist agents (19 modules)
│   │   ├── planning.py              # Scope & industry direction planning
│   │   ├── collection.py            # Evidence collection orchestration
│   │   ├── knowledge_structuring.py # Rule-based fact extraction
│   │   ├── analysis.py              # Claim generation from facts
│   │   ├── claim_support.py         # Citation support review gate
│   │   ├── writing.py               # Structured report generation
│   │   ├── publishing.py            # Artifact export
│   │   ├── evidence_review.py       # Per-source quality review
│   │   ├── coverage_review.py       # Branch-level coverage control
│   │   ├── coverage_state.py        # Root branch coverage ledger
│   │   ├── source_metrics.py        # Accepted-source independence metrics
│   │   ├── source_gap_advisor.py    # LLM-advised source coverage gaps
│   │   ├── industry_direction.py    # GICS industry template matching
│   │   ├── industry_llm_fallback.py # LLM fallback for ambiguous industries
│   │   ├── search_query_builder.py  # Deterministic sub-query generation
│   │   ├── success_criteria.py      # Branch success criteria
│   │   ├── evidence_snippets.py     # Sentence-level evidence support
│   │   ├── specificity.py           # Claim specificity hints
│   │   └── messages.py              # Typed agent message handoffs
│   ├── research/                    # Research engine
│   │   ├── agent.py                 # ResearchAgent
│   │   ├── evidence_collector.py    # ResearchEngineEvidenceCollector
│   │   ├── modes.py                 # ResearchMode definitions
│   │   ├── source_cache.py          # ScrapedSourceCache (SQLite)
│   │   ├── retrievers/              # 18 search retrievers
│   │   ├── scraper/                 # Page scraping & content cleaning
│   │   ├── context/                 # Context compression
│   │   ├── skills/                  # Research skills
│   │   ├── mcp/                     # MCP client & tool selector
│   │   ├── llm_provider/            # LLM provider abstraction
│   │   └── utils/                   # Enums, helpers
│   ├── schema/                      # Pydantic models
│   │   └── competitive.py           # State, evidence, claims, knowledge
│   ├── industry_templates/          # GICS industry direction templates
│   ├── file_context/                # CSV/Excel/JSON/screenshot ingestion
│   ├── retrieval/                   # pgvector evidence RAG
│   └── report_export.py             # Markdown/HTML/PDF/DOCX export
├── backend/                         # FastAPI application
│   ├── server/
│   │   ├── app.py                   # Routes, WebSocket, lifespan
│   │   ├── auth.py                  # JWT auth, scrypt passwords
│   │   ├── user_store.py            # PostgreSQL user CRUD
│   │   ├── trace_store.py           # Traceability persistence
│   │   ├── session_store.py         # Chat session persistence
│   │   ├── report_store.py          # Report CRUD
│   │   ├── evidence_vector_store.py # pgvector embedding index
│   │   ├── rivalens_runner.py       # Workflow execution
│   │   ├── websocket_manager.py     # WebSocket connections
│   │   ├── celery_app.py            # Celery configuration
│   │   ├── celery_tasks.py          # Background report generation
│   │   └── sql_table_create/        # SQL DDL scripts
│   ├── chat/                        # Chat agent with memory
│   ├── memory/                      # Draft & research memory
│   └── report_type/                 # Report type definitions
├── frontend/                        # Static HTML + Next.js app
│   ├── index.html                   # Main page
│   └── nextjs/                      # Next.js 14 application
│       ├── app/                     # App router pages
│       ├── components/              # React components
│       ├── hooks/                   # Custom hooks
│       ├── helpers/                 # Utility functions
│       └── config/                  # Frontend configuration
├── tests/                           # Test suite (8 test files)
├── docs/                            # Architecture & design docs
├── scripts/                         # Utility scripts
│   ├── run_agent_flow.py            # Agent-only local run
│   └── langsmith_smoke.py           # LangSmith connectivity test
└── alembic/                         # Database migrations
    └── versions/                    # Migration scripts
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.11+ |
| **Agent framework** | LangGraph 0.2.x, LangChain 1.x |
| **API server** | FastAPI, Uvicorn |
| **Frontend** | Next.js 14, React 18, Tailwind CSS 3, ECharts 5 |
| **Database** | PostgreSQL 16 + pgvector |
| **Cache / queue** | Redis 7, Celery |
| **Migrations** | Alembic |
| **Package management** | Poetry |
| **LLM providers** | OpenAI, Anthropic (via LangChain adapters) |
| **Search retrievers** | Tavily, UniFuncs DeepSearch, Serper, Exa, DuckDuckGo, Arxiv, Bing, Bocha, Google, PubMed Central, SearchAPI, Searx, Semantic Scholar, SerpAPI, MCP, Xquik, Custom |
| **Scraping** | BeautifulSoup4, lxml, Playwright, PyMuPDF, Firecrawl, Tavily Extract |
| **Export formats** | Markdown, HTML, PDF (WeasyPrint), DOCX |
| **Tracing** | LangSmith |
| **Containerization** | Docker, Docker Compose |

## Getting Started

### Prerequisites

- Python 3.11 or later
- Node.js 18+ (for frontend development)
- Docker and Docker Compose (for full-stack deployment)
- PostgreSQL 16 with pgvector extension (included in Docker Compose)
- Redis 7 (included in Docker Compose)

### Installation

**Poetry (recommended):**

```bash
git clone https://github.com/rivalens/rivalens.git
cd rivalens
poetry install
```

**pip:**

```bash
git clone https://github.com/rivalens/rivalens.git
cd rivalens
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

**Frontend:**

```bash
cd frontend/nextjs
npm install
```

### Configuration

Copy the example environment file and fill in your keys:

```bash
cp .env.langsmith.example .env
```

Essential environment variables:

```env
# LLM
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1

# Search (at minimum one retriever)
TAVILY_API_KEY=tvly-your-key
RETRIEVER=tavily

# Database (Docker Compose defaults)
DATABASE_URL=postgresql://rivalens:123456@localhost:5433/rivalens

# Auth (change for production)
AUTH_JWT_SECRET=replace-with-a-long-random-secret
AUTH_ACCESS_TOKEN_TTL_SECONDS=86400

# Optional: LangSmith tracing
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2-your-key
LANGSMITH_PROJECT=rivalens-local
```

### Run

**Full stack with Docker Compose:**

```bash
docker compose up -d
```

This starts five services:
- `rivalens` API server on port 8000
- `rivalens-worker` Celery worker for background report generation
- `rivalens-nextjs` frontend on port 3000
- `postgres` PostgreSQL 16 + pgvector on port 5433
- `redis` Redis 7 on port 6380

**Backend only (development):**

```bash
python main.py
# FastAPI server at http://localhost:8000
```

**Frontend only (development):**

```bash
cd frontend/nextjs
npm run dev
# Next.js dev server at http://localhost:3000
```

**Agent-only local run (no backend, no Docker):**

```bash
.venv/bin/python scripts/run_agent_flow.py "Compare Feishu and DingTalk for enterprise collaboration"
```

With explicit competitor scope:

```bash
.venv/bin/python scripts/run_agent_flow.py "Analyze Feishu vs DingTalk competitive landscape" \
  --competitor Feishu \
  --competitor DingTalk
```

Options: `--full-budget` for normal collection budget, `--print-report` to print the final report. Output lands in `outputs/agent_runs/`.

**Standalone CLI research report:**

```bash
python cli.py "Your research query" --report_type research_report --tone objective
```

### Test

```bash
poetry run pytest
# or
python -m pytest tests/ -v
```

## API

All routes are defined in `backend/server/app.py`. The backend uses FastAPI with JWT Bearer token authentication. The Next.js frontend stores the access token in an HTTP-only cookie.

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Register new user (email, display_name, password) |
| POST | `/api/auth/login` | Login, returns JWT access token |
| GET | `/api/auth/me` | Get current authenticated user profile |
| PATCH | `/api/auth/me` | Update current user display name |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| POST | `/report/` | Generate a new research report (background or sync) |
| GET | `/api/reports` | List all reports |
| GET | `/api/reports/{research_id}` | Get a single report with full context |
| GET | `/api/reports/{research_id}/status` | Poll report generation status |
| POST | `/api/reports` | Create or update a report |
| PUT | `/api/reports/{research_id}` | Update an existing report |
| DELETE | `/api/reports/{research_id}` | Delete a report and its evidence vectors |
| GET | `/api/reports/{research_id}/chat` | Get chat messages for a report |
| POST | `/api/reports/{research_id}/chat` | Append a chat message to a report |
| GET | `/report/{research_id}` | Download report DOCX file |
| GET | `/api/download/{file_path}` | Download output artifacts |

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sessions` | List user's chat sessions |
| POST | `/api/sessions` | Create a new session |
| GET | `/api/sessions/{session_id}` | Get session details |
| PATCH | `/api/sessions/{session_id}` | Update session metadata (title) |
| PUT | `/api/sessions/{session_id}/memory` | Update session memory |
| POST | `/api/sessions/{session_id}/messages` | Append a message to session |
| DELETE | `/api/sessions/{session_id}` | Delete a session |

### Traceability

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/trace/runs/{run_id}` | Retrieve workflow graph and provenance bundle |

### Analysis

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/rivalens` | Execute Rivalens competitor analysis workflow |
| POST | `/api/industry-directions` | Preview industry direction plan before full analysis |

### Other

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve frontend HTML |
| POST | `/api/chat` | Chat with a report (RAG over evidence + report context) |
| POST | `/upload/` | Upload a file to the document path |
| DELETE | `/files/{filename}` | Delete a file from the document path |
| GET | `/files/` | List uploaded files |
| WebSocket | `/ws` | Real-time workflow communication |

## Agent Workflow

### Agent Roles

**scope_planner** (PlanningAgent) owns planning end-to-end: normalizes competitor inputs, selects an industry using GICS sector matching with L0/L1/L2 facet templates, composes confirmed analysis directions, and emits a `research_plan` handoff to `source_collection`. When the top rule score is below the configured threshold, it falls back to the LLM configured by `INDUSTRY_FALLBACK_LLM`.

**source_collection** (CollectionAgent) expands confirmed analysis dimensions into competitor × dimension collection branches and runs them concurrently through `ResearchEngineEvidenceCollector`. It creates a `competitor_profile` task for each selected competitor so report information cards are backed by explicit public profile evidence.

**knowledge_structuring** (KnowledgeStructuringAgent) uses deterministic rules to normalize and deduplicate accepted evidence into `KnowledgeFact` atoms that cite accepted `EvidenceItem` IDs. Pricing evidence is atomized into free-tier, plan-price, quote-only, usage-based-billing, and annual-discount facts when those signals are present.

**dimension_analysis** (AnalysisAgent) groups facts by competitor, dimension, claim type, subject, predicate, and normalized fact key before generating traceable `AnalysisClaim` records. An optional LLM mode (`RIVALENS_ANALYSIS_LLM`) can organize claim candidates from KnowledgeFact packages.

**claim_support_review** (ClaimSupportReviewer) checks claim-level citation support before writing. When wording is too broad or too strong, it asks `AnalysisAgent` to tighten the claim to the cited evidence; claims without traceable bindings are suppressed.

**report_writer** (ReportWriterAgent) adapts Rivalens claims, `CompetitorKnowledge`, and accepted `EvidenceItem` records into the shared `ReportGenerator` writing path, with SWOT/TOWS matrix skeletons.

**publisher** (PublisherAgent) exports the final report as Markdown, HTML, PDF, and DOCX artifacts.

### Structured Agent Messages

Agents exchange validated JSON messages through `CompetitorAnalysisState.messages`. Each `AgentMessage` contains `sender`, `receiver`, `type`, `payload`, `artifact_ids`, `evidence_ids`, and `created_at`. Message payloads are validated against Pydantic models:

```
research_plan  → ResearchPlanMessagePayload
evidence       → EvidenceMessagePayload
schema         → SchemaMessagePayload
analysis       → AnalysisMessagePayload
claim_support  → ClaimSupportMessagePayload
report         → ReportMessagePayload
publish        → PublishMessagePayload
```

## Evidence Collection

Search is owned by `CollectionAgent`. Other agents consume structured state and messages — they do not call the research engine directly.

```
CollectionAgent
  → ResearchBranch frontier
  → ResearchBrief / ResearchTask queue with success criteria
  → ResearchEngineEvidenceCollector (explicit ResearchMode)
  → ResearchEngine
  → EvidenceItem[]
  → EvidenceQualityReviewer (source-level accepted/rejected)
  → SourceMetricsBuilder (source independence metrics)
  → CoverageReviewer (criterion coverage gaps)
  → BranchCoverageStateBuilder (root branch coverage ledger)
```

### Collection Quality Loop

- **EvidenceQualityReviewer** produces `EvidenceReviewResult` records with accepted/rejected evidence IDs, success-criterion matches, findings, score, and required action.
- **SourceMetricsBuilder** computes deterministic accepted-source metrics: unique canonical URLs, unique domains, independent source count, primary source count, and duplicate source groups.
- **CoverageReviewer** controls branch-level coverage: source-type gaps, satisfied/partial/missing criteria, and gap-driven follow-up task specs. An LLM source-gap advisor judges whether the accepted evidence source mix needs targeted follow-up.
- **BranchCoverageStateBuilder** aggregates each root branch and its follow-up children into `branch_coverage_states`.

### Collection Limits

```env
RIVALENS_MAX_ROOT_BRANCHES=20        # max initial analysis-dimension branches per competitor
RIVALENS_MAX_BRANCH_DEPTH=0          # 0 disables follow-up collection branches
RIVALENS_MAX_EXPANSION_BRANCHES=0    # max follow-up branches from coverage gaps
RIVALENS_MAX_CONCURRENT_COLLECTIONS=3 # concurrent collection branches
RIVALENS_MAX_SUBQUERY_CONCURRENCY=2  # per-branch sub-query processing
```

### Scraped Source Cache

`ScrapedSourceCache` (SQLite) canonicalizes search results by URL (fragments and common tracking parameters removed). Cache hits return the same raw scraped-page shape as a live scrape, but cached pages still pass through `EvidenceQualityReviewer` and `CoverageReviewer` normally.

```env
RIVALENS_SCRAPED_SOURCE_CACHE_ENABLED=true
RIVALENS_SCRAPED_SOURCE_CACHE_PATH=cache/scraped_sources.db
RIVALENS_SCRAPED_SOURCE_CACHE_TTL_SECONDS=86400
```

## Search Retrievers

Rivalens can run multiple search retrievers for the same collection task. Configure a comma-separated `RETRIEVER` value:

```env
RETRIEVER=unifuncs_deepsearch,tavily
SCRAPER=tavily_extract

# UniFuncs Deep Search (Chinese ecosystem discovery)
UNIFUNCS_API_KEY=sk-your-unifuncs-key
UNIFUNCS_DEEPSEARCH_BASE_URL=https://api.unifuncs.com/deepsearch/v1
UNIFUNCS_DEEPSEARCH_MODEL=s3
UNIFUNCS_DEEPSEARCH_LANGUAGE=zh

# Tavily (English web discovery)
TAVILY_API_KEY=tvly-your-tavily-key
```

## PostgreSQL Data

PostgreSQL stores user authentication and durable business provenance. LangSmith handles detailed execution observability (model/tool spans, prompts, outputs, latency, token usage, cost).

### Traceability Chain

`backend/server/trace_store.py` manages traceability tables. Each Rivalens run receives a `running` record before execution; completed runs are stored transactionally at the workflow boundary.

```
analysis_runs
  → workflow_step_executions / workflow_transitions / agent_messages
  → analysis_dimensions → research_branches → research_tasks
  → evidence_items → knowledge_facts → analysis_claims
  → report_sections → artifacts
```

Key many-to-many provenance tables:

- `knowledge_fact_evidence` — facts to source evidence
- `claim_evidence` — claims to source evidence
- `claim_knowledge_facts` — claims to structured facts
- `report_section_claims` — report sections to claims

### Evidence RAG (pgvector)

The `evidence_embeddings` table indexes compact `EvidenceItem` text plus metadata (evidence ID, source URL, competitor, dimension, source type). Report persistence indexes completed report evidence, and the "Ask About Evidence" chat feature retrieves from this table before using report prose.

```env
RIVALENS_ENABLE_EVIDENCE_RAG=true
```

## LangSmith Tracing

Rivalens uses LangGraph and LangChain components, so LangSmith tracing is available with standard `LANGSMITH_*` environment variables:

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2-your-langsmith-key
LANGSMITH_PROJECT=rivalens-local
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=
LANGCHAIN_CALLBACKS_BACKGROUND=false
```

Smoke test:

```bash
.venv/bin/python scripts/langsmith_smoke.py
```

## Optional LLM Analysis

`AnalysisAgent` is rule-based by default. To enable LLM-based claim organization:

```env
RIVALENS_ANALYSIS_LLM=openai:gpt-4.1-mini
RIVALENS_ANALYSIS_LLM_CONCURRENCY=4
RIVALENS_ANALYSIS_LLM_MAX_TOKENS=900
RIVALENS_ANALYSIS_LLM_FACTS_PER_PACKAGE=18
```

Failed packages fall back to rule-generated claims.

## Report Export

Reports are exported in multiple formats via `backend/report_type/` and `rivalens/report_export.py`:

- **Markdown** — primary format
- **HTML** — styled with `backend/styles/pdf_styles.css`
- **PDF** — via WeasyPrint (Linux) or alternative renderer
- **DOCX** — via python-docx

Report types (configured via `report_type` in API requests): `research_report` (summary), `custom_report` (customizable template-based report).

## Security and Privacy

Default configuration documents the structure needed to run the project. Production model keys, database passwords, and tracing credentials should be injected through environment variables or private configuration, not committed to the repository.

The system processes competitor research queries, public web evidence, and generated analysis. Demonstrations, tests, and screenshots should use non-confidential competitor scenarios. If tracing or third-party model services are enabled, review data retention and audit requirements for your deployment context.

Authentication uses scrypt password hashing with unique per-user salts. JWT access tokens have configurable TTL and are stored in HTTP-only cookies by the Next.js frontend. Runs with a `user_id` are visible only to their owner or an admin.

## License

This repository is licensed under the Apache License 2.0. See [LICENSE](./LICENSE) for the full license text.
