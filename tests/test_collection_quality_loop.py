"""Focused tests for collection-stage quality and coverage follow-up loops."""

import asyncio
from typing import Any

from rivalens.agents.collection import CollectionAgent
from rivalens.agents.coverage_state import BranchCoverageStateBuilder
from rivalens.agents.coverage_review import CoverageReviewer
from rivalens.agents.source_metrics import SourceMetricsBuilder
from rivalens.agents.source_gap_advisor import SourceGapDecision
from rivalens.agents.success_criteria import normalize_success_criteria
from rivalens.research.skills.researcher import ResearchConductor


class FakeSourceGapAdvisor:
    provider = "fake"
    model = "fake-source-gap"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def decide(
        self,
        *,
        branch: dict[str, Any],
        accepted_evidence: list[dict[str, Any]],
        found_source_types: list[str],
        source_preferences: list[str],
        minimum_count: int,
        source_metrics: dict[str, Any] | None = None,
    ) -> SourceGapDecision:
        self.calls.append(
            {
                "branch_id": branch.get("id", ""),
                "accepted_evidence_ids": [
                    evidence.get("id", "")
                    for evidence in accepted_evidence
                    if evidence.get("id")
                ],
                "found_source_types": list(found_source_types),
                "source_preferences": list(source_preferences),
                "minimum_count": minimum_count,
                "source_metrics": dict(source_metrics or {}),
            }
        )
        if self.fail:
            raise RuntimeError("fake source gap advisor failure")
        if "pricing_page" not in source_preferences:
            return SourceGapDecision(open_gap=False, reason="No pricing source preference.")
        if "pricing_page" in found_source_types:
            return SourceGapDecision(open_gap=False, reason="Pricing page evidence is present.")
        return SourceGapDecision(
            open_gap=True,
            gap_code="needs_pricing_page_source",
            query_focus="Find an official pricing page with public plans, packaging, or billing.",
            target_source_types=["pricing_page"],
            blocking=False,
            reason="Accepted evidence covers pricing from news sources but lacks a primary pricing source.",
            expected_improvement="Adds a traceable public pricing source for downstream analysis claims.",
            confidence=0.84,
        )


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
        elif generated_from_gap == "needs_pricing_page_source":
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


class FakeMixedQualityEvidenceCollector:
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
        if collection_task.get("generated_from_gap") == "mixed_quality_high_rejected_ratio":
            evidence_items = [
                {
                    "title": "Acme stable pricing source",
                    "url": "https://stable.example/acme-pricing",
                    "source_type": "news",
                    "excerpt": "Acme pricing plans and billing packaging are described clearly.",
                    "confidence": 0.83,
                },
                {
                    "title": "Acme official billing note",
                    "url": "https://stable.example/acme-billing",
                    "source_type": "official_site",
                    "excerpt": "Acme public billing information describes plans and invoices.",
                    "confidence": 0.88,
                },
            ]
        else:
            evidence_items = [
                {
                    "title": "Acme usable pricing mention",
                    "url": "https://good.example/acme-pricing",
                    "source_type": "news",
                    "excerpt": "Acme pricing plans are discussed in readable public evidence.",
                    "confidence": 0.75,
                },
                {
                    "title": "Broken scrape A",
                    "url": "https://bad.example/a",
                    "source_type": "news",
                    "excerpt": "�����",
                    "confidence": 0.2,
                },
                {
                    "title": "Broken scrape B",
                    "url": "https://bad.example/b",
                    "source_type": "news",
                    "excerpt": "�����",
                    "confidence": 0.2,
                },
                {
                    "title": "Broken scrape C",
                    "url": "https://bad.example/c",
                    "source_type": "news",
                    "excerpt": "�����",
                    "confidence": 0.2,
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


def test_success_criteria_do_not_carry_source_targets():
    normalized = normalize_success_criteria(
        [
            {
                "id": "pricing_content",
                "description": "Identify public pricing and packaging.",
                "target_source_types": ["pricing_page"],
                "required_source_types": ["pricing_page"],
            }
        ]
    )

    assert normalized == [
        {
            "id": "pricing_content",
            "description": "Identify public pricing and packaging.",
        }
    ]


def test_source_metrics_builder_counts_independent_sources():
    branch = {
        "id": "collect_acme_pricing_model",
        "competitor": "Acme",
        "dimension_id": "pricing_model",
    }
    evidence_items = [
        {
            "id": "ev_1",
            "url": "https://www.example.com/pricing?utm_source=search",
            "source_type": "pricing_page",
            "is_primary_source": True,
        },
        {
            "id": "ev_2",
            "url": "https://example.com/pricing/",
            "source_type": "pricing_page",
            "is_primary_source": True,
        },
        {
            "id": "ev_3",
            "url": "https://news.example/acme-pricing",
            "source_type": "news",
            "is_primary_source": False,
        },
        {
            "id": "ev_4",
            "url": "https://news.example/acme-billing",
            "source_type": "news",
            "is_primary_source": False,
        },
        {
            "id": "ev_rejected",
            "url": "https://mirror.example/acme",
            "source_type": "news",
            "is_primary_source": False,
        },
    ]
    evidence_review = {
        "id": "ev_review_collect_acme_pricing_model",
        "accepted_evidence_ids": ["ev_1", "ev_2", "ev_3", "ev_4"],
        "rejected_evidence_ids": ["ev_rejected"],
    }

    metrics = SourceMetricsBuilder().build(
        branch=branch,
        evidence_items=evidence_items,
        evidence_review=evidence_review,
    )

    assert metrics["accepted_evidence_count"] == 4
    assert metrics["unique_canonical_url_count"] == 3
    assert metrics["unique_domain_count"] == 2
    assert metrics["independent_source_count"] == 2
    assert metrics["primary_source_count"] == 1
    assert metrics["source_type_counts"] == {"pricing_page": 2, "news": 2}
    assert metrics["domain_counts"] == {"example.com": 2, "news.example": 2}
    duplicate_group = next(
        group
        for group in metrics["duplicate_source_groups"]
        if group["reason"] == "same_canonical_url"
    )
    assert duplicate_group["evidence_ids"] == ["ev_1", "ev_2"]


def test_mixed_quality_evidence_triggers_differential_retry():
    collector = FakeMixedQualityEvidenceCollector()
    source_gap_advisor = FakeSourceGapAdvisor()
    agent = CollectionAgent(
        evidence_collector=collector,
        coverage_reviewer=CoverageReviewer(source_gap_advisor=source_gap_advisor),
        max_branch_depth=1,
        max_expansion_branches=4,
        max_concurrent_collections=1,
    )
    state = {
        "task": {
            "query": "Compare Acme market signals.",
            "competitors": ["Acme"],
            "verbose": False,
        },
        "competitors": ["Acme"],
        "analysis_dimensions": [
            {
                "id": "market_growth",
                "name": "Market Growth",
                "source_hints": [],
                "guiding_questions": [],
                "schema_field_ids": ["market_growth"],
            }
        ],
    }

    result = asyncio.run(agent.run(state))

    root = next(
        branch
        for branch in result["research_branches"]
        if branch["id"] == "collect_acme_market_growth"
    )
    child = next(
        branch
        for branch in result["research_branches"]
        if branch.get("parent_id") == root["id"]
    )
    root_coverage = next(
        assessment
        for assessment in result["coverage_assessments"]
        if assessment["branch_id"] == root["id"]
    )
    child_coverage = next(
        assessment
        for assessment in result["coverage_assessments"]
        if assessment["branch_id"] == child["id"]
    )

    assert root_coverage["quality_stability"]["status"] == "unstable"
    assert root_coverage["quality_stability"]["accepted_count"] == 1
    assert root_coverage["quality_stability"]["rejected_count"] == 3
    assert root_coverage["quality_stability_gaps"][0]["code"] == (
        "mixed_quality_high_rejected_ratio"
    )
    assert root_coverage["selected_follow_up_specs"][0]["decision_action"] == (
        "scope_refinement"
    )
    assert child["generated_from_gap"] == "mixed_quality_high_rejected_ratio"
    assert child["excluded_canonical_urls"] == [
        "https://bad.example/a",
        "https://bad.example/b",
        "https://bad.example/c",
    ]
    follow_up_call = next(
        call
        for call in collector.calls
        if call.get("generated_from_gap") == "mixed_quality_high_rejected_ratio"
    )
    assert follow_up_call["excluded_canonical_urls"] == child["excluded_canonical_urls"]
    assert child_coverage["quality_stability"]["status"] == "stable"
    assert child_coverage["quality_stability"]["rejected_count"] == 0

    summary = next(
        item
        for item in result["branch_coverage_states"]
        if item["root_branch_id"] == root["id"]
    )
    improvement = next(
        item
        for item in summary["improvement_assessments"]
        if item["gap_code"] == "mixed_quality_high_rejected_ratio"
    )
    assert child["triggered_by_gap_type"] == "quality_stability"
    assert child["triggered_by_coverage_assessment_id"] == root_coverage["id"]
    assert improvement["gap_type"] == "quality_stability"
    assert improvement["status"] == "improved"
    assert improvement["resolved_gap"] is True
    assert improvement["baseline"]["rejected_ratio"] == 0.75
    assert improvement["follow_up"]["rejected_ratio"] == 0.0
    assert improvement["deltas"]["rejected_ratio_delta"] == -0.75
    assert "quality_status_improved" in improvement["improved_signals"]


def test_research_conductor_filters_excluded_canonical_urls():
    class DummyResearcher:
        kwargs = {
            "rivalens_excluded_canonical_urls": [
                "https://bad.example/a",
            ]
        }

    conductor = ResearchConductor.__new__(ResearchConductor)
    conductor.researcher = DummyResearcher()

    assert conductor._is_excluded_source_url(
        "https://www.bad.example/a?utm_source=retry"
    )
    assert not conductor._is_excluded_source_url("https://bad.example/b")


def test_coverage_review_does_not_synthesize_dimension_guiding_questions():
    source_gap_advisor = FakeSourceGapAdvisor()
    coverage_reviewer = CoverageReviewer(source_gap_advisor=source_gap_advisor)
    branch = {
        "id": "collect_acme_pricing_model",
        "competitor": "Acme",
        "dimension_id": "pricing_model",
        "dimension_name": "Pricing Model",
        "guiding_questions": [],
        "success_criteria": [],
        "source_hints": [],
    }
    evidence_items = [
        {
            "id": "ev_1",
            "title": "Acme market note",
            "url": "https://news.example/acme",
            "source_type": "news",
            "excerpt": "Acme announced a product update in public market coverage.",
        }
    ]
    evidence_review = {
        "accepted_evidence_ids": ["ev_1"],
        "rejected_evidence_ids": [],
        "findings": [],
        "required_action": "accept",
    }

    result = asyncio.run(
        coverage_reviewer.review(
            branch=branch,
            evidence_items=evidence_items,
            evidence_review=evidence_review,
        )
    )

    assert source_gap_advisor.calls
    assert result["covered_questions"] == []
    assert result["missing_questions"] == []
    assert result["missing_criteria"] == []
    assert result["next_action"] == "ready_for_analysis"


def test_collection_quality_loop_expands_llm_source_gap():
    collector = FakeEvidenceCollector()
    source_gap_advisor = FakeSourceGapAdvisor()
    agent = CollectionAgent(
        evidence_collector=collector,
        coverage_reviewer=CoverageReviewer(source_gap_advisor=source_gap_advisor),
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
    assert child_branches[0]["generated_from_gap"] == "needs_pricing_page_source"
    assert child_branches[0]["source_hints"] == ["pricing_page"]
    assert child_branches[0]["target_source_types"] == ["pricing_page"]

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
    assert "needs_pricing_page_source" not in evidence_finding_codes
    assert root_coverage["source_gap_review"]["status"] == "completed"
    assert root_coverage["source_gap_review"]["no_rule_fallback"] is True
    assert root_coverage["source_metrics"]["accepted_evidence_count"] == 2
    assert root_coverage["source_metrics"]["unique_domain_count"] == 1
    assert root_coverage["source_metrics"]["independent_source_count"] == 1
    assert root_coverage["source_type_gaps"][0]["code"] == "needs_pricing_page_source"
    assert root_coverage["source_type_gaps"][0]["gap_type"] == "source_coverage"
    assert root_coverage["source_type_gaps"][0]["target_source_types"] == ["pricing_page"]
    assert root_coverage["source_type_gaps"][0]["blocking"] is False
    assert root_coverage["source_coverage_gaps"] == root_coverage["source_type_gaps"]
    assert root_coverage["quality_gap_codes"] == []
    assert root_coverage["selected_follow_up_specs"][0]["generated_from_gap"] == "needs_pricing_page_source"
    assert root_coverage["selected_follow_up_specs"][0]["target_source_types"] == ["pricing_page"]
    pricing_advisor_call = next(
        call
        for call in source_gap_advisor.calls
        if call["branch_id"] == pricing_root["id"]
    )
    assert pricing_advisor_call["source_metrics"]["independent_source_count"] == 1

    follow_up_calls = [
        call
        for call in collector.calls
        if call.get("generated_from_gap") == "needs_pricing_page_source"
    ]
    assert len(follow_up_calls) == 1
    assert follow_up_calls[0]["target_source_types"] == ["pricing_page"]
    assert follow_up_calls[0]["source_hints"] == ["pricing_page"]

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
        if gap["code"] == "needs_pricing_page_source"
    )
    assert summary["status"] == "ready_for_analysis"
    assert summary["id"] == pricing_root["coverage_state_id"]
    assert summary["open_gap_codes"] == []
    assert summary["resolved_gap_codes"] == ["needs_pricing_page_source"]
    assert resolved_gap["gap_type"] == "source_type"
    assert resolved_gap["blocking"] is False
    assert resolved_gap["status"] == "resolved"
    assert resolved_gap["resolved_by_branch_ids"] == [child_branches[0]["id"]]
    assert resolved_gap["resolved_by_evidence_ids"] == follow_up_review["accepted_evidence_ids"]
    assert summary["success_criteria"][0]["status"] == "satisfied"
    improvement = next(
        item
        for item in summary["improvement_assessments"]
        if item["gap_code"] == "needs_pricing_page_source"
    )
    assert child_branches[0]["triggered_by_gap_type"] == "source_coverage"
    assert child_branches[0]["triggered_by_coverage_assessment_id"] == root_coverage["id"]
    assert improvement["gap_type"] == "source_coverage"
    assert improvement["status"] == "improved"
    assert improvement["resolved_gap"] is True
    assert "original_gap_resolved" in improvement["improved_signals"]
    assert "target_source_type_collected" in improvement["improved_signals"]


def test_branch_improvement_assessment_tracks_success_criterion_resolution():
    builder = BranchCoverageStateBuilder(
        CoverageReviewer(source_gap_advisor=FakeSourceGapAdvisor()),
    )
    root = {
        "id": "collect_acme_product",
        "competitor": "Acme",
        "dimension_id": "product",
        "dimension_name": "Product",
        "analysis_dimension_id": "product",
        "success_criteria": [
            {
                "id": "feature_signal",
                "description": "Identify public feature capabilities.",
            },
            {
                "id": "security_signal",
                "description": "Identify security compliance controls.",
            },
        ],
    }
    child = {
        "id": "collect_acme_product_d1_1",
        "parent_id": root["id"],
        "competitor": "Acme",
        "dimension_id": "product",
        "dimension_name": "Product",
        "analysis_dimension_id": "product",
        "generated_from_gap": "missing_success_criterion",
        "triggered_by_gap_type": "success_criterion",
        "triggered_by_gap_code": "missing_success_criterion",
        "triggered_by_coverage_assessment_id": "coverage_collect_acme_product",
        "triggered_by_criterion_id": "security_signal",
        "success_criteria": [root["success_criteria"][1]],
    }
    evidence_items = [
        {
            "id": "ev_root",
            "branch_id": root["id"],
            "url": "https://acme.example/features",
            "source_type": "official_site",
            "excerpt": "Acme public feature capabilities are described.",
        },
        {
            "id": "ev_child",
            "branch_id": child["id"],
            "url": "https://acme.example/security",
            "source_type": "docs",
            "excerpt": "Acme security compliance controls are documented.",
        },
    ]
    evidence_reviews = [
        {
            "id": "ev_review_collect_acme_product",
            "branch_id": root["id"],
            "accepted_evidence_ids": ["ev_root"],
            "rejected_evidence_ids": [],
        },
        {
            "id": "ev_review_collect_acme_product_d1_1",
            "branch_id": child["id"],
            "accepted_evidence_ids": ["ev_child"],
            "rejected_evidence_ids": [],
        },
    ]
    coverage_assessments = [
        {
            "id": "coverage_collect_acme_product",
            "branch_id": root["id"],
            "accepted_evidence_ids": ["ev_root"],
            "rejected_evidence_ids": [],
            "quality_stability": {
                "status": "stable",
                "accepted_count": 1,
                "rejected_count": 0,
                "rejected_ratio": 0.0,
            },
            "source_metrics": {
                "accepted_evidence_count": 1,
                "independent_source_count": 1,
                "unique_canonical_url_count": 1,
                "unique_domain_count": 1,
                "primary_source_count": 0,
            },
            "satisfied_criteria": [root["success_criteria"][0]],
            "partial_criteria": [],
            "missing_criteria": [root["success_criteria"][1]],
            "covered_questions": [],
            "missing_questions": [],
        },
        {
            "id": "coverage_collect_acme_product_d1_1",
            "branch_id": child["id"],
            "accepted_evidence_ids": ["ev_child"],
            "rejected_evidence_ids": [],
            "quality_stability": {
                "status": "stable",
                "accepted_count": 1,
                "rejected_count": 0,
                "rejected_ratio": 0.0,
            },
            "source_metrics": {
                "accepted_evidence_count": 1,
                "independent_source_count": 1,
                "unique_canonical_url_count": 1,
                "unique_domain_count": 1,
                "primary_source_count": 0,
            },
            "satisfied_criteria": [root["success_criteria"][1]],
            "partial_criteria": [],
            "missing_criteria": [],
            "covered_questions": [],
            "missing_questions": [],
        },
    ]

    states = builder.build(
        [root, child],
        evidence_reviews,
        evidence_items,
        coverage_assessments,
    )

    summary = states[0]
    improvement = summary["improvement_assessments"][0]
    resolved_gap = summary["coverage_gaps"][0]
    assert resolved_gap["gap_type"] == "success_criterion"
    assert resolved_gap["status"] == "resolved"
    assert improvement["gap_type"] == "success_criterion"
    assert improvement["criterion_id"] == "security_signal"
    assert improvement["status"] == "improved"
    assert improvement["resolved_gap"] is True
    assert improvement["deltas"]["missing_criteria_count_delta"] == -1
    assert "missing_criteria_count_decreased" in improvement["improved_signals"]


def test_unresolved_llm_source_gap_does_not_block_branch_coverage():
    collector = FakeEvidenceCollector()
    source_gap_advisor = FakeSourceGapAdvisor()
    agent = CollectionAgent(
        evidence_collector=collector,
        coverage_reviewer=CoverageReviewer(source_gap_advisor=source_gap_advisor),
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

    assert root_coverage["source_gap_review"]["status"] == "completed"
    assert root_coverage["source_type_gaps"][0]["code"] == "needs_pricing_page_source"
    assert root_coverage["source_type_gaps"][0]["gap_type"] == "source_coverage"
    assert root_coverage["source_type_gaps"][0]["target_source_types"] == ["pricing_page"]
    assert root_coverage["source_type_gaps"][0]["blocking"] is False
    assert root_coverage["source_coverage_gaps"] == root_coverage["source_type_gaps"]
    assert child_branches == []
    assert pricing_summary["status"] == "ready_for_analysis"
    assert pricing_summary["open_gap_codes"] == ["needs_pricing_page_source"]
    assert pricing_summary["blocked_gap_codes"] == []


def test_source_gap_advisor_failure_does_not_open_rule_gap():
    collector = FakeEvidenceCollector()
    source_gap_advisor = FakeSourceGapAdvisor(fail=True)
    agent = CollectionAgent(
        evidence_collector=collector,
        coverage_reviewer=CoverageReviewer(source_gap_advisor=source_gap_advisor),
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
    root_coverage = next(
        assessment
        for assessment in result["coverage_assessments"]
        if assessment["branch_id"] == pricing_root["id"]
    )

    assert source_gap_advisor.calls
    assert root_coverage["source_gap_review"]["status"] == "failed"
    assert root_coverage["source_gap_review"]["no_rule_fallback"] is True
    assert root_coverage["source_type_gaps"] == []
    assert root_coverage["source_coverage_gaps"] == []
    assert child_branches == []
