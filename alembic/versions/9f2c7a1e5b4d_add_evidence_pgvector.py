"""add evidence pgvector index

Revision ID: 9f2c7a1e5b4d
Revises: 3d6c1c76773f
Create Date: 2026-06-06 00:00:00.000000
"""

from alembic import op


revision = "9f2c7a1e5b4d"
down_revision = "3d6c1c76773f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_embeddings (
            research_id VARCHAR(280) NOT NULL,
            evidence_id VARCHAR(180) NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            run_id VARCHAR(160),
            embedding_provider VARCHAR(80) NOT NULL DEFAULT '',
            embedding_model VARCHAR(160) NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            competitor VARCHAR(160) NOT NULL DEFAULT '',
            analysis_dimension_id VARCHAR(160) NOT NULL DEFAULT '',
            report_section_id VARCHAR(160) NOT NULL DEFAULT '',
            source_type VARCHAR(80) NOT NULL DEFAULT '',
            content_sha256 VARCHAR(64) NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding vector NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (research_id, evidence_id, chunk_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_embeddings_research_id "
        "ON evidence_embeddings (research_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_embeddings_run_id "
        "ON evidence_embeddings (run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_embeddings_metadata "
        "ON evidence_embeddings USING gin (metadata)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_embeddings_metadata")
    op.execute("DROP INDEX IF EXISTS ix_evidence_embeddings_run_id")
    op.execute("DROP INDEX IF EXISTS ix_evidence_embeddings_research_id")
    op.execute("DROP TABLE IF EXISTS evidence_embeddings")
