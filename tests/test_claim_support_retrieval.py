from __future__ import annotations

from typing import Any

from rivalens.agents.claim_support import ClaimSupportReviewer


class FakeEvidenceVectorStore:
    def __init__(self) -> None:
        self.indexed_count = 0
        self.search_queries: list[str] = []

    def index_evidence_items(
        self,
        *,
        research_id: str,
        run_id: str | None,
        evidence_items: Any,
        replace_existing: bool = False,
    ) -> int:
        items = list(evidence_items)
        self.indexed_count = len(items)
        return self.indexed_count

    def search(
        self,
        query: str,
        *,
        research_id: str | None = None,
        run_id: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        self.search_queries.append(query)
        return [{"id": "ev_1"}]


def test_claim_support_uses_retrieved_evidence_ids() -> None:
    store = FakeEvidenceVectorStore()
    reviewer = ClaimSupportReviewer(
        enable_retrieval=True,
        max_retrieval_results=3,
        evidence_vector_store=store,
    )

    result = reviewer.review(
        {
            "task": {"run_id": "run_1"},
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "claim": "DingTalk supports enterprise approval workflow automation.",
                    "analysis_dimension_id": "workflow",
                    "evidence_ids": [],
                    "confidence": 0.86,
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "title": "DingTalk approval workflow",
                    "url": "https://example.com/dingtalk-workflow",
                    "excerpt": "DingTalk supports enterprise approval workflow automation.",
                    "source_type": "official_site",
                    "confidence": 0.9,
                }
            ],
            "messages": [],
            "agent_events": [],
        }
    )

    review = result["claim_support_reviews"][0]
    assert store.indexed_count == 1
    assert store.search_queries
    assert review["support_status"] == "supported"
    assert review["evidence_ids"] == ["ev_1"]
    assert review["retrieved_evidence_ids"] == ["ev_1"]
    assert "ev_1" in review["retrieval_notes"]
