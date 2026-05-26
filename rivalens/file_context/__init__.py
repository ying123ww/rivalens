"""Reusable file-context helpers for agents.

These helpers are intentionally not agents. They ingest user-provided files
into lightweight summaries and retrievable chunks that workflow agents can use
as planning hints and local RAG context.
"""

from .context import (
    build_file_context,
    file_context_summary,
    format_rag_context,
    get_task_file_references,
    retrieve_file_chunks,
)

__all__ = [
    "build_file_context",
    "file_context_summary",
    "format_rag_context",
    "get_task_file_references",
    "retrieve_file_chunks",
]
