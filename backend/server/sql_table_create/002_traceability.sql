CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id VARCHAR(160) PRIMARY KEY,
    user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    report TEXT NOT NULL DEFAULT '',
    langsmith_trace_id VARCHAR(64) NULL,
    langsmith_thread_id VARCHAR(160) NULL,
    langsmith_project VARCHAR(160) NULL,
    langsmith_trace_url TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NULL,
    total_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    error TEXT NULL,
    task_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_analysis_runs_status
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS workflow_step_executions (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    agent VARCHAR(120) NOT NULL,
    action VARCHAR(240) NOT NULL,
    status VARCHAR(32) NOT NULL,
    input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    langsmith_run_id VARCHAR(64) NULL,
    PRIMARY KEY (run_id, sequence)
);

CREATE TABLE IF NOT EXISTS workflow_transitions (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    from_agent VARCHAR(120) NOT NULL,
    to_agent VARCHAR(120) NOT NULL,
    edge_type VARCHAR(80) NOT NULL,
    source_message_id VARCHAR(160) NULL,
    decision_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, sequence)
);

CREATE TABLE IF NOT EXISTS agent_messages (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(160) NOT NULL,
    sequence INTEGER NOT NULL,
    sender VARCHAR(120) NOT NULL,
    receiver VARCHAR(120) NOT NULL,
    message_type VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NULL,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS analysis_dimensions (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    name TEXT NOT NULL,
    objective TEXT NOT NULL DEFAULT '',
    priority VARCHAR(40) NOT NULL DEFAULT 'P1',
    required BOOLEAN NOT NULL DEFAULT TRUE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS research_branches (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    parent_id VARCHAR(180) NULL,
    parent_task_id VARCHAR(180) NULL,
    analysis_dimension_id VARCHAR(180) NULL,
    competitor TEXT NOT NULL DEFAULT '',
    depth INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    decision_action VARCHAR(80) NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS research_tasks (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    branch_id VARCHAR(180) NULL,
    parent_task_id VARCHAR(180) NULL,
    analysis_dimension_id VARCHAR(180) NULL,
    competitor TEXT NOT NULL DEFAULT '',
    search_stage VARCHAR(40) NOT NULL DEFAULT 'focused',
    objective TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS evidence_items (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    branch_id VARCHAR(180) NULL,
    research_task_id VARCHAR(180) NULL,
    collection_task_id VARCHAR(180) NULL,
    analysis_dimension_id VARCHAR(180) NULL,
    report_section_id VARCHAR(180) NULL,
    competitor TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    source_type VARCHAR(80) NOT NULL DEFAULT 'other',
    published_at VARCHAR(80) NULL,
    retrieved_at TIMESTAMPTZ NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    is_primary_source BOOLEAN NOT NULL DEFAULT FALSE,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    content_sha256 VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS evidence_reviews (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    branch_id VARCHAR(180) NULL,
    accepted BOOLEAN NOT NULL DEFAULT FALSE,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    required_action VARCHAR(80) NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS coverage_assessments (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    branch_id VARCHAR(180) NULL,
    next_action VARCHAR(80) NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS competitor_knowledge (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    competitor TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS knowledge_facts (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    competitor TEXT NOT NULL DEFAULT '',
    analysis_dimension_id VARCHAR(180) NULL,
    schema_field_id VARCHAR(180) NULL,
    report_section_id VARCHAR(180) NULL,
    statement TEXT NOT NULL,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS analysis_claims (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    analysis_dimension_id VARCHAR(180) NULL,
    report_section_id VARCHAR(180) NULL,
    branch_id VARCHAR(180) NULL,
    evidence_review_id VARCHAR(180) NULL,
    claim_source VARCHAR(120) NOT NULL DEFAULT '',
    claim TEXT NOT NULL,
    reasoning TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS claim_support_reviews (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    claim_id VARCHAR(180) NOT NULL,
    support_status VARCHAR(40) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    reviewer_notes TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS report_sections (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(180) NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id VARCHAR(160) NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    id VARCHAR(240) NOT NULL,
    artifact_type VARCHAR(80) NOT NULL,
    uri TEXT NOT NULL DEFAULT '',
    agent VARCHAR(120) NULL,
    branch_id VARCHAR(180) NULL,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS knowledge_fact_evidence (
    run_id VARCHAR(160) NOT NULL,
    knowledge_fact_id VARCHAR(180) NOT NULL,
    evidence_id VARCHAR(180) NOT NULL,
    PRIMARY KEY (run_id, knowledge_fact_id, evidence_id),
    FOREIGN KEY (run_id, knowledge_fact_id)
        REFERENCES knowledge_facts(run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, evidence_id)
        REFERENCES evidence_items(run_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    run_id VARCHAR(160) NOT NULL,
    claim_id VARCHAR(180) NOT NULL,
    evidence_id VARCHAR(180) NOT NULL,
    PRIMARY KEY (run_id, claim_id, evidence_id),
    FOREIGN KEY (run_id, claim_id)
        REFERENCES analysis_claims(run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, evidence_id)
        REFERENCES evidence_items(run_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claim_knowledge_facts (
    run_id VARCHAR(160) NOT NULL,
    claim_id VARCHAR(180) NOT NULL,
    knowledge_fact_id VARCHAR(180) NOT NULL,
    PRIMARY KEY (run_id, claim_id, knowledge_fact_id),
    FOREIGN KEY (run_id, claim_id)
        REFERENCES analysis_claims(run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, knowledge_fact_id)
        REFERENCES knowledge_facts(run_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_section_claims (
    run_id VARCHAR(160) NOT NULL,
    report_section_id VARCHAR(180) NOT NULL,
    claim_id VARCHAR(180) NOT NULL,
    PRIMARY KEY (run_id, report_section_id, claim_id),
    FOREIGN KEY (run_id, report_section_id)
        REFERENCES report_sections(run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, claim_id)
        REFERENCES analysis_claims(run_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_analysis_runs_user_created
    ON analysis_runs (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_status
    ON analysis_runs (status);
CREATE INDEX IF NOT EXISTS ix_workflow_steps_run_agent
    ON workflow_step_executions (run_id, agent);
CREATE INDEX IF NOT EXISTS ix_workflow_transitions_run_agents
    ON workflow_transitions (run_id, from_agent, to_agent);
CREATE INDEX IF NOT EXISTS ix_agent_messages_run_sequence
    ON agent_messages (run_id, sequence);
CREATE INDEX IF NOT EXISTS ix_research_branches_run_dimension
    ON research_branches (run_id, analysis_dimension_id);
CREATE INDEX IF NOT EXISTS ix_research_tasks_run_branch
    ON research_tasks (run_id, branch_id);
CREATE INDEX IF NOT EXISTS ix_evidence_items_run_dimension
    ON evidence_items (run_id, analysis_dimension_id);
CREATE INDEX IF NOT EXISTS ix_evidence_items_run_competitor
    ON evidence_items (run_id, competitor);
CREATE INDEX IF NOT EXISTS ix_knowledge_facts_run_dimension
    ON knowledge_facts (run_id, analysis_dimension_id);
CREATE INDEX IF NOT EXISTS ix_analysis_claims_run_dimension
    ON analysis_claims (run_id, analysis_dimension_id);
CREATE INDEX IF NOT EXISTS ix_analysis_claims_run_report_section
    ON analysis_claims (run_id, report_section_id);
CREATE INDEX IF NOT EXISTS ix_claim_evidence_evidence
    ON claim_evidence (run_id, evidence_id);
