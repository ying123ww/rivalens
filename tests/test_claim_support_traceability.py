from __future__ import annotations

from rivalens.agents.claim_support import ClaimSupportReviewer


def test_claim_support_repairs_evidence_ids_from_knowledge_facts() -> None:
    reviewer = ClaimSupportReviewer()

    result = reviewer.review(
        {
            "analysis_claims": [
                {
                    "id": "claim_1",
                    "claim": "DingTalk supports enterprise approval workflow automation.",
                    "analysis_dimension_id": "workflow",
                    "knowledge_fact_ids": ["fact_1"],
                    "evidence_ids": [],
                    "confidence": 0.86,
                }
            ],
            "knowledge_facts": [
                {
                    "id": "fact_1",
                    "competitor": "DingTalk",
                    "analysis_dimension_id": "workflow",
                    "object": "DingTalk supports enterprise approval workflow automation.",
                    "statement": "DingTalk supports enterprise approval workflow automation.",
                    "evidence_ids": ["ev_1"],
                }
            ],
            "evidence_items": [
                {
                    "id": "ev_1",
                    "competitor": "DingTalk",
                    "analysis_dimension_id": "workflow",
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
    message = result["messages"][-1]
    event = result["agent_events"][-1]

    assert review["support_status"] == "supported"
    assert review["recommended_action"] == "accept"
    assert review["evidence_ids"] == ["ev_1"]
    assert review["knowledge_fact_ids"] == ["fact_1"]
    assert "retrieved_evidence_ids" not in review
    assert "retrieval" not in message["payload"]
    assert message["evidence_ids"] == ["ev_1"]
    assert event["output"]["repaired_evidence_binding_count"] == 1
    assert "verification_task_queue" not in result
