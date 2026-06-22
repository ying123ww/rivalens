"""Local file context ingestion and simple retrieval."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


TEXT_LIMIT = 1200
MAX_CHUNKS_PER_FILE = 40
SUPPORTED_TABULAR = {".csv", ".xls", ".xlsx"}
SUPPORTED_JSON = {".json"}
SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def get_task_file_references(task: dict[str, Any]) -> list[Any]:
    references: list[Any] = []
    for key in ("files", "file_paths", "attachments"):
        value = task.get(key)
        if not value:
            continue
        if isinstance(value, list):
            references.extend(value)
        else:
            references.append(value)
    return references


def build_file_context(file_references: list[Any]) -> dict[str, Any]:
    sources = []
    chunks = []

    for reference in file_references:
        path = _reference_path(reference)
        if not path:
            continue
        source = _load_file(path)
        source["id"] = f"file_{len(sources) + 1}"
        sources.append(source)

        for chunk in source.get("chunks", [])[:MAX_CHUNKS_PER_FILE]:
            chunks.append(
                {
                    **chunk,
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "source_path": source["path"],
                    "source_type": source["type"],
                }
            )

    return {
        "sources": sources,
        "chunks": chunks,
        "summary": file_context_summary({"sources": sources, "chunks": chunks}),
        "search_hints": _build_search_hints(sources, chunks),
    }


def file_context_summary(file_context: dict[str, Any]) -> str:
    sources = file_context.get("sources", [])
    chunks = file_context.get("chunks", [])
    if not sources:
        return ""

    source_lines = []
    for source in sources:
        if source.get("error"):
            source_lines.append(
                (
                    f"{source.get('name', 'unknown file')} "
                    f"({source.get('type', 'unknown')}): {source['error']}"
                )
            )
            continue
        source_lines.append(
            (
                f"{source.get('name', 'unknown file')} "
                f"({source.get('type', 'unknown')}): {source.get('summary', '')}"
            )
        )

    preview = "\n".join(source_lines[:8])
    return f"{len(sources)} local file(s), {len(chunks)} retrievable chunk(s).\n{preview}"


def retrieve_file_chunks(
    file_context: dict[str, Any],
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    chunks = file_context.get("chunks", [])
    if not chunks or not query:
        return chunks[:limit]

    query_tokens = _tokens(query)
    scored = []
    for chunk in chunks:
        text = f"{chunk.get('title', '')} {chunk.get('text', '')}"
        score = len(query_tokens.intersection(_tokens(text)))
        if score:
            scored.append((score, chunk))

    if not scored:
        return chunks[:limit]
    return [
        chunk
        for _, chunk in sorted(
            scored,
            key=lambda item: item[0],
            reverse=True,
        )[:limit]
    ]


def format_rag_context(
    file_context: dict[str, Any],
    query: str,
    limit: int = 5,
) -> str:
    chunks = retrieve_file_chunks(file_context, query, limit=limit)
    if not chunks:
        return ""

    lines = ["Local file RAG context:"]
    for chunk in chunks:
        lines.append(
            "\n".join(
                [
                    f"- Source: {chunk.get('source_name', 'unknown file')}",
                    f"  Section: {chunk.get('title', 'chunk')}",
                    f"  Content: {chunk.get('text', '')[:TEXT_LIMIT]}",
                ]
            )
        )
    return "\n".join(lines)


def _reference_path(reference: Any) -> Path | None:
    if isinstance(reference, str):
        return Path(reference)
    if isinstance(reference, dict):
        value = (
            reference.get("path")
            or reference.get("file_path")
            or reference.get("url")
        )
        if value:
            return Path(str(value))
    return None


def _load_file(path: Path) -> dict[str, Any]:
    extension = path.suffix.lower()
    source = {
        "name": path.name,
        "path": str(path),
        "type": extension.lstrip(".") or "unknown",
        "summary": "",
        "chunks": [],
    }

    if not path.exists() or not path.is_file():
        return {**source, "error": "File does not exist or is not readable."}

    try:
        if extension == ".csv":
            return {**source, **_load_csv(path)}
        if extension in {".xls", ".xlsx"}:
            return {**source, **_load_excel(path)}
        if extension == ".json":
            return {**source, **_load_json(path)}
        if extension in SUPPORTED_IMAGES:
            return {**source, **_load_image(path)}
        return {**source, "error": f"Unsupported file type: {extension or 'unknown'}"}
    except Exception as exc:
        return {**source, "error": str(exc)}


def _load_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        sample = file.read(4096)
        file.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(file, dialect=dialect)
        headers = reader.fieldnames or []
        rows = [row for _, row in zip(range(25), reader)]

    return _tabular_context(path.name, headers, rows)


def _load_excel(path: Path) -> dict[str, Any]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Excel ingestion requires pandas.") from exc

    sheets = pd.read_excel(path, sheet_name=None, nrows=25)
    chunks = []
    summaries = []
    for sheet_name, frame in sheets.items():
        headers = [str(column) for column in frame.columns]
        rows = frame.fillna("").astype(str).to_dict(orient="records")
        tabular = _tabular_context(f"{path.name}:{sheet_name}", headers, rows)
        summaries.append(tabular["summary"])
        chunks.extend(tabular["chunks"])
    return {"summary": " | ".join(summaries)[:TEXT_LIMIT], "chunks": chunks}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    chunks = []
    flattened = list(_flatten_json(data))[:MAX_CHUNKS_PER_FILE]
    for key, value in flattened:
        chunks.append(
            {
                "title": key,
                "text": _compact_text(value),
            }
        )
    summary = (
        f"JSON with top-level type {type(data).__name__}; "
        f"keys: {', '.join(_json_keys(data)[:12])}"
    )
    return {"summary": summary, "chunks": chunks}


def _load_image(path: Path) -> dict[str, Any]:
    width = height = None
    ocr_text = ""
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            ocr_text = _try_ocr_image(image)
    except Exception:
        pass

    size_text = f"{width}x{height}" if width and height else "unknown size"
    metadata = (
        f"Screenshot/image file {path.name}, {size_text}. "
        "Use filename and surrounding user task as visual context."
    )
    chunks = [{"title": "screenshot metadata", "text": metadata}]
    if ocr_text:
        chunks.append({"title": "screenshot OCR text", "text": ocr_text})

    return {
        "summary": f"{metadata} OCR text extracted: {bool(ocr_text)}",
        "chunks": chunks,
    }


def _tabular_context(
    name: str,
    headers: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    chunks = []
    header_text = ", ".join(headers)
    chunks.append({"title": f"{name} columns", "text": f"Columns: {header_text}"})

    for index, row in enumerate(rows, start=1):
        cells = [f"{key}: {_compact_text(value)}" for key, value in row.items()]
        chunks.append({"title": f"{name} row {index}", "text": "; ".join(cells)})

    summary = (
        f"Tabular file with {len(headers)} column(s): {header_text}; "
        f"sampled {len(rows)} row(s)."
    )
    return {"summary": summary, "chunks": chunks[:MAX_CHUNKS_PER_FILE]}


def _flatten_json(data: Any, prefix: str = "$"):
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _flatten_json(value, f"{prefix}.{key}")
    elif isinstance(data, list):
        for index, value in enumerate(data[:20]):
            yield from _flatten_json(value, f"{prefix}[{index}]")
    else:
        yield prefix, data


def _json_keys(data: Any) -> list[str]:
    if isinstance(data, dict):
        return [str(key) for key in data.keys()]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return [str(key) for key in data[0].keys()]
    return []


def _build_search_hints(
    sources: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[str]:
    hints = []
    for source in sources:
        if source.get("error"):
            continue
        hints.append(source.get("summary", ""))
    for chunk in chunks[:12]:
        hints.append(f"{chunk.get('title', '')}: {chunk.get('text', '')[:240]}")
    return [hint for hint in hints if hint][:20]


def _compact_text(value: Any) -> str:
    text = " ".join(str(value).split())
    return text[:TEXT_LIMIT]


def _try_ocr_image(image: Any) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""

    try:
        return _compact_text(pytesseract.image_to_string(image))
    except Exception:
        return ""


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in "".join(
            character if character.isalnum() else " " for character in text
        ).split()
        if len(token) > 1
    }
