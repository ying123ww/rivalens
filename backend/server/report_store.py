import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List


class ReportStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()

    async def _ensure_parent_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def _read_all_unlocked(self) -> Dict[str, Dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data  # type: ignore[return-value]
        except Exception:
            return {}
        return {}

    async def _write_all_unlocked(self, data: Dict[str, Dict[str, Any]]) -> None:
        await self._ensure_parent_dir()
        task_id = id(asyncio.current_task())
        tmp_path = self._path.with_name(
            f"{self._path.name}.{os.getpid()}.{task_id}.tmp"
        )
        serialized = json.dumps(data, ensure_ascii=False)
        tmp_path.write_text(serialized, encoding="utf-8")
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                tmp_path.replace(self._path)
                return
            except OSError as exc:
                last_error = exc
                if attempt < 4:
                    await asyncio.sleep(0.05 * (attempt + 1))

        try:
            self._path.write_text(serialized, encoding="utf-8")
        except OSError:
            if last_error is not None:
                raise last_error
            raise
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def list_reports(self, report_ids: List[str] | None = None) -> List[Dict[str, Any]]:
        async with self._lock:
            data = await self._read_all_unlocked()
            if report_ids is None:
                return list(data.values())
            return [data[report_id] for report_id in report_ids if report_id in data]

    async def get_report(self, report_id: str) -> Dict[str, Any] | None:
        async with self._lock:
            data = await self._read_all_unlocked()
            return data.get(report_id)

    async def upsert_report(self, report_id: str, report: Dict[str, Any]) -> None:
        async with self._lock:
            data = await self._read_all_unlocked()
            data[report_id] = report
            await self._write_all_unlocked(data)

    async def delete_report(self, report_id: str) -> bool:
        async with self._lock:
            data = await self._read_all_unlocked()
            existed = report_id in data
            if existed:
                del data[report_id]
                await self._write_all_unlocked(data)
            return existed
