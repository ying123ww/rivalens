import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Allow alembic to import from backend/server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from server.metadata import shared_metadata  # noqa: E402
import server.user_store      # noqa: E402 — registers users on shared_metadata
import server.trace_store     # noqa: E402 — registers trace tables
import server.session_store   # noqa: E402 — registers chat_sessions
import server.report_store    # noqa: E402 — registers reports
import server.evidence_vector_store  # noqa: E402 — registers evidence pgvector index

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = shared_metadata


def _get_url() -> str:
    url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    if url and url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _get_url()
    config.set_main_option("sqlalchemy.url", url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
