"""Focused tests for collection-stage quality and coverage follow-up loops."""

import asyncio
from typing import Any

from rivalens.agents.collection import CollectionAgent


class FakeEvidenceCollector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def collect(
        self,
        collection_task: dict[str, Any],
        mode: Any,
        source_urls: list[str],
        verbose: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(dict(collection_task))
        dimension_id = collection_task.get("dimension_id", "")
        generated_from_gap = collection_task.get("generated_from_gap", "")
        if dimension_id == "competitor_profile":
            evidence_items = [
                {
                    "title": "Acme official product page",
                    "url": "https://acme.example/",
                    "source_type": "official_site",
                    "excerpt": (
                        "Acme official website canonical public page. "
                        "Acme product brand platform identity is public. "
                        "Acme is categorized and positioned as a pricing platform."
                    ),
                    "confidence": 0.9,
                }
            ]
        elif generated_from_gap == "missing_preferred_source_type":
            evidence_items = [
                {
                    "title": "Acme Pricing",
                    "url": "https://acme.example/pricing",
                    "source_type": "pricing_page",
                    "excerpt": (
                        "Acme public pricing packaging plans billing include Free, "
                        "Pro, and Enterprise pricing tiers."
                    ),
                    "confidence": 0.92,
                },
                {
                    "title": "Acme Enterprise Pricing",
                    "url": "https://acme.example/enterprise-pricing",
                    "source_type": "pricing_page",
                    "excerpt": (
                        "Acme enterprise pricing page describes quote-based "
                        "billing and annual packaging."
                    ),
                    "confidence": 0.88,
                },
            ]
        else:
            evidence_items = [
                {
                    "title": "Acme pricing plan news",
                    "url": "https://news.example/acme-pricing-plans",
                    "source_type": "news",
                    "excerpt": (
                        "Acme public pricing packaging plans billing include "
                        "free and enterprise options."
                    ),
                    "confidence": 0.76,
                },
                {
                    "title": "Acme billing report",
                    "url": "https://news.example/acme-billing-report",
                    "source_type": "news",
                    "excerpt": (
                        "Acme pricing plans and billing packaging are discussed "
                        "in public market coverage."
                    ),
                    "confidence": 0.74,
                },
            ]
        return {
            "task": collection_task,
            "mode": str(mode),
            "query": collection_task.get("query", ""),
            "context": "",
            "evidence_items": evidence_items,
            "costs": 0.0,
        }


def test_collection_quality_loop_expands_preferred_source_gap():
    collector = FakeEvidenceCollector()
    agent = CollectionAgent(
        evidence_collector=collector,
        max_branch_depth=1,
        max_expansion_branches=4,
        max_concurrent_collections=1,
    )
    state = {
        "task": {
            "query": "Compare Acme pricing.",
            "competitors": ["Acme"],
            "verbose": False,
        },
        "competitors": ["Acme"],
        "analysis_dimensions": [
            {
                "id": "pricing_model",
                "name": "Pricing Model",
                "source_hints": ["pricing_page"],
                "guiding_questions": [
                    "What public pricing, packaging, plans, or billing units are available?"
                ],
                "schema_field_ids": ["pricing_model"],
            }
        ],
    }

    result = asyncio.run(agent.run(state))

    pricing_root = next(
        branch
        for branch in result["research_branches"]
        if branch["id"] == "collect_acme_pricing_model"
    )
    child_branches = [
        branch
        for branch in result["research_branches"]
        if branch.get("parent_id") == pricing_root["id"]
    ]
    assert pricing_root["status"] == "expanded"
    assert pricing_root["coverage_status"] == "ready_for_analysis"
    assert pricing_root["coverage_state_id"] == f"coverage_state_{pricing_root['id']}"
    assert len(child_branches) == 1
    assert child_branches[0]["generated_from_gap"] == "missing_preferred_source_type"

    root_coverage = next(
        assessment
        for assessment in result["coverage_assessments"]
        if assessment["branch_id"] == pricing_root["id"]
    )
    root_evidence_review = next(
        review
        for review in result["evidence_reviews"]
        if review["branch_id"] == pricing_root["id"]
    )
    evidence_finding_codes = {
        finding["code"] for finding in root_evidence_review["findings"]
    }
    assert "missing_preferred_source_type" not in evidence_finding_codes
    assert root_coverage["source_type_gaps"][0]["code"] == "missing_preferred_source_type"
    assert root_coverage["source_type_gaps"][0]["blocking"] is False
    assert root_coverage["quality_gap_codes"] == []
    assert root_coverage["selected_follow_up_specs"][0]["generated_from_gap"] == "missing_preferred_source_type"

    follow_up_calls = [
        call
        for call in collector.calls
        if call.get("generated_from_gap") == "missing_preferred_source_type"
    ]
    assert len(follow_up_calls) == 1

    follow_up_review = next(
        review
        for review in result["evidence_reviews"]
        if review["branch_id"] == child_branches[0]["id"]
    )
    assert follow_up_review["required_action"] == "accept"
    assert len(follow_up_review["accepted_evidence_ids"]) == 2

    event = result["agent_events"][-1]
    assert event["output"]["expanded_branch_count"] == 1
    assert event["output"]["accepted_follow_up_evidence_count"] == 2

    summary = next(
        item
        for item in result["branch_coverage_states"]
        if item["root_branch_id"] == pricing_root["id"]
    )
    resolved_gap = next(
        gap
        for gap in summary["coverage_gaps"]
        if gap["code"] == "missing_preferred_source_type"
    )
    assert summary["status"] == "ready_for_analysis"
    assert summary["id"] == pricing_root["coverage_state_id"]
    assert summary["open_gap_codes"] == []
    assert summary["resolved_gap_codes"] == ["missing_preferred_source_type"]
    assert resolved_gap["gap_type"] == "source_type"
    assert resolved_gap["blocking"] is False
    assert resolved_gap["status"] == "resolved"
    assert resolved_gap["resolved_by_branch_ids"] == [child_branches[0]["id"]]
    assert resolved_gap["resolved_by_evidence_ids"] == follow_up_review["accepted_evidence_ids"]
    assert summary["success_criteria"][0]["status"] == "satisfied"


def test_unresolved_source_hints_do_not_block_branch_coverage():
    collector = FakeEvidenceCollector()
    agent = CollectionAgent(
        evidence_collector=collector,
        max_branch_depth=0,
        max_expansion_branches=4,
        max_concurrent_collections=1,
    )
    state = {
        "task": {
            "query": "Compare Acme pricing.",
            "competitors": ["Acme"],
            "verbose": False,
        },
        "competitors": ["Acme"],
        "analysis_dimensions": [
            {
                "id": "pricing_model",
                "name": "Pricing Model",
                "source_hints": ["pricing_page"],
                "guiding_questions": [
                    "What public pricing, packaging, plans, or billing units are available?"
                ],
                "schema_field_ids": ["pricing_model"],
            }
        ],
    }

    result = asyncio.run(agent.run(state))

    pricing_root = next(
        branch
        for branch in result["research_branches"]
        if branch["id"] == "collect_acme_pricing_model"
    )
    child_branches = [
        branch
        for branch in result["research_branches"]
        if branch.get("parent_id") == pricing_root["id"]
    ]
    root_coverage = next(
        assessment
        for assessment in result["coverage_assessments"]
        if assessment["branch_id"] == pricing_root["id"]
    )
    pricing_summary = next(
        item
        for item in result["branch_coverage_states"]
        if item["root_branch_id"] == pricing_root["id"]
    )

    assert root_coverage["source_type_gaps"][0]["code"] == "missing_preferred_source_type"
    assert root_coverage["source_type_gaps"][0]["blocking"] is False
    assert child_branches == []
    assert pricing_summary["status"] == "ready_for_analysis"
    assert pricing_summary["open_gap_codes"] == ["missing_preferred_source_type"]
    assert pricing_summary["blocked_gap_codes"] == []
