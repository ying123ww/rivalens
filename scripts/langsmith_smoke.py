#!/usr/bin/env python3
"""Submit a tiny LangSmith trace to verify local Rivalens tracing setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _load_project_env() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")


def _require_langsmith_config() -> tuple[str, str]:
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", "rivalens-local")
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    os.environ.setdefault("LANGCHAIN_CALLBACKS_BACKGROUND", "false")

    api_key = os.getenv("LANGSMITH_API_KEY")
    project = os.getenv("LANGSMITH_PROJECT", "rivalens-local")
    if not api_key:
        raise SystemExit(
            "LANGSMITH_API_KEY is not set. Add it to .env or export it before "
            "running this smoke check."
        )
    return api_key, project


def main() -> int:
    _load_project_env()
    _, project = _require_langsmith_config()

    from langchain_core.tracers.langchain import wait_for_all_tracers
    from langsmith import traceable, tracing_context

    @traceable(
        name="rivalens_langsmith_smoke",
        run_type="chain",
        tags=["rivalens", "langsmith-smoke"],
        metadata={"component": "observability", "project": project},
    )
    def smoke_trace() -> dict[str, str]:
        return {
            "status": "ok",
            "project": project,
        }

    try:
        with tracing_context(enabled=True, project_name=project):
            result = smoke_trace()
    finally:
        wait_for_all_tracers()

    print(f"LangSmith smoke trace submitted: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
