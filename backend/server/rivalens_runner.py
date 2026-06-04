import os
import sys
import logging
from typing import Any, Awaitable, Callable
from uuid import uuid4

from .trace_store import TraceStore, langsmith_trace_id_for_run

RunRivalensTask = Callable[..., Awaitable[Any]]
logger = logging.getLogger(__name__)
_trace_store = TraceStore()


def set_trace_store(store: TraceStore) -> None:
    """Inject a shared TraceStore instance (e.g. from app.py)."""
    global _trace_store
    _trace_store = store


def _ensure_repo_root_on_path() -> None:
    """Ensure top-level repo root is importable for Rivalens modules."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _resolve_run_rivalens_task() -> RunRivalensTask:
    _ensure_repo_root_on_path()

    from rivalens.workflows import run_competitive_analysis_task
    return run_competitive_analysis_task


async def run_rivalens_task(*args, **kwargs) -> Any:
    run_task = _resolve_run_rivalens_task()
    run_id = str(kwargs.get("run_id") or uuid4())
    query = str(kwargs.get("query") or (args[0] if args else ""))
    user_id = kwargs.get("user_id")
    langsmith_trace_id = str(
        kwargs.get("langsmith_trace_id") or langsmith_trace_id_for_run(run_id)
    )
    langsmith_thread_id = str(kwargs.get("langsmith_thread_id") or run_id)
    kwargs.update(
        {
            "run_id": run_id,
            "langsmith_trace_id": langsmith_trace_id,
            "langsmith_thread_id": langsmith_thread_id,
        }
    )

    if _trace_store.enabled:
        try:
            _trace_store.start_run(
                run_id=run_id,
                query=query,
                user_id=user_id,
                langsmith_trace_id=langsmith_trace_id,
                langsmith_thread_id=langsmith_thread_id,
            )
        except Exception:
            logger.exception("Failed to persist running Rivalens trace %s", run_id)

    try:
        state = await run_task(*args, **kwargs)
    except Exception as exc:
        if _trace_store.enabled:
            try:
                _trace_store.mark_failed_run(
                    run_id=run_id,
                    query=query,
                    error=str(exc),
                    user_id=user_id,
                    langsmith_trace_id=langsmith_trace_id,
                    langsmith_thread_id=langsmith_thread_id,
                )
            except Exception:
                logger.exception("Failed to persist failed Rivalens run %s", run_id)
        raise

    if isinstance(state, dict) and _trace_store.enabled:
        try:
            result = _trace_store.persist_state(
                state,
                run_id=run_id,
                user_id=user_id,
            )
            logger.info(
                "Persisted Rivalens trace %s: steps=%s transitions=%s evidence=%s claims=%s links=%s artifacts=%s",
                result.run_id,
                result.step_count,
                result.transition_count,
                result.evidence_count,
                result.claim_count,
                result.claim_evidence_count,
                result.artifact_count,
            )
        except Exception:
            logger.exception("Failed to persist Rivalens trace %s", run_id)
    return state
