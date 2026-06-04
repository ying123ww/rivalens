"""SQL-backed report metadata store (replaces the legacy JSON-file store).

Table ``reports`` lives on ``shared_metadata`` so Alembic manages it
alongside every other table.  The public API is unchanged — callers still
see dict-shaped reports — but the backing store is now PostgreSQL.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from .metadata import shared_metadata
from .user_store import DEFAULT_DATABASE_URL

logger = logging.getLogger(__name__)

JSON_DATA = JSON().with_variant(JSONB, "postgresql")

REPORT_STORE_PATH_ENV = "REPORT_STORE_PATH"
LEGACY_REPORT_STORE_PATH = os.path.join("data", "reports.json")

reports = Table(
    "reports",
    shared_metadata,
    Column("report_id", String(280), primary_key=True),
    Column(
        "user_id",
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "run_id",
        String(160),
        ForeignKey("analysis_runs.run_id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("question", Text, nullable=False, default=""),
    Column("answer", Text, nullable=False, default=""),
    Column("status", String(32), nullable=False, default="running"),
    Column("report_type", String(64), nullable=True),
    Column("report_source", String(64), nullable=True),
    Column("tone", String(32), nullable=True),
    Column("timestamp", DateTime(timezone=True), nullable=True),
    Column("docx_path", Text, nullable=True),
    Column("pdf_path", Text, nullable=True),
    Column("markdown_path", Text, nullable=True),
    Column("html_path", Text, nullable=True),
    Column("data", JSON_DATA, nullable=False, default=dict),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class ReportStore:
    def __init__(
        self,
        database_url: str | None = None,
    ) -> None:
        self._database_url = database_url
        self._engine: Engine | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            database_url = self._database_url or os.getenv(
                "DATABASE_URL", DEFAULT_DATABASE_URL
            )
            self._engine = create_engine(
                _sqlalchemy_database_url(database_url),
                pool_pre_ping=True,
            )
        return self._engine

    # ── public API (unchanged signatures) ─────────────────────────

    async def list_reports(
        self, report_ids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(reports).order_by(reports.c.updated_at.desc())
        if report_ids:
            stmt = stmt.where(reports.c.report_id.in_(list(report_ids)))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_row_to_report(dict(row)) for row in rows]

    async def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(reports).where(reports.c.report_id == report_id)
            ).mappings().first()
        if row is None:
            return None
        return _row_to_report(dict(row))

    async def upsert_report(
        self, report_id: str, report: dict[str, Any]
    ) -> None:
        """Insert or update a report.

        *report* can be either the legacy flat dict (all fields at top-level)
        or a dict with ``id`` / ``report_id`` keys.
        """
        values = _report_to_row(report_id, report)
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(reports.c.report_id).where(
                    reports.c.report_id == report_id
                )
            ).first()
            if existing:
                conn.execute(
                    update(reports)
                    .where(reports.c.report_id == report_id)
                    .values(**values)
                )
            else:
                conn.execute(insert(reports).values(**values))

    async def delete_report(self, report_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(reports).where(reports.c.report_id == report_id)
            )
            return result.rowcount > 0

    # ── migration ─────────────────────────────────────────────────

    async def migrate_from_json(self, path: str | None = None) -> int:
        """Import reports from the legacy JSON file.  Returns count of imported rows."""
        path = path or os.getenv(REPORT_STORE_PATH_ENV, LEGACY_REPORT_STORE_PATH)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return 0
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read legacy report store %s: %s", path, exc)
            return 0

        if not isinstance(data, dict):
            return 0

        imported = 0
        for report_id, report in data.items():
            try:
                values = _report_to_row(report_id, report)
                with self.engine.begin() as conn:
                    existing = conn.execute(
                        select(reports.c.report_id).where(
                            reports.c.report_id == report_id
                        )
                    ).first()
                    if existing:
                        conn.execute(
                            update(reports)
                            .where(reports.c.report_id == report_id)
                            .values(**values)
                        )
                    else:
                        conn.execute(insert(reports).values(**values))
                imported += 1
            except Exception:
                logger.exception("Failed to migrate report %s", report_id)
        logger.info("Migrated %d reports from %s", imported, path)
        return imported


# ── row ↔ dict conversion ─────────────────────────────────────────

_FIXED_KEYS = frozenset({
    "docx_path", "pdf_path", "markdown_path", "html_path",
    "run_id", "error", "user_id",
})


def _report_to_row(report_id: str, report: dict[str, Any]) -> dict[str, Any]:
    """Split a flat report dict into fixed columns + ``data`` JSONB payload."""

    def _pop(key: str, default: Any = None) -> Any:
        v = report.get(key, default)
        if key in report:
            del report[key]
        return v

    data: dict[str, Any] = {}
    for key in (
        "orderedData", "chatMessages", "artifacts", "report_artifacts",
        "trace_summary", "assessments", "evidence_index",
        "analysis_claims", "competitor_knowledge", "state",
        "research_information", "research_costs", "visited_urls",
        "research_images",
    ):
        if key in report:
            data[key] = report.pop(key)

    timestamp_val = _pop("timestamp")
    if isinstance(timestamp_val, (int, float)):
        try:
            timestamp_val = datetime.fromtimestamp(
                timestamp_val / 1000.0, tz=timezone.utc
            )
        except (ValueError, OSError):
            timestamp_val = None

    return {
        "report_id": _pop("id") or report_id,
        "user_id": _pop("user_id"),
        "run_id": _pop("run_id"),
        "question": _pop("question", ""),
        "answer": _pop("answer", ""),
        "status": _pop("status", "completed"),
        "report_type": _pop("report_type"),
        "report_source": _pop("report_source"),
        "tone": _pop("tone"),
        "timestamp": timestamp_val,
        "docx_path": _pop("docx_path"),
        "pdf_path": _pop("pdf_path"),
        "markdown_path": _pop("markdown_path"),
        "html_path": _pop("html_path"),
        "data": data,
        "error": _pop("error"),
        "updated_at": _utcnow(),
    }


def _row_to_report(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a flat report dict from a database row."""

    def _ts(v: Any) -> int | None:
        if isinstance(v, datetime):
            return int(v.timestamp() * 1000)
        if isinstance(v, (int, float)):
            return int(v)
        return None

    report: dict[str, Any] = {
        "id": row.get("report_id", ""),
        "question": row.get("question", ""),
        "answer": row.get("answer", ""),
        "status": row.get("status", "completed"),
        "report_type": row.get("report_type"),
        "report_source": row.get("report_source"),
        "tone": row.get("tone"),
        "timestamp": _ts(row.get("timestamp")),
        "docx_path": row.get("docx_path"),
        "pdf_path": row.get("pdf_path"),
        "markdown_path": row.get("markdown_path"),
        "html_path": row.get("html_path"),
        "run_id": row.get("run_id"),
        "error": row.get("error"),
    }

    data = row.get("data")
    if isinstance(data, dict):
        report.update(data)

    report = {k: v for k, v in report.items() if v is not None}
    return report


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url
