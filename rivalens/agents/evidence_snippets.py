"""Sentence-level evidence snippet enrichment for accepted evidence."""

from __future__ import annotations

import re
from typing import Any

from rivalens.agents.success_criteria import (
    normalize_success_criteria,
    success_criterion_terms,
    text_terms,
)
from rivalens.schema import EvidenceSnippet, ResearchBranch


class EvidenceSnippetBuilder:
    """Select top-k sentence snippets that support matched success criteria."""

    def __init__(
        self,
        top_k_per_criterion: int = 2,
        max_snippets_per_evidence: int = 6,
    ) -> None:
        self.top_k_per_criterion = max(1, top_k_per_criterion)
        self.max_snippets_per_evidence = max(1, max_snippets_per_evidence)

    def enrich(
        self,
        evidence_items: list[dict[str, Any]],
        research_branches: list[ResearchBranch],
    ) -> dict[str, int]:
        branch_by_id = {
            branch.get("id", ""): branch
            for branch in research_branches
            if branch.get("id")
        }
        enriched_count = 0
        snippet_count = 0
        for evidence in evidence_items:
            branch = branch_by_id.get(evidence.get("branch_id", ""), {})
            snippets = self.build_for_evidence(evidence, branch)
            evidence["evidence_snippets"] = snippets
            if snippets:
                enriched_count += 1
                snippet_count += len(snippets)
        return {
            "evidence_snippet_enriched_count": enriched_count,
            "evidence_snippet_count": snippet_count,
        }

    def build_for_evidence(
        self,
        evidence: dict[str, Any],
        branch: dict[str, Any],
    ) -> list[EvidenceSnippet]:
        criterion_ids = [
            str(criterion_id)
            for criterion_id in evidence.get("success_criterion_ids", [])
            if str(criterion_id or "").strip()
        ]
        if not criterion_ids:
            return []

        criteria_by_id = {
            criterion.get("id", ""): criterion
            for criterion in normalize_success_criteria(branch.get("success_criteria", []))
            if criterion.get("id")
        }
        sentences = self._candidate_sentences(evidence)
        if not criteria_by_id or not sentences:
            return []

        ranked_snippets: list[tuple[float, EvidenceSnippet]] = []
        evidence_id = str(evidence.get("id", "") or "unknown")
        for criterion_id in criterion_ids:
            criterion = criteria_by_id.get(criterion_id)
            if not criterion:
                continue
            criterion_terms = success_criterion_terms(criterion, branch)
            if not criterion_terms:
                continue
            candidates = self._rank_sentences_for_criterion(
                evidence_id,
                criterion_id,
                criterion_terms,
                sentences,
            )
            for rank, (score, snippet) in enumerate(
                candidates[: self.top_k_per_criterion],
                start=1,
            ):
                snippet["rank"] = rank
                ranked_snippets.append((score, snippet))

        ranked_snippets.sort(key=lambda item: (-item[0], item[1].get("id", "")))
        return [
            snippet
            for _score, snippet in ranked_snippets[: self.max_snippets_per_evidence]
        ]

    def _rank_sentences_for_criterion(
        self,
        evidence_id: str,
        criterion_id: str,
        criterion_terms: set[str],
        sentences: list[dict[str, str]],
    ) -> list[tuple[float, EvidenceSnippet]]:
        candidates = []
        for index, sentence in enumerate(sentences, start=1):
            text = sentence["text"]
            matched_terms = sorted(criterion_terms.intersection(text_terms(text)))
            if not matched_terms:
                continue
            score = self._score_sentence(text, matched_terms, criterion_terms)
            snippet: EvidenceSnippet = {
                "id": f"{evidence_id}_snip_{criterion_id}_{index}",
                "text": text,
                "success_criterion_id": criterion_id,
                "reason": (
                    "matches success criterion terms: "
                    + ", ".join(matched_terms[:6])
                ),
                "matched_terms": matched_terms,
                "source_field": sentence["source_field"],
                "confidence": round(min(0.95, 0.45 + score), 3),
            }
            candidates.append((score, snippet))
        candidates.sort(
            key=lambda item: (
                -item[0],
                len(item[1].get("text", "")),
                item[1].get("id", ""),
            ),
        )
        return candidates

    def _score_sentence(
        self,
        text: str,
        matched_terms: list[str],
        criterion_terms: set[str],
    ) -> float:
        coverage = len(matched_terms) / max(1, len(criterion_terms))
        score = coverage + min(0.4, 0.12 * len(matched_terms))
        if len(text) > 280:
            score -= 0.12
        return max(0.0, score)

    def _candidate_sentences(self, evidence: dict[str, Any]) -> list[dict[str, str]]:
        candidates = []
        seen = set()
        for field in ("title", "excerpt", "summary"):
            for sentence in self._split_sentences(str(evidence.get(field, "") or "")):
                normalized = " ".join(sentence.split())
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(
                    {
                        "source_field": field,
                        "text": normalized[:420],
                    },
                )
        return candidates

    def _split_sentences(self, text: str) -> list[str]:
        normalized = re.sub(r"([.!?。！？；;])", r"\1\n", text)
        return [
            sentence.strip()
            for sentence in normalized.splitlines()
            if sentence.strip()
        ]
