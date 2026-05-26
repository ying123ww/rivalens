# Rivalens

Rivalens is an AI-driven competitor analysis agent system.

The project is being shaped into a traceable multi-agent workflow for market
intelligence. The main package is `rivalens`, with these primary domains:

- `rivalens/workflows`: DAG task orchestration for competitor analysis.
- `rivalens/agents`: specialist agents for collection, analysis, writing, and quality review.
- `rivalens/schema`: structured competitor knowledge and evidence schema.
- `rivalens/research`: evidence collection adapters, retrievers, and the underlying research engine.

The generic research implementation lives inside `rivalens/research` as the web
research engine beneath Rivalens agents.

## Architecture

```mermaid
flowchart TB
    User["User / product team"] --> Workflow["rivalens.workflows\nLangGraph DAG"]

    Workflow --> Planner["PlanningAgent\nscope, active schema"]
    Workflow --> Collector["CollectionAgent\npublic evidence collection"]
    Workflow --> Knowledge["KnowledgeStructuringAgent\nEvidenceItem -> CompetitorKnowledge"]
    Workflow --> Analyst["AnalysisAgent\nCompetitorKnowledge -> AnalysisClaim"]
    Workflow --> Reviewer["QualityAgent\ntraceability and coverage review"]
    Workflow --> Reviser["RevisionAgent\nrespond to review findings"]
    Workflow --> Writer["ReportWriterAgent\nstructured report"]
    Workflow --> Publisher["PublisherAgent\nartifacts"]

    Planner --> MsgSelection["AgentMessage(type=schema_selection)"]
    Collector --> MsgEvidence["AgentMessage(type=evidence)"]
    Knowledge --> MsgSchema["AgentMessage(type=schema)"]
    Analyst --> MsgAnalysis["AgentMessage(type=analysis)"]
    Reviewer --> MsgReview["AgentMessage(type=review)"]
    MsgSelection --> MsgGuard
    MsgEvidence --> MsgGuard
    MsgSchema --> MsgGuard
    MsgAnalysis --> MsgGuard
    MsgReview --> MsgGuard

    Collector --> EvidenceCollector["ResearchEngineEvidenceCollector\nEvidenceItem adapter"]
    EvidenceCollector --> Modes["ResearchMode\nstandard/deep evidence"]
    Modes --> Engine["ResearchEngine\nsearch, scrape, context"]
    Engine --> Retrievers["Retrievers\nTavily / Exa / Serper / MCP / local / etc."]

    Planner --> State["CompetitorAnalysisState"]
    Collector --> State
    Knowledge --> State
    Analyst --> State
    Reviewer --> State
    Reviser --> State
    Writer --> State
    Publisher --> State

    State --> Evidence["EvidenceItem"]
    State --> ActiveSchema["ActiveKnowledgeSchema"]
    State --> KnowledgeState["CompetitorKnowledge"]
    State --> Claims["AnalysisClaim"]
    State --> QA["QualityFinding"]
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
    D --> E["reviewer\nQualityAgent"]
    E -->|quality_findings present| F["reviser\nRevisionAgent"]
    E -->|accepted| G["report_writer\nReportWriterAgent"]
    F --> G
    G --> H["publisher\nPublisherAgent"]
```

`scope_planner` owns the planning phase end to end: it normalizes competitor
inputs, selects and freezes an `ActiveKnowledgeSchema` from the schema registry,
then emits one `schema_selection` handoff to
`source_collection`. `source_collection` expands that schema into competitor-by-
dimension collection tasks and runs them concurrently through
`ResearchEngineEvidenceCollector`, which wraps
`rivalens.research.ResearchEngine` as a narrow evidence adapter. It normalizes
research sources into `EvidenceItem` records with collection task and schema
dimension metadata. The final report is produced only after evidence has been
structured into `CompetitorKnowledge`, analyzed, and reviewed over traceable
evidence.

## Structured Agent Messages

Agents exchange validated JSON messages through
`CompetitorAnalysisState.messages`. Each `AgentMessage` contains `sender`,
`receiver`, `type`, `payload`, `artifact_ids`, `evidence_ids`, and `created_at`.
The payload is validated before it is appended to state, using a dedicated
Pydantic schema for each message type:

```text
schema_selection -> SchemaSelectionMessagePayload
evidence -> EvidenceMessagePayload
schema   -> SchemaMessagePayload
analysis -> AnalysisMessagePayload
review   -> ReviewMessagePayload
revision -> RevisionMessagePayload
report   -> ReportMessagePayload
publish  -> PublishMessagePayload
```

Downstream agents consume the latest validated message addressed to them with
`latest_message_for(...)`. This makes each DAG edge behave more like a
function-calling contract: the shared state remains observable, but the handoff
between agents has explicit typed inputs instead of arbitrary free-form text.

## Evidence Collection Boundary

Search is intentionally owned by `CollectionAgent`. Other agents express data
needs through structured state, messages, and quality findings; they do not call
the research engine directly.

`CollectionAgent` calls `ResearchEngineEvidenceCollector`, which keeps the
ResearchEngine wiring out of agent business logic:

```text
CollectionAgent
  -> ResearchBranch frontier
  -> BranchReviewAgent expand/stop decisions
  -> EvidenceCollectionTask
  -> ResearchEngineEvidenceCollector (standard evidence)
  -> ResearchEngine
  -> EvidenceItem[]
```

The collection path uses standard evidence collection for each branch. Deep
research recursion is not used as a black box inside `ResearchEngine`; instead,
Rivalens keeps branch lineage, review decisions, depth, and budget in
`CompetitorAnalysisState.research_branches` and
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
`QualityAgent` no longer run their own research/report modes by default.
`BranchReviewAgent` handles collection-time branch expansion by reviewing child
query candidates against the current competitor, schema dimension, evidence
gaps, drift risk, and expansion budget.
Quality review should still audit final claims and evidence; when it finds a
coverage or citation gap, the next design step is to route a structured
collection request back to `CollectionAgent`.
