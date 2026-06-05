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

## PostgreSQL Data

PostgreSQL stores user authentication and durable business provenance.
LangSmith remains responsible for detailed execution observability such as
model/tool spans, prompts, outputs, latency, token usage, and cost. PostgreSQL
stores the domain relationships needed to replay and visualize why a report
contains a claim.

The backend creates the `users` table at startup through
`backend/server/user_store.py`. The equivalent PostgreSQL script is
`backend/server/sql_table_create/001_users.sql`.

The user table stores:

- `id`: stable UUID identity.
- `email`: normalized lowercase login identifier with a unique index.
- `display_name`: user-facing name.
- `password_hash`: salted scrypt digest; plaintext passwords are never stored.
- `role` and `status`: authorization role and account availability.
- `email_verified_at` and `last_login_at`: verification and login audit fields.
- `created_at` and `updated_at`: account audit timestamps.

It intentionally does not store LangSmith API keys, trace payloads, raw
passwords, or access tokens. Configure authentication with:

```env
DATABASE_URL=postgresql://rivalens:123456@localhost:5433/rivalens
AUTH_JWT_SECRET=replace-with-a-long-random-secret
AUTH_ACCESS_TOKEN_TTL_SECONDS=86400
RIVALENS_TRACE_PERSISTENCE_ENABLED=true
```

The backend exposes `POST /api/auth/register`, `POST /api/auth/login`, and
`GET /api/auth/me`. The Next.js proxy stores the returned access token in an
HTTP-only cookie.

`backend/server/trace_store.py` creates the traceability tables. The equivalent
PostgreSQL script is `backend/server/sql_table_create/002_traceability.sql`.
Each Rivalens run receives a `running` record before execution. Completed runs
are stored transactionally at the backend workflow boundary, and failed runs
retain an auditable `analysis_runs` status when the database is available.

The traceability chain is:

```text
analysis_runs
  -> workflow_step_executions / workflow_transitions / agent_messages
  -> analysis_dimensions -> research_branches -> research_tasks
  -> evidence_items -> knowledge_facts -> analysis_claims
  -> report_sections -> artifacts
```

Critical many-to-many provenance uses actual relation tables:

- `knowledge_fact_evidence`: facts to source evidence.
- `claim_evidence`: claims to source evidence.
- `claim_knowledge_facts`: claims to structured facts.
- `report_section_claims`: report sections to claims.

`analysis_runs.langsmith_trace_id` is also used as the explicit LangSmith root
run ID, while `langsmith_thread_id` groups the business run. PostgreSQL stores
compact Agent event summaries and structured business payloads rather than
duplicating complete LangSmith traces or raw scraped pages.

Authenticated clients can use `GET /api/trace/runs/{run_id}` to retrieve a
visualization-ready workflow graph and the complete business provenance bundle
for a run. The primary WebSocket flow reads the HttpOnly authentication cookie
during the handshake and passes the user ID into `analysis_runs`. Runs with a
`user_id` are visible only to their owner or an admin; system or legacy runs
without an owner remain visible to authenticated users.

## Architecture

```mermaid
flowchart TB
    User["User / product team"] --> Workflow["rivalens.workflows\nLangGraph DAG"]

    Workflow --> Planner["PlanningAgent\nscope, industry directions"]
    Workflow --> Collector["CollectionAgent\npublic evidence collection"]
    Workflow --> Knowledge["KnowledgeStructuringAgent\nEvidenceItem -> KnowledgeFact"]
    Workflow --> Analyst["AnalysisAgent\nKnowledgeFact -> AnalysisClaim"]
    Workflow --> ClaimSupport["ClaimSupportReviewer\nclaim citation support gate"]
    Workflow --> Writer["ReportWriterAgent\nstructured report"]
    Workflow --> Publisher["PublisherAgent\nartifacts"]

    Planner --> MsgSelection["AgentMessage(type=research_plan)"]
    Collector --> MsgEvidence["AgentMessage(type=evidence)"]
    Knowledge --> MsgSchema["AgentMessage(type=schema)"]
    Analyst --> MsgAnalysis["AgentMessage(type=analysis)"]
    ClaimSupport --> MsgClaimSupport["AgentMessage(type=claim_support)"]
    MsgSelection --> MsgGuard
    MsgEvidence --> MsgGuard
    MsgSchema --> MsgGuard
    MsgAnalysis --> MsgGuard
    MsgClaimSupport --> MsgGuard

    Collector --> EvidenceCollector["ResearchEngineEvidenceCollector\nEvidenceItem adapter"]
    Collector --> EvidenceReview["EvidenceQualityReviewer\naccepted/rejected evidence"]
    Collector --> CoverageReview["CoverageReviewer\ncoverage gaps / follow-up tasks"]
    EvidenceCollector --> Modes["ResearchMode\nstandard evidence"]
    Modes --> Engine["ResearchEngine\nsearch, scrape, context"]
    Engine --> Retrievers["Retrievers\nTavily / Exa / Serper / MCP / local / etc."]

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

## Active Workflow

The active LangGraph entry point is `rivalens/workflows/agent.py`. Its current
multi-agent DAG is:

```mermaid
flowchart LR
    A["scope_planner\nPlanningAgent"] --> B["source_collection\nCollectionAgent"]
    B --> C["knowledge_structuring\nKnowledgeStructuringAgent"]
    C --> D["dimension_analysis\nAnalysisAgent"]
    D --> G["claim_support_review\nClaimSupportReviewer"]
    G --> E["report_writer\nReportWriterAgent"]
    E --> F["publisher\nPublisherAgent"]
```

`scope_planner` owns the planning phase end to end: it normalizes competitor
inputs, selects an industry, composes the confirmed analysis directions from
reusable industry facets, then emits one `research_plan` handoff to
`source_collection`. When deterministic
industry matching is confident, the planner uses the maintained facet templates:
L0 common business-analysis directions, L1 business-archetype directions, and
L2 regulated-domain directions are deduplicated into the default search plan.
The selected GICS sector, archetypes, regulated domains, and composition layers
are stored in `final_analysis_plan.direction_composition` for review and trace
replay. When the top rule score is below the
configured threshold, it calls the Anthropic-compatible industry LLM fallback
configured by `INDUSTRY_FALLBACK_LLM` / `ANTHROPIC_MODEL`, then stores the
structured industry, rationale, and suggested directions inside the same
`IndustryDirectionPlan` protocol. Rule-template
plans no longer use a second set of `planner_added_directions`, because L0 is
the shared general coverage layer. The confirmed direction plan is stored in
`CompetitorAnalysisState.industry_direction_plan`, so the search scope can be
reviewed before evidence collection. When the user has not specified a clear
competitor pair, the preview plan surfaces industry-template example
competitors as `suggested_competitors` without automatically treating them as
selected analysis targets. When known competitors are detected in the user query
and no explicit competitor list was provided, `PlanningAgent` promotes those
`detected_competitors` into the workflow competitor scope before collection.
`source_collection` also creates a `competitor_profile` task for each selected
competitor, so report information cards are backed by explicit public profile
evidence instead of writer-only inference.
`source_collection` expands the confirmed analysis dimensions into
competitor-by-dimension collection tasks and runs them concurrently through
`ResearchEngineEvidenceCollector`, which wraps
`rivalens.research.ResearchEngine` as a narrow evidence adapter. It normalizes
research sources into `EvidenceItem` records with collection task and analysis
dimension metadata, reviews each standard-search result against branch
`success_criteria`, and stores accepted branch evidence for structuring and
analysis. Collection branches carry one clean seed query while preserving
competitor, dimension, source hints, success criteria, and task context as
structured fields; `ResearchEngine` expands that seed into natural-language
sub-queries using the structured collection context. `CoverageReviewer` records which criteria are satisfied, partial, or
missing, consumes LLM-advised source-gap decisions, and narrows follow-up tasks
to the missing criteria or source coverage gaps instead of throwing away
partially useful evidence. `BranchCoverageStateBuilder` then aggregates each root branch
and its follow-up children into `branch_coverage_states`, recording current open
gap codes, resolved/blocked gap records, and the final coverage status on the
root branch. `KnowledgeStructuringAgent` first tries
the configured knowledge-fact LLM extractor, then validates, normalizes, and
deduplicates the returned candidates into `KnowledgeFact` atoms that cite
accepted `EvidenceItem` IDs. If the LLM is not configured, fails, or returns no
valid facts, the agent falls back to the deterministic rule extractor and still
populates `CompetitorKnowledge`. A local atomization policy keeps facts narrow:
pricing evidence is split into free-tier, plan-price, quote-only,
usage-based-billing, and annual-discount atoms when those signals are present.
`AnalysisAgent` groups facts by competitor, dimension, claim type, subject,
predicate, and normalized fact key before generating traceable `AnalysisClaim`
records.
`ClaimSupportReviewer` checks claim-level citation support before writing.
It does not launch a special collection path; future claim-support follow-up
should enter the same structured collection protocol used for normal coverage
gaps.

CSV, Excel, JSON, and screenshot inputs are ingested by `rivalens/file_context`
instead of being modeled as agents. `PlanningAgent` uses the resulting summaries
and search hints during industry and analysis planning. Collection,
knowledge structuring, and analysis reuse the same file chunks as local RAG
context while preserving the external evidence pipeline.

## Structured Agent Messages

Agents exchange validated JSON messages through
`CompetitorAnalysisState.messages`. Each `AgentMessage` contains `sender`,
`receiver`, `type`, `payload`, `artifact_ids`, `evidence_ids`, and `created_at`.
The payload is validated before it is appended to state. Active handoffs
currently use these Pydantic payloads:

```text
research_plan -> ResearchPlanMessagePayload
evidence -> EvidenceMessagePayload
schema   -> SchemaMessagePayload
analysis -> AnalysisMessagePayload
claim_support -> ClaimSupportMessagePayload
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
  -> ResearchBrief / ResearchTask queue with success criteria
  -> focused search_stage control
  -> ResearchEngineEvidenceCollector (explicit ResearchMode)
  -> ResearchEngine
  -> EvidenceItem[]
  -> EvidenceQualityReviewer (source-level accepted/rejected evidence and criterion matches)
  -> CoverageReviewer (criterion coverage gaps, LLM-advised source gaps, and follow-up task specs)
  -> BranchCoverageStateBuilder (root branch/group coverage ledger)
```

The collection path starts every confirmed competitor x dimension branch as
focused evidence collection. Claim-support review does not use a separate
verification collection channel. Deep research recursion is not used as a black
box inside `ResearchEngine`; instead, Rivalens keeps branch lineage, research
briefs, research tasks, evidence reviews, criterion coverage assessments,
depth, and budget in
`CompetitorAnalysisState.research_branches`,
`CompetitorAnalysisState.research_briefs`,
`CompetitorAnalysisState.research_tasks`,
`CompetitorAnalysisState.evidence_reviews`, and
`CompetitorAnalysisState.coverage_assessments`. After collection finishes,
`CompetitorAnalysisState.branch_coverage_states` records each root branch/group
status, accepted evidence IDs, source types found, success-criteria status, and
gap lifecycle.

`ResearchRoutingAction` is intentionally a shared routing vocabulary, not the
stage boundary. Consumers should distinguish stages with `search_stage` and the
assessment `stage_contract`: focused collection writes accepted source-backed
items to `evidence_items` and coverage observations to `coverage_assessments`.
Source coverage follow-ups are handled by LLM-advised `CoverageReviewer` tasks
instead of a separate pre-evidence discovery stage.

Collection field semantics are intentionally separated. `success_criteria`
defines required branch content coverage. `guiding_questions` must be explicit
on the branch when question-level coverage is required; `CoverageReviewer` does
not keep a dimension-id fallback policy for guiding questions or coverage
terms. `source_hints` are ranked preferred source types for initial query
building and source-gap review context, not hard requirements. An LLM
source-gap advisor decides whether the accepted evidence source mix needs
targeted follow-up; `CoverageReviewer` materializes that decision as explicit
`SourceCoverageGap` records and follow-up tasks. Only those gaps or their
follow-up tasks carry `target_source_types`; unresolved non-blocking source gaps
do not make a branch incomplete by themselves.
`expected_claim_types` is preserved as branch/task context for later analysis
typing, but collection does not use an implicit risk field to tighten evidence
thresholds.

Root branches are required analysis coverage: every competitor x confirmed
analysis dimension is collected before any depth expansion is considered. The expansion
budget applies only to child branches created from `CoverageReviewer`
follow-up task specs, with
`max_root_branch_hard_limit` acting as a per-competitor defensive cap for
unusually large analysis plans and `max_expansion_branches` controlling follow-up
breadth.

This keeps provider calls, source normalization, costs, and evidence metadata in
one place while preserving the main Rivalens chain:

```text
EvidenceItem -> EvidenceReviewResult -> AnalysisClaim
EvidenceItem -> CompetitorKnowledge -> Report
```

## Search Retrievers

Rivalens can run multiple search retrievers for the same collection task by
setting a comma-separated `RETRIEVER` value. For the MVP Chinese-plus-English
search setup, use UniFuncs Deep Search for Chinese ecosystem discovery and
Tavily for broader English web discovery:

```env
RETRIEVER=unifuncs_deepsearch,tavily
SCRAPER=tavily_extract

UNIFUNCS_API_KEY=sk-your-unifuncs-key
UNIFUNCS_DEEPSEARCH_BASE_URL=https://api.unifuncs.com/deepsearch/v1
UNIFUNCS_DEEPSEARCH_MODEL=s3
UNIFUNCS_DEEPSEARCH_LANGUAGE=zh
UNIFUNCS_DEEPSEARCH_REFERENCE_STYLE=link
UNIFUNCS_DEEPSEARCH_MAX_DEPTH=8

TAVILY_API_KEY=tvly-your-tavily-key
```

The UniFuncs retriever is used for source discovery, not final report writing.
It returns source URLs and short snippets, then the existing scraper fetches full
page content before evidence review and downstream analysis. When
`SCRAPER=tavily_extract` is set, URLs discovered by either UniFuncs or Tavily are
fetched through Tavily Extract.

`CollectionAgent` localizes deterministic branch `search_queries` before they
reach the retrievers. If the original task or competitor name is Chinese, for
example 飞书 or 钉钉, the planned sub-queries use Chinese source terms such as
官网、定价、文档、评价、新闻 to bias discovery toward Chinese-language sources.

## Knowledge Fact LLM Extraction

`KnowledgeStructuringAgent` can use an LLM to extract structured
`KnowledgeFact` atoms from accepted evidence before analysis:

```env
RIVALENS_KNOWLEDGE_STRUCTURING_LLM=openai:gpt-4.1-mini
RIVALENS_KNOWLEDGE_FACT_LLM_MAX_EVIDENCE=24
RIVALENS_KNOWLEDGE_FACT_LLM_EXCERPT_CHARS=700
```

The LLM setting uses the same `<provider>:<model>` format as other Rivalens LLM
configuration. If `RIVALENS_KNOWLEDGE_STRUCTURING_LLM` is unset, the agent also
checks `KNOWLEDGE_STRUCTURING_LLM`, then `STRATEGIC_LLM`, then `SMART_LLM`.
Every LLM fact candidate must cite accepted input evidence IDs; the agent
rejects candidates without valid citations, fills dimension and schema metadata
from the cited evidence, merges duplicates by `normalized_key`, and falls back
to deterministic fact extraction when the LLM path is unavailable or invalid.
If an LLM pricing fact is too broad, the local atomizer splits it using the
cited evidence before analysis. Agent events record the source, prompt ID,
provider, model, input count, fact count, atomization counts, fallback reason,
and estimated cost.

## LangSmith Tracing

Rivalens uses LangGraph and LangChain components, so LangSmith tracing can be
enabled with the official `LANGSMITH_*` environment variables. Traces are useful
when debugging the `CollectionAgent`, because the top-level LangGraph run is
tagged with `rivalens`, `competitive-analysis`, and metadata for retriever,
branch budget, competitor count, and collection ownership.

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2-your-langsmith-key
LANGSMITH_PROJECT=rivalens-local
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=
LANGCHAIN_CALLBACKS_BACKGROUND=false
```

Set `LANGSMITH_WORKSPACE_ID` only when the key can access more than one
workspace, or when LangSmith asks you to choose a workspace. For EU, APAC,
AWS-hosted, self-hosted, or hybrid LangSmith deployments, replace
`LANGSMITH_ENDPOINT` with that deployment's API URL.

The local smoke check submits one tiny trace to the configured project:

```bash
.venv/bin/python scripts/langsmith_smoke.py
```

The production Docker service passes the same variables through
`docker-compose.yml`. The legacy `LANGCHAIN_*` aliases are still forwarded for
older LangChain code paths, but new configuration should use `LANGSMITH_*`.
When inspecting one `rivalens_competitive_analysis` run, expand
`scope_planner` for the `rivalens_scope_planner` span, which summarizes the
normalized competitor scope, selected industry, and final
analysis directions. Then expand `source_collection` and look for child spans
named `rivalens_collect_evidence`, `rivalens_process_subquery`,
`rivalens_retriever_search`, `rivalens_scrape_url`,
`rivalens_evidence_quality_review`, and `rivalens_coverage_review`. Rivalens collection uses
the deterministic branch `search_queries` generated by `CollectionAgent`; when
those are present, it skips the generic LLM sub-query rewrite step. Collection
spans carry `rivalens_branch_id`, `rivalens_research_task_id`,
`rivalens_dimension_id`, `rivalens_search_stage`, `rivalens_search_queries`, and
`rivalens_actual_query` metadata so a branch can be followed from collection
task, to each retriever query, to scraped URLs, evidence acceptance/rejection,
success-criteria coverage, and follow-up collection decisions.

## Rivalens Collection Limits

For `report_type=rivalens`, the competitor-analysis workflow creates collection
branches before calling the underlying search retrievers. Use these environment
variables to reduce or expand that branch budget:

```env
RIVALENS_MAX_ROOT_BRANCHES=20
RIVALENS_MAX_BRANCH_DEPTH=0
RIVALENS_MAX_EXPANSION_BRANCHES=0
RIVALENS_MAX_CONCURRENT_COLLECTIONS=3
RIVALENS_MAX_SUBQUERY_CONCURRENCY=2
```

- `RIVALENS_MAX_ROOT_BRANCHES` caps the initial analysis-dimension collection
  branches per competitor. Budget for `selected directions + 1
  competitor_profile task` for each competitor.
- `RIVALENS_MAX_BRANCH_DEPTH=0` disables follow-up collection branches.
- `RIVALENS_MAX_EXPANSION_BRANCHES` caps follow-up branches created from
  coverage gaps.
- `RIVALENS_MAX_CONCURRENT_COLLECTIONS` caps how many collection branches run at
  once. Lower this when embedding or LLM providers return quota/rate errors.
- `RIVALENS_MAX_SUBQUERY_CONCURRENCY` caps per-branch sub-query processing,
  including scraped-content compression and embedding calls.

These limits are separate from `MAX_SEARCH_RESULTS_PER_QUERY` and
`MAX_ITERATIONS`, which control how many search results and sub-queries each
individual collection branch uses.

`PlanningAgent`, `KnowledgeStructuringAgent`, `AnalysisAgent`, and
`ReportWriterAgent` do not run their own research/report modes by default.
`ReportWriterAgent` does not collect new evidence, but it adapts Rivalens claims,
`CompetitorKnowledge`, and accepted `EvidenceItem` records into the shared
`ReportGenerator` writing path, using a fixed report contract: analysis purpose,
competitor selection, an evidence-driven competitor-analysis chapter whose
dimensions are dynamically derived from supported claims and accepted evidence,
summary, and an automatically appended information-index appendix that maps
paper-style citation refs such as `[1]` back to evidence IDs and source URLs. The
previous end-of-pipeline `QualityAgent` and `RevisionAgent` have been removed
because they created a late, claim-deletion-oriented pseudo loop.
`EvidenceQualityReviewer` now runs immediately after each standard search and
produces `EvidenceReviewResult` records with accepted/rejected evidence IDs,
success-criterion matches, findings, score, and required action.
`CoverageReviewer` consumes that result and remains responsible for branch-level
coverage control: source-type gaps, satisfied/partial/missing criteria, missing
guiding questions, next action, and gap-driven follow-up task specs.
`CollectionAgent` owns depth and expansion budget enforcement directly, while
`BranchCoverageStateBuilder` records whether the root branch/group became ready
for analysis or remained blocked.
`AnalysisAgent` runs after knowledge structuring and records
`knowledge_fact_ids`, `evidence_ids`, claim type, `claim_risk_level`, and report
routing on each generated `AnalysisClaim`. `ClaimSupportReviewer` marks claims
as supported, weak, contradicted, or unverifiable and emits a recommended action:
accept, revise, suppress, or evidence gap. Higher-risk claims are reviewed more
conservatively at the claim gate, not during collection. Only
supported/accepted claims enter the writer context; claim support review does
not currently trigger a collection-specific verification pass.
