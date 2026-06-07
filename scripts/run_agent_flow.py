#!/usr/bin/env python3
"""Run the Rivalens Agent DAG locally without backend or frontend services."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "agent_runs"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Rivalens competitor-analysis Agent workflow directly. "
            "This does not start FastAPI, Next.js, Docker, Postgres, or Redis."
        )
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Research input, for example: 'Compare Feishu and DingTalk pricing'.",
    )
    parser.add_argument(
        "--competitor",
        action="append",
        default=[],
        help="Competitor name. Repeat for multiple competitors.",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        help="Optional local file path to include as context. Repeat as needed.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for the markdown report and state JSON. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--max-root-branches",
        type=int,
        default=6,
        help="Cap initial collection branches for a faster local test. Default: 6.",
    )
    parser.add_argument(
        "--full-budget",
        action="store_true",
        help="Use the workflow/env collection budgets instead of the small local-test budget.",
    )
    parser.add_argument(
        "--langsmith",
        action="store_true",
        help="Keep LangSmith tracing enabled if configured in .env.",
    )
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="Print the final markdown report to stdout after saving it.",
    )
    return parser


def _query_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    query = " ".join(args.query).strip()
    if not query and not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    if not query:
        parser.error("Please provide a query, or pipe one through stdin.")
    return query


def _configure_env(args: argparse.Namespace) -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        if (REPO_ROOT / ".env").exists():
            print(
                "Warning: python-dotenv is not installed, so .env was not loaded. "
                "Use .venv/bin/python or install project requirements.",
                file=sys.stderr,
            )
    else:
        load_dotenv(REPO_ROOT / ".env", override=True)

    # Keep this command focused on Agent execution, not app persistence/services.
    os.environ["RIVALENS_TRACE_PERSISTENCE_ENABLED"] = "false"
    os.environ["RIVALENS_SESSION_PERSISTENCE_ENABLED"] = "false"

    if not args.langsmith:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    if args.full_budget:
        return

    # Still runs the whole DAG, but avoids an expensive branch explosion during smoke tests.
    os.environ["RIVALENS_MAX_BRANCH_DEPTH"] = "0"
    os.environ["RIVALENS_MAX_EXPANSION_BRANCHES"] = "0"
    os.environ["RIVALENS_MAX_ROOT_BRANCHES"] = str(args.max_root_branches)
    os.environ["RIVALENS_MAX_CONCURRENT_COLLECTIONS"] = "2"
    os.environ["RIVALENS_MAX_SUBQUERY_CONCURRENCY"] = "1"
    os.environ["MAX_SEARCH_RESULTS_PER_QUERY"] = "3"
    os.environ["MAX_ITERATIONS"] = "1"


def _runtime_warnings() -> list[str]:
    warnings: list[str] = []
    retrievers = {
        retriever.strip()
        for retriever in os.getenv("RETRIEVER", "tavily").split(",")
        if retriever.strip()
    }
    if "tavily" in retrievers and not os.getenv("TAVILY_API_KEY"):
        warnings.append("RETRIEVER includes tavily but TAVILY_API_KEY is not set.")

    llm_settings = [
        os.getenv("FAST_LLM", ""),
        os.getenv("SMART_LLM", ""),
        os.getenv("STRATEGIC_LLM", ""),
    ]
    if any(setting.startswith("openai:") for setting in llm_settings) and not os.getenv(
        "OPENAI_API_KEY"
    ):
        warnings.append("One or more LLM settings use openai:* but OPENAI_API_KEY is not set.")
    return warnings


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


async def _run(args: argparse.Namespace, query: str) -> int:
    from rivalens.report_export import markdown_to_html_document
    from rivalens.workflows import run_competitive_analysis_task

    run_id = str(uuid4())
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    warnings = _runtime_warnings()
    if warnings:
        print("Configuration warnings:")
        for warning in warnings:
            print(f"- {warning}")
        print()

    print(f"Starting Rivalens Agent workflow: {run_id}")
    print("Backend/App/Docker services are not started.")

    kwargs = {
        "run_id": run_id,
        "competitors": [{"name": name} for name in args.competitor],
        "files": args.files,
        "verbose": True,
    }
    if not args.full_budget:
        kwargs.update(
            {
                "max_branch_depth": 0,
                "max_expansion_branches": 0,
                "max_root_branch_hard_limit": args.max_root_branches,
            }
        )

    state = await run_competitive_analysis_task(query, **kwargs)
    safe_state = _json_safe(state)
    report = str(safe_state.get("report", ""))
    artifacts = safe_state.get("published_artifacts") or {}
    events = safe_state.get("agent_events") or []
    evidence = safe_state.get("evidence_items") or []
    claims = safe_state.get("analysis_claims") or []

    report_path = output_dir / f"{run_id}.md"
    html_path = output_dir / f"{run_id}.html"
    state_path = output_dir / f"{run_id}.state.json"
    report_path.write_text(report, encoding="utf-8")
    html_path.write_text(
        markdown_to_html_document(report, title="Rivalens Agent Report"),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(safe_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("Agent workflow finished.")
    print(f"- Report: {report_path}")
    print(f"- HTML report: {html_path}")
    print(f"- State JSON: {state_path}")
    print(f"- Agent events: {len(events)}")
    print(f"- Evidence items: {len(evidence)}")
    print(f"- Analysis claims: {len(claims)}")
    if artifacts:
        print("- Publisher artifacts:")
        for kind, path in artifacts.items():
            if path:
                print(f"  {kind}: {path}")

    if args.print_report:
        print("\n" + report)

    return 0


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    query = _query_from_args(args, parser)
    _configure_env(args)
    try:
        return asyncio.run(_run(args, query))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nAgent workflow failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
