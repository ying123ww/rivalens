"""Shared report export helpers for Rivalens-generated reports."""

from __future__ import annotations

import os
import re
import urllib.parse
import warnings
from html import escape
from pathlib import Path
from typing import Any

import mistune


ReportArtifacts = dict[str, str]


def _safe_filename(filename: str) -> str:
    stem = Path(filename).stem or "report"
    return re.sub(r"[^\w\s-]", "", stem).strip()[:60] or "report"


def _artifact_path(output_dir: str | Path, filename: str, suffix: str) -> Path:
    return Path(output_dir) / f"{_safe_filename(filename)}.{suffix}"


def _artifact_value(path: Path, quote_paths: bool) -> str:
    value = path.as_posix()
    return urllib.parse.quote(value) if quote_paths else value


async def _write_text(path: Path, text: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(text, str):
        text = str(text)
    text_utf8 = text.encode("utf-8", errors="replace").decode("utf-8")
    path.write_text(text_utf8, encoding="utf-8")


def markdown_to_html_document(markdown_text: str, title: str = "Rivalens Report") -> str:
    body = mistune.html(markdown_text)
    escaped_title = escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{
      max-width: 920px;
      margin: 40px auto;
      padding: 0 24px 48px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
      color: #172033;
      background: #ffffff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0 24px;
      font-size: 0.95rem;
    }}
    th, td {{
      border: 1px solid #d8dee9;
      padding: 8px 10px;
      vertical-align: top;
    }}
    th {{
      background: #f4f6f8;
      font-weight: 650;
    }}
    code {{
      background: #f4f6f8;
      padding: 0.1em 0.3em;
      border-radius: 4px;
    }}
    pre {{
      overflow-x: auto;
      background: #f4f6f8;
      padding: 16px;
      border-radius: 6px;
    }}
    a {{
      color: #0b63ce;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _preprocess_images_for_pdf(text: str) -> str:
    base_path = os.path.abspath(".")

    def replace_image_url(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        url = match.group(2)
        if url.startswith("/outputs/"):
            abs_path = os.path.join(base_path, url.lstrip("/"))
            return f"![{alt_text}]({abs_path})"
        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\((/outputs/[^)]+)\)", replace_image_url, text)


def _default_pdf_css_path() -> str | None:
    repo_root = Path(__file__).resolve().parent.parent
    css_path = repo_root / "backend" / "styles" / "pdf_styles.css"
    return str(css_path) if css_path.exists() else None


async def _write_markdown(path: Path, report: str) -> str:
    await _write_text(path, report)
    return path.as_posix()


async def _write_html(path: Path, report: str, title: str) -> str:
    await _write_text(path, markdown_to_html_document(report, title=title))
    return path.as_posix()


def _pdf_css(css_path: str | None = None) -> str:
    css = ""
    resolved_css_path = css_path or _default_pdf_css_path()
    if resolved_css_path:
        path = Path(resolved_css_path)
        if path.exists():
            css = path.read_text(encoding="utf-8")
    cjk_safe_overrides = """
@page {
  size: A4;
  margin: 18mm 16mm;
}
body {
  font-family: sans-serif;
  font-size: 11pt;
  line-height: 1.55;
  color: #172033;
}
h1, h2, h3, h4, h5, h6 {
  font-family: sans-serif;
  color: #111827;
  margin: 0.8em 0 0.45em;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0 18px;
  font-size: 9.5pt;
}
th, td {
  border: 0.75pt solid #d8dee9;
  padding: 5px 6px;
  vertical-align: top;
}
th {
  background: #f4f6f8;
  font-weight: 700;
}
code, pre {
  font-family: monospace;
}
img {
  max-width: 100%;
}
"""
    return f"{css}\n{cjk_safe_overrides}"


async def _write_pdf(path: Path, report: str, css_path: str | None = None) -> str:
    try:
        import fitz

        path.parent.mkdir(parents=True, exist_ok=True)
        html = mistune.html(_preprocess_images_for_pdf(report))
        story = fitz.Story(html, user_css=_pdf_css(css_path))
        writer = fitz.DocumentWriter(path.as_posix())
        mediabox = fitz.Rect(0, 0, 595, 842)
        content_box = fitz.Rect(45, 45, 550, 797)
        page_count = 0
        while True:
            device = writer.begin_page(mediabox)
            more, _filled = story.place(content_box)
            story.draw(device)
            writer.end_page()
            page_count += 1
            if not more:
                break
            if page_count >= 500:
                raise RuntimeError("PDF generation exceeded 500 pages")
        writer.close()
        return path.as_posix()
    except Exception:
        return ""


async def _write_docx(path: Path, report: str) -> str:
    try:
        from bs4 import MarkupResemblesLocatorWarning
        from docx import Document
        from htmldocx import HtmlToDocx

        path.parent.mkdir(parents=True, exist_ok=True)
        doc = Document()
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=MarkupResemblesLocatorWarning,
            )
            HtmlToDocx().add_html_to_document(mistune.html(report), doc)
        doc.save(path)
        return path.as_posix()
    except Exception:
        return ""


async def generate_report_files(
    report: str,
    filename: str,
    *,
    output_dir: str | Path = "outputs",
    quote_paths: bool = False,
    include_legacy_md_key: bool = False,
    title: str = "Rivalens Report",
    css_path: str | None = None,
) -> ReportArtifacts:
    """Export a Markdown report to Markdown, PDF, DOCX, and HTML files."""
    if not isinstance(report, str):
        report = str(report)

    markdown_path = _artifact_path(output_dir, filename, "md")
    pdf_path = _artifact_path(output_dir, filename, "pdf")
    docx_path = _artifact_path(output_dir, filename, "docx")
    html_path = _artifact_path(output_dir, filename, "html")

    artifacts = {
        "markdown": await _write_markdown(markdown_path, report),
        "pdf": await _write_pdf(pdf_path, report, css_path=css_path),
        "docx": await _write_docx(docx_path, report),
        "html": await _write_html(html_path, report, title=title),
    }
    result = {
        key: (_artifact_value(Path(value), quote_paths) if value else "")
        for key, value in artifacts.items()
    }
    if include_legacy_md_key:
        result["md"] = result["markdown"]
    return result
