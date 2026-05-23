import os
import sys
from typing import Any, Awaitable, Callable

RunRivalensTask = Callable[..., Awaitable[Any]]


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
    return await run_task(*args, **kwargs)
