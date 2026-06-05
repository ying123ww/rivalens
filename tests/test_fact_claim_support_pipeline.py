"""Focused tests for the KnowledgeFact -> AnalysisClaim -> support gate path."""

import asyncio

from rivalens.agents.analysis import AnalysisAgent
from rivalens.agents.claim_support import ClaimSupportReviewer
from rivalens.agents.knowledge_structuring import KnowledgeStructuringAgent
from rivalens.agents.writing import ReportWriterAgent


class FakeFactExtractor:
    def is_configured(self):
        return True

    async def extract(self, evidence_items):
        return (
            [
                {
                    "competitor": "Acme",
                    "analysis_dimension_id": "pricing_model",
                    "fact_type": "pricing_signal",
                    "subject": "Acme pricing page",
                    "predicate": "publishes",
                    "object": "public Pro and Enterprise pricing tiers",
                    "statement": "Acme pricing page publishes public Pro and Enterprise pricing tiers.",
                    "evidence_ids": ["ev_1"],
                    "confidence": 0.92,
                }
            ],
            {
                "llm_prompt": "fake_prompt",
                "llm_provider": "fake",
                "llm_model": "fake-model",
                "llm_cost": 0.0,
            },
        )


class FakeBroadPricingExtractor:
    def is_configured(self):
        return True

    async def extract(self, evidence_items):
        return (
            [
                {
                    "competitor": "Acme",
                    "analysis_dimension_id": "pricing_model",
                    "fact_type": "pricing_signal",
                    "subject": "Acme pricing page",
                    "predicate": "publishes",
                    "object": "multiple pricing signals across free, Pro, Enterprise, usage, and annual billing",
                    "statement": "Acme pricing page publishes multiple pricing signals.",
                    "evidence_ids": ["ev_pricing"],
                    "confidence": 0.92,
                }
            ],
            {
                "llm_prompt": "fake_prompt",
                "llm_provider": "fake",
                "llm_model": "fake-model",
                "llm_cost": 0.0,
            },
        )


def _combined_pricing_evidence():
    return [
        {
            "id": "ev_pricing",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": (
                "Free plan available. Pro is $20/user/month. "
                "Enterprise is quote-only. Usage-based billing is available. "
                "Annual billing gets 20% off."
            ),
            "url": "https://acme.example/pricing",
            "confidence": 0.9,
        }
    ]


def test_knowledge_structuring_uses_llm_extractor_when_configured():
    agent = KnowledgeStructuringAgent(fact_extractor=FakeFactExtractor())
    evidence = [
        {
            "id": "ev_1",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
            "url": "https://acme.example/pricing",
            "confidence": 0.8,
        }
    ]

    facts, metadata = asyncio.run(agent._build_knowledge_facts_with_llm(evidence))

    assert metadata["source"] == "llm"
    assert metadata["llm_fact_count"] == 1
    assert facts[0]["fact_type"] == "pricing_signal"
    assert facts[0]["subject"] == "Acme pricing page"
    assert facts[0]["evidence_ids"] == ["ev_1"]
    assert facts[0]["normalized_key"]


def test_knowledge_structuring_splits_pricing_evidence_into_atom_facts():
    agent = KnowledgeStructuringAgent()

    facts = agent._build_knowledge_facts(_combined_pricing_evidence())

    atom_kinds = sorted(
        (fact.get("qualifiers", {}) or {}).get("pricing_atom_kind", "")
        for fact in facts
    )
    assert atom_kinds == sorted(
        [
            "free_tier",
            "published_plan_price",
            "quote_only",
            "usage_based_billing",
            "annual_discount",
        ]
    )
    assert len(facts) == 5
    assert {
        fact["predicate"]
        for fact in facts
    } == {
        "exists",
        "publishes_price",
        "requires_quote",
        "uses_billing_model",
        "offers_discount",
    }
    assert all(fact["evidence_ids"] == ["ev_pricing"] for fact in facts)


def test_llm_broad_pricing_fact_is_split_before_analysis():
    agent = KnowledgeStructuringAgent(fact_extractor=FakeBroadPricingExtractor())

    facts, metadata = asyncio.run(
        agent._build_knowledge_facts_with_llm(_combined_pricing_evidence())
    )

    assert metadata["source"] == "llm"
    assert metadata["atomization_too_broad_count"] == 1
    assert metadata["atomization_split_count"] == 5
    assert sorted(
        (fact.get("qualifiers", {}) or {}).get("pricing_atom_kind", "")
        for fact in facts
    ) == sorted(
        [
            "free_tier",
            "published_plan_price",
            "quote_only",
            "usage_based_billing",
            "annual_discount",
        ]
    )


def test_llm_atomic_pricing_fact_is_not_duplicated_by_splitter():
    evidence = [
        {
            "id": "ev_price",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Pro is $20/user/month.",
            "url": "https://acme.example/pricing",
            "confidence": 0.9,
        }
    ]
    raw_facts = [
        {
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "fact_type": "pricing_signal",
            "subject": "Pro plan",
            "predicate": "publishes_price",
            "object": "Pro pricing is $20/user/month",
            "statement": "Pro plan publishes pricing at $20/user/month.",
            "evidence_ids": ["ev_price"],
            "confidence": 0.9,
        }
    ]

    facts = KnowledgeStructuringAgent()._normalize_llm_facts(raw_facts, evidence)

    assert len(facts) == 1
    assert facts[0]["predicate"] == "publishes_price"
    assert (facts[0].get("qualifiers", {}) or {}).get("pricing_atom_kind") == "published_plan_price"


def test_knowledge_structuring_builds_and_merges_fact_atoms():
    agent = KnowledgeStructuringAgent()
    evidence = [
        {
            "id": "ev_1",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
            "url": "https://acme.example/pricing",
            "confidence": 0.8,
        },
        {
            "id": "ev_2",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "dimension_name": "Pricing Model",
            "source_type": "pricing_page",
            "title": "Acme Pricing",
            "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
            "url": "https://acme.example/pricing?ref=copy",
            "confidence": 0.9,
        },
    ]

    facts = agent._build_knowledge_facts(evidence)

    assert len(facts) == 1
    fact = facts[0]
    assert fact["fact_type"] == "pricing_signal"
    assert fact["subject"]
    assert fact["predicate"] == "publishes"
    assert fact["object"]
    assert fact["normalized_key"]
    assert fact["evidence_ids"] == ["ev_1", "ev_2"]


def test_analysis_groups_fact_atoms_into_one_traceable_claim():
    agent = AnalysisAgent()
    facts = [
        {
            "id": "fact_1",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "fact_type": "pricing_signal",
            "subject": "Acme pricing tiers",
            "predicate": "publishes",
            "normalized_key": "acme|pricing_model|pricing_signal|publishes|pricing_tiers",
            "object": "Acme publishes public Pro and Enterprise pricing tiers.",
            "statement": "Acme pricing source publishes public Pro and Enterprise pricing tiers.",
            "evidence_ids": ["ev_1"],
            "confidence": 0.8,
        },
        {
            "id": "fact_2",
            "competitor": "Acme",
            "analysis_dimension_id": "pricing_model",
            "fact_type": "pricing_signal",
            "subject": "Acme pricing tiers",
            "predicate": "publishes",
            "normalized_key": "acme|pricing_model|pricing_signal|publishes|pricing_tiers",
            "object": "Acme shows per-user pricing for paid tiers.",
            "statement": "Acme pricing source publishes per-user pricing for paid tiers.",
            "evidence_ids": ["ev_2"],
            "confidence": 0.9,
        },
    ]
    state = {
        "analysis_dimensions": [
            {"id": "pricing_model", "name": "Pricing Model"},
        ],
    }

    claims = agent._claims_from_knowledge_facts(state, facts)

    assert len(claims) == 1
    claim = claims[0]
    assert claim["claim_source"] == "knowledge_fact_group"
    assert claim["claim_type"] == "pricing_strategy"
    assert claim["claim_risk_level"] == "high"
    assert claim["knowledge_fact_ids"] == ["fact_1", "fact_2"]
    assert claim["evidence_ids"] == ["ev_1", "ev_2"]
    assert "public evidence" in claim["claim"]


def test_analysis_keeps_distinct_pricing_atoms_as_distinct_claims():
    facts = KnowledgeStructuringAgent()._build_knowledge_facts(
        _combined_pricing_evidence()
    )
    state = {
        "analysis_dimensions": [
            {"id": "pricing_model", "name": "Pricing Model"},
        ],
    }

    claims = AnalysisAgent()._claims_from_knowledge_facts(state, facts)

    assert len(claims) == 5
    assert all(len(claim["knowledge_fact_ids"]) == 1 for claim in claims)
    assert len({claim["normalized_key"] for claim in claims}) == 5
    assert not any("multiple pricing signals" in claim["claim"] for claim in claims)


def test_claim_support_accepts_supported_fact_bound_claim():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_1",
                "analysis_dimension_id": "pricing_model",
                "knowledge_fact_ids": ["fact_1"],
                "claim": "Acme Pricing Model: public evidence pricing signals Acme publishes public Pro and Enterprise pricing tiers.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_1"],
                "confidence": 0.8,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "object": "Acme publishes public Pro and Enterprise pricing tiers.",
                "statement": "Acme pricing source publishes public Pro and Enterprise pricing tiers.",
                "evidence_ids": ["ev_1"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "supported"
    assert review["recommended_action"] == "accept"
    assert review["claim_risk_level"] == "high"
    assert review["required_follow_up_tasks"] == []
    assert "verification_task_queue" not in result


def test_claim_support_flags_overclaim_and_writer_filters_it():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_1",
                "analysis_dimension_id": "pricing_model",
                "knowledge_fact_ids": ["fact_1"],
                "claim": "Acme is the leading pricing platform with the strongest enterprise advantage.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_1"],
                "confidence": 0.8,
            }
        ],
        "knowledge_facts": [
            {
                "id": "fact_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "object": "Acme publishes public Pro and Enterprise pricing tiers.",
                "statement": "Acme pricing source publishes public Pro and Enterprise pricing tiers.",
                "evidence_ids": ["ev_1"],
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["support_status"] == "weak"
    assert review["recommended_action"] == "revise"
    assert review["suggested_revision"]
    assert ReportWriterAgent()._supported_claims(
        state["analysis_claims"],
        result["claim_support_reviews"],
    ) == []


def test_high_risk_claim_without_knowledge_fact_requires_evidence_gap():
    reviewer = ClaimSupportReviewer()
    state = {
        "analysis_claims": [
            {
                "id": "claim_1",
                "analysis_dimension_id": "pricing_model",
                "claim_type": "pricing_strategy",
                "claim_risk_level": "high",
                "claim": "Acme pricing is cheaper than Beta for enterprise teams.",
                "competitors": ["Acme"],
                "evidence_ids": ["ev_1"],
                "confidence": 0.8,
            }
        ],
        "evidence_items": [
            {
                "id": "ev_1",
                "competitor": "Acme",
                "analysis_dimension_id": "pricing_model",
                "title": "Acme Pricing",
                "excerpt": "Acme publishes public Pro and Enterprise pricing tiers.",
                "url": "https://acme.example/pricing",
            }
        ],
    }

    result = reviewer.review(state)
    review = result["claim_support_reviews"][0]

    assert review["claim_risk_level"] == "high"
    assert review["support_status"] == "unverifiable"
    assert review["recommended_action"] == "evidence_gap"
