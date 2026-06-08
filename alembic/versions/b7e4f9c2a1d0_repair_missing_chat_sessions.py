"""repair missing chat_sessions table

Revision ID: b7e4f9c2a1d0
Revises: 9f2c7a1e5b4d
Create Date: 2026-06-06 21:40:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b7e4f9c2a1d0"
down_revision: Union[str, Sequence[str], None] = "9f2c7a1e5b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_updated")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_id")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
