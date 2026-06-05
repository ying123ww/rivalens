"""Source URL identity helpers for crawler caching and source metrics."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAM_NAMES = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}
TRACKING_PARAM_PREFIXES = ("utm_",)


@dataclass(frozen=True)
class SourceIdentity:
    original_url: str
    canonical_url: str
    domain: str


def identify_source_url(url: str) -> SourceIdentity:
    """Return a conservative canonical identity for an HTTP source URL."""
    original_url = (url or "").strip()
    if not original_url:
        return SourceIdentity(original_url="", canonical_url="", domain="")

    parsed = urlsplit(original_url)
    if not parsed.scheme or not parsed.netloc:
        return SourceIdentity(
            original_url=original_url,
            canonical_url=original_url,
            domain="",
        )

    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    domain = host[4:] if host.startswith("www.") else host
    netloc = domain
    if parsed.port and not _is_default_port(scheme, parsed.port):
        netloc = f"{domain}:{parsed.port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query = _canonical_query(parsed.query)
    canonical_url = urlunsplit((scheme, netloc, path, query, ""))
    return SourceIdentity(
        original_url=original_url,
        canonical_url=canonical_url,
        domain=domain,
    )


def _canonical_query(query: str) -> str:
    pairs = []
    for name, value in parse_qsl(query, keep_blank_values=True):
        lowered_name = name.lower()
        if lowered_name in TRACKING_PARAM_NAMES:
            continue
        if any(lowered_name.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
            continue
        pairs.append((name, value))
    return urlencode(sorted(pairs), doseq=True)


def _is_default_port(scheme: str, port: int) -> bool:
    return (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
