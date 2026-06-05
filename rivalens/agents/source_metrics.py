"""Deterministic source metrics for accepted collection evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rivalens.research.source_identity import identify_source_url
from rivalens.schema import EvidenceReviewResult, ResearchBranch, SourceMetrics


class SourceMetricsBuilder:
    """Summarize source independence without deciding coverage outcomes."""

    def build(
        self,
        *,
        branch: ResearchBranch,
        evidence_items: list[dict[str, Any]],
        evidence_review: EvidenceReviewResult,
    ) -> SourceMetrics:
        accepted_ids = set(evidence_review.get("accepted_evidence_ids", []))
        accepted_evidence = [
            evidence
            for evidence in evidence_items
            if evidence.get("id", "") in accepted_ids
        ]

        canonical_groups: dict[str, dict[str, Any]] = {}
        domain_counts: dict[str, int] = {}
        source_type_counts: dict[str, int] = {}
        content_hash_groups: dict[str, list[str]] = defaultdict(list)
        cache_status_counts: dict[str, int] = defaultdict(int)

        for evidence in accepted_evidence:
            identity = self._source_identity(evidence)
            canonical_url = identity["canonical_url"]
            domain = identity["domain"]
            source_type = evidence.get("source_type", "other") or "other"
            evidence_id = evidence.get("id", "")
            content_hash = self._content_hash(evidence)
            cache_status = (evidence.get("source_cache") or {}).get("status", "")

            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
            if domain:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if cache_status:
                cache_status_counts[cache_status] += 1

            group = canonical_groups.setdefault(
                canonical_url,
                {
                    "canonical_url": canonical_url,
                    "domain": domain,
                    "source_types": [],
                    "evidence_ids": [],
                    "urls": [],
                    "is_primary_source": False,
                    "content_sha256_values": [],
                },
            )
            if source_type not in group["source_types"]:
                group["source_types"].append(source_type)
            if evidence_id:
                group["evidence_ids"].append(evidence_id)
            url = evidence.get("url", "")
            if url and url not in group["urls"]:
                group["urls"].append(url)
            group["is_primary_source"] = bool(
                group["is_primary_source"] or evidence.get("is_primary_source")
            )
            if content_hash:
                if content_hash not in group["content_sha256_values"]:
                    group["content_sha256_values"].append(content_hash)
                content_hash_groups[content_hash].append(canonical_url)

        canonical_sources = list(canonical_groups.values())
        duplicate_groups = self._duplicate_groups(
            canonical_sources,
            content_hash_groups,
        )
        independent_source_count = self._independent_source_count(
            canonical_sources,
            content_hash_groups,
        )

        return {
            "id": f"source_metrics_{branch.get('id', 'unknown')}",
            "branch_id": branch.get("id", ""),
            "evidence_review_id": evidence_review.get("id", ""),
            "accepted_evidence_ids": [
                evidence.get("id", "")
                for evidence in accepted_evidence
                if evidence.get("id")
            ],
            "accepted_evidence_count": len(accepted_evidence),
            "unique_canonical_url_count": len(canonical_sources),
            "unique_domain_count": len(domain_counts),
            "independent_source_count": independent_source_count,
            "primary_source_count": sum(
                1 for source in canonical_sources if source.get("is_primary_source")
            ),
            "source_type_counts": source_type_counts,
            "domain_counts": domain_counts,
            "duplicate_source_groups": duplicate_groups,
            "canonical_sources": canonical_sources,
            "source_cache_hit_count": int(cache_status_counts.get("hit", 0)),
            "source_cache_stored_count": int(cache_status_counts.get("stored", 0)),
        }

    def _source_identity(self, evidence: dict[str, Any]) -> dict[str, str]:
        source_cache = evidence.get("source_cache") or {}
        canonical_url = (
            evidence.get("canonical_url")
            or source_cache.get("canonical_url")
            or ""
        )
        domain = evidence.get("source_domain") or source_cache.get("domain") or ""
        if canonical_url and domain:
            return {"canonical_url": canonical_url, "domain": domain}

        identity = identify_source_url(evidence.get("url", ""))
        return {
            "canonical_url": canonical_url or identity.canonical_url or evidence.get("url", ""),
            "domain": domain or identity.domain,
        }

    def _content_hash(self, evidence: dict[str, Any]) -> str:
        source_cache = evidence.get("source_cache") or {}
        return (
            evidence.get("scraped_content_sha256")
            or source_cache.get("content_sha256")
            or ""
        )

    def _duplicate_groups(
        self,
        canonical_sources: list[dict[str, Any]],
        content_hash_groups: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        duplicate_groups = []
        for source in canonical_sources:
            evidence_ids = list(source.get("evidence_ids", []))
            if len(evidence_ids) <= 1:
                continue
            duplicate_groups.append(
                {
                    "reason": "same_canonical_url",
                    "canonical_url": source.get("canonical_url", ""),
                    "domain": source.get("domain", ""),
                    "evidence_ids": evidence_ids,
                    "source_types": list(source.get("source_types", [])),
                }
            )

        for content_hash, canonical_urls in content_hash_groups.items():
            unique_canonical_urls = list(dict.fromkeys(canonical_urls))
            if len(unique_canonical_urls) <= 1:
                continue
            evidence_ids = []
            source_types = []
            for source in canonical_sources:
                if source.get("canonical_url") not in unique_canonical_urls:
                    continue
                evidence_ids.extend(source.get("evidence_ids", []))
                for source_type in source.get("source_types", []):
                    if source_type not in source_types:
                        source_types.append(source_type)
            duplicate_groups.append(
                {
                    "reason": "same_content_hash",
                    "content_sha256": content_hash,
                    "canonical_urls": unique_canonical_urls,
                    "evidence_ids": evidence_ids,
                    "source_types": source_types,
                }
            )
        return duplicate_groups

    def _independent_source_count(
        self,
        canonical_sources: list[dict[str, Any]],
        content_hash_groups: dict[str, list[str]],
    ) -> int:
        mirrored_hashes = {
            content_hash
            for content_hash, canonical_urls in content_hash_groups.items()
            if len(set(canonical_urls)) > 1
        }
        independent_keys = set()
        for source in canonical_sources:
            mirrored_content_hash = next(
                (
                    content_hash
                    for content_hash in source.get("content_sha256_values", [])
                    if content_hash in mirrored_hashes
                ),
                "",
            )
            if mirrored_content_hash:
                independent_keys.add(f"content:{mirrored_content_hash}")
                continue
            domain = source.get("domain", "")
            if domain:
                independent_keys.add(f"domain:{domain}")
            else:
                independent_keys.add(f"canonical:{source.get('canonical_url', '')}")
        return len(independent_keys)
