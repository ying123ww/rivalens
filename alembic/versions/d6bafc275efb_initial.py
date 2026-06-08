"""initial

Revision ID: d6bafc275efb
Revises: 
Create Date: 2026-06-04 16:42:29.529606

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd6bafc275efb'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY,
            email VARCHAR(320) NOT NULL,
            display_name VARCHAR(80) NOT NULL,
            password_hash TEXT NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'user',
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            email_verified_at TIMESTAMPTZ NULL,
            last_login_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_users_email_lowercase CHECK (email = lower(email)),
            CONSTRAINT ck_users_role CHECK (role IN ('user', 'admin')),
            CONSTRAINT ck_users_status CHECK (status IN ('active', 'disabled'))
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users (email)")
    op.execute(
        """
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_analysis_runs_status
                CHECK (status IN ('running', 'completed', 'failed', 'cancelled'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_analysis_runs_user_created
        ON analysis_runs (user_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_analysis_runs_status
        ON analysis_runs (status)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            memory JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id
        ON chat_sessions (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_updated
        ON chat_sessions (user_id, updated_at DESC)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_updated")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_id")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
    op.execute("DROP INDEX IF EXISTS ix_analysis_runs_status")
    op.execute("DROP INDEX IF EXISTS ix_analysis_runs_user_created")
    op.execute("DROP TABLE IF EXISTS analysis_runs")
    op.execute("DROP INDEX IF EXISTS ux_users_email")
    op.execute("DROP TABLE IF EXISTS users")
