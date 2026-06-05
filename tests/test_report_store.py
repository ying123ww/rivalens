from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from backend.server.report_store import (
    LEGACY_REPORT_MIGRATION_ENABLED_ENV,
    LEGACY_REPORT_MIGRATION_MARKER_PATH_ENV,
    ReportStore,
    reports,
)
from backend.server.trace_store import analysis_runs
from backend.server.user_store import users


def _make_tmp_path() -> Path:
    path = Path(__file__).resolve().parents[1] / ".test-tmp" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _create_store() -> ReportStore:
    store = ReportStore("sqlite:///:memory:")
    users.create(store.engine, checkfirst=True)
    analysis_runs.create(store.engine, checkfirst=True)
    reports.create(store.engine, checkfirst=True)
    return store


def _write_legacy_reports(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "report-1": {
                    "id": "report-1",
                    "question": "钉钉和飞书",
                    "answer": "legacy answer",
                    "orderedData": [{"type": "basic", "content": "legacy answer"}],
                    "chatMessages": [],
                    "timestamp": 1780644736900,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_legacy_report_migration_is_disabled_by_default(monkeypatch):
    tmp_path = _make_tmp_path()
    legacy_path = tmp_path / "reports.json"
    _write_legacy_reports(legacy_path)
    monkeypatch.delenv(LEGACY_REPORT_MIGRATION_ENABLED_ENV, raising=False)

    store = _create_store()

    imported = asyncio.run(store.migrate_from_json(str(legacy_path)))

    assert imported == 0
    assert asyncio.run(store.list_reports()) == []


def test_legacy_report_migration_does_not_restore_deleted_reports(
    monkeypatch,
):
    tmp_path = _make_tmp_path()
    legacy_path = tmp_path / "reports.json"
    marker_path = tmp_path / "reports.json.migrated"
    _write_legacy_reports(legacy_path)
    monkeypatch.setenv(LEGACY_REPORT_MIGRATION_ENABLED_ENV, "true")
    monkeypatch.setenv(
        LEGACY_REPORT_MIGRATION_MARKER_PATH_ENV,
        str(marker_path),
    )

    store = _create_store()

    assert asyncio.run(store.migrate_from_json(str(legacy_path))) == 1
    assert marker_path.exists()
    assert asyncio.run(store.get_report("report-1")) is not None

    assert asyncio.run(store.delete_report("report-1")) is True
    assert asyncio.run(store.get_report("report-1")) is None

    assert asyncio.run(store.migrate_from_json(str(legacy_path))) == 0
    assert asyncio.run(store.get_report("report-1")) is None
