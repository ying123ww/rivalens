"""repair backend store schema

Revision ID: f4d2a8c9b7e1
Revises: b7e4f9c2a1d0
Create Date: 2026-06-07 00:00:00.000000
"""

from __future__ import annotations

import os
import sys

from alembic import op


revision = "f4d2a8c9b7e1"
down_revision = "b7e4f9c2a1d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    metadata = _load_store_metadata()
    metadata.create_all(bind=bind, checkfirst=True)
    for table in metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_evidence_embeddings_research_id "
            "ON evidence_embeddings (research_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_evidence_embeddings_metadata "
            "ON evidence_embeddings USING gin (metadata)"
        )


def downgrade() -> None:
    pass


def _load_store_metadata():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    backend_dir = os.path.join(root_dir, "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from server.metadata import shared_metadata
    import server.evidence_vector_store  # noqa: F401
    import server.report_store  # noqa: F401
    import server.session_store  # noqa: F401
    import server.trace_store  # noqa: F401
    import server.user_store  # noqa: F401

    return shared_metadata
