"""add reports table

Revision ID: 3d6c1c76773f
Revises: d6bafc275efb
Create Date: 2026-06-04 16:45:34.759231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '3d6c1c76773f'
down_revision: Union[str, Sequence[str], None] = 'd6bafc275efb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reports',
    sa.Column('report_id', sa.String(length=280), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('run_id', sa.String(length=160), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('report_type', sa.String(length=64), nullable=True),
    sa.Column('report_source', sa.String(length=64), nullable=True),
    sa.Column('tone', sa.String(length=32), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('docx_path', sa.Text(), nullable=True),
    sa.Column('pdf_path', sa.Text(), nullable=True),
    sa.Column('markdown_path', sa.Text(), nullable=True),
    sa.Column('html_path', sa.Text(), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['analysis_runs.run_id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('report_id')
    )


def downgrade() -> None:
    op.drop_table('reports')
