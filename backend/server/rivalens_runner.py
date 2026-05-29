import os
import sys
import logging
from typing import Any, Awaitable, Callable

RunRivalensTask = Callable[..., Awaitable[Any]]
logger = logging.getLogger(__name__)


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
    state = await run_task(*args, **kwargs)
    if isinstance(state, dict):
        try:
            from server.persistence import persist_competitive_analysis_state

            result = persist_competitive_analysis_state(state)
            logger.info(
                "Persisted Rivalens run %s: competitors=%s directions=%s branches=%s tasks=%s evidence=%s claims=%s claim_reviews=%s",
                result.run_id,
                result.competitor_count,
                result.direction_count,
                result.research_branch_count,
                result.research_task_count,
                result.evidence_count,
                result.claim_count,
                result.claim_support_review_count,
            )
        except Exception as exc:
            logger.warning("Failed to persist Rivalens run: %s", exc)
    return state
