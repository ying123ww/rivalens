from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .celery_task_lock import ReportTaskLock
from .evidence_vector_store import EvidenceVectorStore
from .report_store import ReportStore
from .rivalens_runner import set_trace_store
from .trace_store import TraceStore
from .websocket_manager import run_agent
from rivalens.report_export import generate_report_files
from rivalens.research.utils.llm_rate_limiter import get_llm_rate_limiter
from rivalens.research.utils.enum import Tone


logger = logging.getLogger(__name__)

_report_store = ReportStore()
_evidence_vector_store = EvidenceVectorStore()
_report_task_lock = ReportTaskLock()
set_trace_store(TraceStore())


def _extract_rivalens_report_text(report_information: Any) -> str:
    if isinstance(report_information, str):
        return report_information
    if isinstance(report_information, dict):
        return str(report_information.get("report", ""))
    if isinstance(report_information, (tuple, list)):
        return str(report_information[0]) if report_information else ""
    return str(report_information)


def _tone_from_request(value: Any) -> Tone:
    if isinstance(value, Tone):
        return value
    try:
        return Tone[str(value)]
    except Exception:
        return Tone.Objective


def _report_has_evidence(report: dict[str, Any]) -> bool:
    if isinstance(report.get("evidence_index"), list) and report["evidence_index"]:
        return True
    state = report.get("state")
    return bool(isinstance(state, dict) and state.get("evidence_items"))


async def _index_report_evidence(research_id: str, report: dict[str, Any]) -> None:
    if not _report_has_evidence(report):
        return
    try:
        count = await asyncio.to_thread(
            _evidence_vector_store.index_report,
            research_id,
            report,
        )
        logger.info("Indexed %d EvidenceItem vectors for report %s", count, research_id)
    except Exception:
        logger.exception("Failed to index EvidenceItem vectors for report %s", research_id)


async def _upsert_report_generation_record(
    research_id: str,
    research_request: dict[str, Any],
    status: str,
    *,
    response: dict[str, Any] | None = None,
    error: str | None = None,
    celery_task_id: str | None = None,
) -> dict[str, Any]:
    existing = await _report_store.get_report(research_id) or {}
    response = response or {}
    now_ms = int(time.time() * 1000)
    report_text = str(response.get("report") or existing.get("answer") or "")

    ordered_data = existing.get("orderedData")
    if not isinstance(ordered_data, list):
        ordered_data = []
    if status == "completed" and not ordered_data:
        ordered_data = [
            {"type": "question", "content": research_request.get("task", "")},
            {"type": "basic", "content": report_text},
        ]

    record = {
        **existing,
        "id": research_id,
        "question": existing.get("question") or research_request.get("task", ""),
        "answer": report_text,
        "orderedData": ordered_data,
        "chatMessages": existing.get("chatMessages") or [],
        "timestamp": now_ms,
        "status": status,
        "report_type": research_request.get("report_type"),
        "report_source": research_request.get("report_source"),
        "tone": research_request.get("tone"),
    }
    if celery_task_id:
        record["celery_task_id"] = celery_task_id

    for key in (
        "run_id",
        "research_information",
        "docx_path",
        "pdf_path",
        "markdown_path",
        "html_path",
        "artifacts",
        "report_artifacts",
        "trace_summary",
        "assessments",
        "evidence_index",
        "analysis_claims",
        "claim_support_reviews",
        "competitor_knowledge",
        "state",
    ):
        if key in response:
            record[key] = response[key]

    if error is not None:
        record["error"] = error
    elif "error" in record:
        record.pop("error")

    await _report_store.upsert_report(research_id, record)
    return record


async def _write_report(
    research_request: dict[str, Any],
    research_id: str,
) -> dict[str, Any]:
    report_type = str(research_request.get("report_type", ""))
    report_information = await run_agent(
        task=str(research_request.get("task", "")),
        report_type=report_type,
        report_source=str(research_request.get("report_source", "")),
        source_urls=research_request.get("source_urls", []) or [],
        document_urls=research_request.get("document_urls", []) or [],
        tone=_tone_from_request(research_request.get("tone")),
        websocket=None,
        stream_output=None,
        headers=research_request.get("headers"),
        query_domains=research_request.get("query_domains", []) or [],
        config_path=str(research_request.get("config_path") or ""),
        return_researcher=True,
        mcp_enabled=bool(research_request.get("mcp_enabled", False)),
        mcp_strategy=str(research_request.get("mcp_strategy", "fast")),
        mcp_configs=research_request.get("mcp_configs", []) or [],
        max_search_results=research_request.get("max_search_results"),
        industry_direction_plan=research_request.get("industry_direction_plan"),
        run_id=research_id,
        user_id=research_request.get("user_id"),
    )

    if report_type != "rivalens":
        report, researcher = report_information
        artifacts = await generate_report_files(
            report,
            research_id,
            quote_paths=True,
            include_legacy_md_key=True,
        )
        return {
            "research_id": research_id,
            "research_information": {
                "source_urls": researcher.get_source_urls(),
                "research_costs": researcher.get_costs(),
                "visited_urls": list(researcher.visited_urls),
                "research_images": researcher.get_research_images(),
            },
            "report": report,
            "docx_path": artifacts["docx"],
            "pdf_path": artifacts["pdf"],
            "markdown_path": artifacts["markdown"],
            "html_path": artifacts["html"],
            "artifacts": artifacts,
        }

    report = _extract_rivalens_report_text(report_information)
    artifacts = await generate_report_files(
        report,
        research_id,
        quote_paths=True,
        include_legacy_md_key=True,
    )
    report_artifacts = (
        dict(report_information.get("report_artifacts") or {})
        if isinstance(report_information, dict)
        else {}
    )
    report_artifacts.update(artifacts)
    return {
        "research_id": research_id,
        "run_id": (
            report_information.get("run_id", research_id)
            if isinstance(report_information, dict)
            else research_id
        ),
        "report": report,
        "docx_path": artifacts["docx"],
        "pdf_path": artifacts["pdf"],
        "markdown_path": artifacts["markdown"],
        "html_path": artifacts["html"],
        "artifacts": artifacts,
        "report_artifacts": report_artifacts,
        "trace_summary": (
            report_information.get("trace_summary", {})
            if isinstance(report_information, dict)
            else {}
        ),
        "assessments": (
            report_information.get("assessments", {})
            if isinstance(report_information, dict)
            else {}
        ),
        "evidence_index": (
            report_information.get("evidence_index", [])
            if isinstance(report_information, dict)
            else []
        ),
        "analysis_claims": (
            report_information.get("analysis_claims", [])
            if isinstance(report_information, dict)
            else []
        ),
        "claim_support_reviews": (
            report_information.get("claim_support_reviews")
            or (report_information.get("assessments", {}) or {}).get(
                "claim_support_reviews",
                [],
            )
        )
        if isinstance(report_information, dict)
        else [],
        "competitor_knowledge": (
            report_information.get("competitor_knowledge", [])
            if isinstance(report_information, dict)
            else []
        ),
        "state": (
            report_information.get("state", {})
            if isinstance(report_information, dict)
            else {}
        ),
    }


async def _generate_report_task(
    research_request: dict[str, Any],
    research_id: str,
    celery_task_id: str,
) -> dict[str, Any]:
    existing = await _report_store.get_report(research_id) or {}
    if existing.get("status") == "completed":
        logger.info(
            "Skipping already completed report generation task %s for %s",
            celery_task_id,
            research_id,
        )
        return {
            "research_id": research_id,
            "status": "already_completed",
            "celery_task_id": celery_task_id,
        }

    await _upsert_report_generation_record(
        research_id,
        research_request,
        "running",
        celery_task_id=celery_task_id,
    )
    try:
        response = await _write_report(research_request, research_id)
        record = await _upsert_report_generation_record(
            research_id,
            research_request,
            "completed",
            response=response,
            celery_task_id=celery_task_id,
        )
        await _index_report_evidence(research_id, record)
        return response
    except Exception as exc:
        await _upsert_report_generation_record(
            research_id,
            research_request,
            "failed",
            error=str(exc),
            celery_task_id=celery_task_id,
        )
        raise


async def _run_generate_report_task(
    research_request: dict[str, Any],
    research_id: str,
    celery_task_id: str,
) -> dict[str, Any]:
    try:
        return await _generate_report_task(
            research_request,
            research_id,
            celery_task_id,
        )
    finally:
        try:
            await get_llm_rate_limiter().aclose()
        except Exception:
            logger.exception(
                "Failed to close async Redis rate limiter for task %s",
                celery_task_id,
            )


@celery_app.task(bind=True, name="backend.server.celery_tasks.generate_report_task")
def generate_report_task(
    self,
    research_request: dict[str, Any],
    research_id: str,
) -> dict[str, Any]:
    celery_task_id = str(self.request.id or uuid4())
    try:
        acquired, lock_owner_task_id = _report_task_lock.try_acquire(
            research_id,
            celery_task_id,
        )
    except Exception as exc:
        asyncio.run(
            _upsert_report_generation_record(
                research_id,
                research_request,
                "failed",
                error=str(exc),
                celery_task_id=celery_task_id,
            )
        )
        raise

    if not acquired:
        logger.info(
            "Skipping duplicate report generation task %s for %s; lock owner is %s",
            celery_task_id,
            research_id,
            lock_owner_task_id,
        )
        return {
            "research_id": research_id,
            "status": "duplicate_skipped",
            "celery_task_id": celery_task_id,
            "lock_owner_task_id": lock_owner_task_id or "",
        }

    try:
        return asyncio.run(
            _run_generate_report_task(
                research_request,
                research_id,
                celery_task_id,
            )
        )
    except SoftTimeLimitExceeded:
        asyncio.run(
            _upsert_report_generation_record(
                research_id,
                research_request,
                "failed",
                error="Celery task exceeded soft time limit",
                celery_task_id=celery_task_id,
            )
        )
        raise
    finally:
        try:
            _report_task_lock.release(research_id, celery_task_id)
        except Exception:
            logger.exception(
                "Failed to release report generation lock for %s owned by %s",
                research_id,
                celery_task_id,
            )
