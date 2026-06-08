"""add reports table

Revision ID: 3d6c1c76773f
Revises: d6bafc275efb
Create Date: 2026-06-04 16:45:34.759231

"""
from typing import Sequence, Union

from alembic import op

revision: str = '3d6c1c76773f'
down_revision: Union[str, Sequence[str], None] = 'd6bafc275efb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            report_id VARCHAR(280) PRIMARY KEY,
            user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
            run_id VARCHAR(160) NULL REFERENCES analysis_runs(run_id) ON DELETE SET NULL,
            question TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            report_type VARCHAR(64) NULL,
            report_source VARCHAR(64) NULL,
            tone VARCHAR(32) NULL,
            timestamp TIMESTAMPTZ NULL,
            docx_path TEXT NULL,
            pdf_path TEXT NULL,
            markdown_path TEXT NULL,
            html_path TEXT NULL,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reports")
