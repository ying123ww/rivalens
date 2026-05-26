# Rivalens

Rivalens is an AI-driven competitor analysis agent system.

The project is being shaped into a traceable multi-agent workflow for market
intelligence. The main package is `rivalens`, with these primary domains:

- `rivalens/workflows`: DAG task orchestration for competitor analysis.
- `rivalens/agents`: specialist agents for planning, collection, collection-time evidence review, branch control, knowledge structuring, analysis, writing, and publishing.
- `rivalens/file_context`: reusable CSV, Excel, JSON, and screenshot context helpers.
- `rivalens/schema`: structured competitor knowledge and evidence schema.
- `rivalens/research`: evidence collection adapters, retrievers, and the underlying research engine.

The generic research implementation lives inside `rivalens/research` as the web
research engine beneath Rivalens agents.

## Persistence

Docker Compose provisions two persistence services:

- `postgres`: PostgreSQL 16, default database `rivalens`.
- `redis`: Redis 7 with append-only persistence enabled.

The application receives these endpoints through `DATABASE_URL` and `REDIS_URL`.
PostgreSQL data is stored in the `rivalens-postgres-data` Docker volume, and
Redis data is stored in `rivalens-redis-data`. No application tables are created
yet; `backend/server/persistence.py` only centralizes endpoint configuration for
future schema and repository wiring.

## Architecture

```mermaid
flowchart TB
    User["User / product team"] --> Workflow["rivalens.workflows\nLangGraph DAG"]

    Workflow --> Planner["PlanningAgent\nscope, active schema"]
    Workflow --> Collector["CollectionAgent\npublic evidence collection"]
    Workflow --> Knowledge["KnowledgeStructuringAgent\nEvidenceItem -> CompetitorKnowledge"]
    Workflow --> Analyst["AnalysisAgent\nCompetitorKnowledge -> AnalysisClaim"]
    Workflow --> Writer["ReportWriterAgent\nstructured report"]
    Workflow --> Publisher["PublisherAgent\nartifacts"]

    Planner --> MsgSelection["AgentMessage(type=schema_selection)"]
    Collector --> MsgEvidence["AgentMessage(type=evidence)"]
    Knowledge --> MsgSchema["AgentMessage(type=schema)"]
    Analyst --> MsgAnalysis["AgentMessage(type=analysis)"]
    MsgSelection --> MsgGuard
    MsgEvidence --> MsgGuard
    MsgSchema --> MsgGuard
    MsgAnalysis --> MsgGuard

    Collector --> EvidenceCollector["ResearchEngineEvidenceCollector\nEvidenceItem adapter"]
    Collector --> EvidenceReview["EvidenceQualityReviewer\naccepted/rejected evidence"]
    Collector --> BranchReview["BranchReviewAgent\nexpand/retry/fail/stop"]
    EvidenceCollector --> Modes["ResearchMode\nstandard/deep evidence"]
    Modes --> Engine["ResearchEngine\nsearch, scrape, context"]
    Engine --> Retrievers["Retrievers\nTavily / Exa / Serper / MCP / local / etc."]

    Planner --> State["CompetitorAnalysisState"]
    Collector --> State
    Knowledge --> State
    Analyst --> State
    Writer --> State
    Publisher --> State

    State --> Evidence["EvidenceItem"]
    State --> EvidenceReviews["EvidenceReviewResult"]
    State --> ActiveSchema["ActiveKnowledgeSchema"]
    State --> KnowledgeState["CompetitorKnowledge"]
    State --> Claims["AnalysisClaim"]
    State --> Messages["AgentMessage[]"]
    State --> Artifacts["research_artifacts / agent_events"]
```

## Active Workflow

The active LangGraph entry point is `rivalens/workflows/agent.py`. Its current
multi-agent DAG is:

```mermaid
flowchart LR
    A["scope_planner\nPlanningAgent"] --> B["source_collection\nCollectionAgent"]
    B --> C["knowledge_structuring\nKnowledgeStructuringAgent"]
    C --> D["dimension_analysis\nAnalysisAgent"]
    D --> E["report_writer\nReportWriterAgent"]
    E --> F["publisher\nPublisherAgent"]
```

`scope_planner` owns the planning phase end to end: it normalizes competitor
inputs, selects and freezes an `ActiveKnowledgeSchema` from the schema registry,
then emits one `schema_selection` handoff to
`source_collection`. `source_collection` expands that schema into competitor-by-
dimension collection tasks and runs them concurrently through
`ResearchEngineEvidenceCollector`, which wraps
`rivalens.research.ResearchEngine` as a narrow evidence adapter. It normalizes
research sources into `EvidenceItem` records with collection task and schema
dimension metadata, reviews each standard-search result, and passes only
accepted evidence into knowledge structuring. The final report is produced only
after accepted evidence has been structured into `CompetitorKnowledge` and
analyzed into traceable claims.

CSV, Excel, JSON, and screenshot inputs are ingested by `rivalens/file_context`
instead of being modeled as agents. `PlanningAgent` uses the resulting summaries
and search hints during outline generation and schema selection. Collection,
knowledge structuring, and analysis reuse the same file chunks as local RAG
context while preserving the external evidence pipeline.

## Structured Agent Messages

Agents exchange validated JSON messages through
`CompetitorAnalysisState.messages`. Each `AgentMessage` contains `sender`,
`receiver`, `type`, `payload`, `artifact_ids`, `evidence_ids`, and `created_at`.
The payload is validated before it is appended to state. Active handoffs
currently use these Pydantic payloads:

```text
schema_selection -> SchemaSelectionMessagePayload
evidence -> EvidenceMessagePayload
schema   -> SchemaMessagePayload
analysis -> AnalysisMessagePayload
report   -> ReportMessagePayload
publish  -> PublishMessagePayload
```

Downstream agents consume the latest validated message addressed to them with
`latest_message_for(...)`. This makes each DAG edge behave more like a
function-calling contract: the shared state remains observable, but the handoff
between agents has explicit typed inputs instead of arbitrary free-form text.

## Evidence Collection Boundary

Search is intentionally owned by `CollectionAgent`. Other agents consume
structured state and messages; they do not call the research engine directly.

`CollectionAgent` calls `ResearchEngineEvidenceCollector`, which keeps the
ResearchEngine wiring out of agent business logic:

```text
CollectionAgent
  -> ResearchBranch frontier
  -> EvidenceCollectionTask
  -> ResearchEngineEvidenceCollector (standard evidence)
  -> ResearchEngine
  -> EvidenceItem[]
  -> EvidenceQualityReviewer (accept/retry/expand/fail recommendation)
  -> BranchReviewAgent (expand/retry/fail/stop branch decision)
```

The collection path uses standard evidence collection for each branch. Deep
research recursion is not used as a black box inside `ResearchEngine`; instead,
Rivalens keeps branch lineage, evidence reviews, branch review decisions,
depth, and budget in `CompetitorAnalysisState.research_branches`,
`CompetitorAnalysisState.evidence_reviews`, and
`CompetitorAnalysisState.branch_review_decisions`.

Root branches are required schema coverage: every competitor x active schema
dimension is collected before any depth expansion is considered. The expansion
budget applies only to child branches created by `BranchReviewAgent`, with
`max_root_branch_hard_limit` acting as a defensive cap for unusually large
schemas and `max_expansion_branches` controlling follow-up breadth.

This keeps provider calls, source normalization, costs, and evidence metadata in
one place while preserving the main Rivalens chain:

```text
EvidenceItem -> CompetitorKnowledge -> AnalysisClaim -> Report
```

`PlanningAgent`, `KnowledgeStructuringAgent`, `AnalysisAgent`, and
`ReportWriterAgent` do not run their own research/report modes by default. The
previous end-of-pipeline `QualityAgent` and `RevisionAgent` have been removed
because they created a late, claim-deletion-oriented pseudo loop.
`EvidenceQualityReviewer` now runs immediately after each standard search and
produces `EvidenceReviewResult` records with accepted/rejected evidence IDs,
findings, score, and required action. `BranchReviewAgent` consumes that result
and remains responsible for branch-level search control: depth, budget, drift
risk, child query generation, and the final expand/retry/fail/stop decision.
