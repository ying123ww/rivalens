"""UniFuncs Deep Search retriever for Rivalens.

This retriever uses UniFuncs U-deepsearch to discover source URLs. It returns
search snippets only; Rivalens' scraper remains responsible for fetching full
page content before evidence review.
"""

import json
import os
import re
from typing import Any

import requests


class UniFuncsDeepSearch:
    """UniFuncs Deep Search retriever."""

    def __init__(self, query, headers=None, topic="general", query_domains=None):
        self.query = query
        self.headers = headers or {}
        self.topic = topic
        self.query_domains = query_domains or None
        self.base_url = os.getenv(
            "UNIFUNCS_DEEPSEARCH_BASE_URL",
            "https://api.unifuncs.com/deepsearch/v1",
        ).rstrip("/")
        self.api_key = self.get_api_key()
        self.model = os.getenv("UNIFUNCS_DEEPSEARCH_MODEL", "s3")
        self.language = os.getenv("UNIFUNCS_DEEPSEARCH_LANGUAGE", "zh")
        self.reference_style = os.getenv("UNIFUNCS_DEEPSEARCH_REFERENCE_STYLE", "link")
        self.max_depth = self._int_env("UNIFUNCS_DEEPSEARCH_MAX_DEPTH", 8)
        self.timeout = self._int_env("UNIFUNCS_DEEPSEARCH_TIMEOUT", 180)

    def get_api_key(self) -> str:
        api_key = self.headers.get("unifuncs_api_key") or os.getenv("UNIFUNCS_API_KEY", "")
        if not api_key:
            print(
                "UniFuncs API key not found. Set UNIFUNCS_API_KEY to use "
                "the unifuncs_deepsearch retriever."
            )
        return api_key

    def search(self, max_results=10):
        if not self.api_key:
            return []

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self._payload(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._extract_results(response.json(), max_results=max_results)
        except Exception as e:
            print(f"Error: {e}. Failed fetching UniFuncs Deep Search sources.")
            return []

    def _payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.query}],
            "stream": False,
            "introduction": os.getenv(
                "UNIFUNCS_DEEPSEARCH_INTRODUCTION",
                (
                    "You are a competitor-analysis evidence searcher. Prioritize "
                    "official websites, pricing pages, documentation, help centers, "
                    "press releases, and trustworthy third-party sources. Keep source URLs."
                ),
            ),
            "reference_style": self.reference_style,
            "max_depth": self.max_depth,
            "output_prompt": os.getenv(
                "UNIFUNCS_DEEPSEARCH_OUTPUT_PROMPT",
                (
                    "Return verifiable source candidates for the user question. "
                    "For each source, include title, URL, concise summary, relevance, "
                    "and confidence. Do not write the final report."
                ),
            ),
        }

        if self.language and self.language != "auto":
            payload["language"] = self.language

        if self.query_domains:
            payload["domain_scope"] = self.query_domains

        domain_blacklist = self._csv_env("UNIFUNCS_DEEPSEARCH_DOMAIN_BLACKLIST")
        if domain_blacklist:
            payload["domain_blacklist"] = domain_blacklist

        important_keywords = self._csv_env("UNIFUNCS_DEEPSEARCH_IMPORTANT_KEYWORDS")[:20]
        if important_keywords:
            payload["important_keywords"] = important_keywords

        important_urls = self._csv_env("UNIFUNCS_DEEPSEARCH_IMPORTANT_URLS")[:20]
        if important_urls:
            payload["important_urls"] = important_urls

        important_prompt = os.getenv("UNIFUNCS_DEEPSEARCH_IMPORTANT_PROMPT", "").strip()
        if important_prompt:
            payload["important_prompt"] = important_prompt

        return payload

    def _extract_results(self, response_json: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
        content = self._response_content(response_json)
        if not content:
            return []

        structured_results = self._extract_structured_results(content)
        if structured_results:
            return structured_results[:max_results]

        return self._extract_url_results(content)[:max_results]

    def _response_content(self, response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content

        data = response_json.get("data") or {}
        result = data.get("result") or {}
        content = result.get("content") or data.get("content") or response_json.get("content")
        return content if isinstance(content, str) else ""

    def _extract_structured_results(self, content: str) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, dict):
            items = parsed.get("sources") or parsed.get("results") or parsed.get("items") or []
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("href")
            if not url:
                continue
            results.append(
                self._result(
                    url=url,
                    title=item.get("title") or item.get("name") or url,
                    body=item.get("summary") or item.get("body") or item.get("snippet") or "",
                )
            )
        return self._dedupe_results(results)

    def _extract_url_results(self, content: str) -> list[dict[str, Any]]:
        markdown_titles: dict[str, str] = {}
        for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", content):
            markdown_titles[self._clean_url(url)] = title.strip()

        results = []
        seen = set()
        for raw_url in re.findall(r"https?://[^\s\]\)>,\"']+", content):
            url = self._clean_url(raw_url)
            if not url or url in seen:
                continue
            seen.add(url)
            context_line = self._line_for_url(content, raw_url)
            results.append(
                self._result(
                    url=url,
                    title=markdown_titles.get(url) or self._title_from_line(context_line, url),
                    body=context_line,
                )
            )
        return results

    def _result(self, url: str, title: str, body: str) -> dict[str, Any]:
        return {
            "title": title or url,
            "href": url,
            "body": body,
            "source_provider": "unifuncs_deepsearch",
            "content_is_full_text": False,
        }

    def _dedupe_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped = []
        seen = set()
        for result in results:
            url = self._clean_url(result.get("href", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append({**result, "href": url})
        return deduped

    def _line_for_url(self, content: str, raw_url: str) -> str:
        for line in content.splitlines():
            if raw_url in line:
                return line.strip()
        return raw_url

    def _title_from_line(self, line: str, url: str) -> str:
        before_url = line.split(url, 1)[0].strip(" -:[]()0123456789.")
        return before_url or url

    def _clean_url(self, url: str) -> str:
        return url.rstrip(".,;:!?)]}")

    def _csv_env(self, key: str) -> list[str]:
        value = os.getenv(key, "")
        return [item.strip() for item in value.split(",") if item.strip()]

    def _int_env(self, key: str, default: int) -> int:
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default
