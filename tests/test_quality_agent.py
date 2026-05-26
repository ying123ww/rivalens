import asyncio
import unittest

from rivalens.agents.quality import QualityAgent


class QualityAgentTraceabilityTest(unittest.TestCase):
    def run_quality(self, state):
        return asyncio.run(QualityAgent().run({"messages": [], **state}))

    def test_rejects_missing_evidence_records(self):
        result = self.run_quality(
            {
                "analysis_claims": [
                    {
                        "id": "claim_1",
                        "dimension": "pricing_model",
                        "claim": "Acme has public pricing.",
                        "competitors": ["Acme"],
                        "evidence_ids": ["ev_missing"],
                    }
                ],
                "evidence_items": [],
            }
        )

        self.assertFalse(result["messages"][-1]["payload"]["accepted"])
        self.assertEqual(result["quality_findings"][0]["severity"], "high")
        self.assertIn("do not exist", result["quality_findings"][0]["message"])

    def test_rejects_evidence_without_source_url(self):
        result = self.run_quality(
            {
                "analysis_claims": [
                    {
                        "id": "claim_1",
                        "dimension": "pricing_model",
                        "claim": "Acme has public pricing.",
                        "competitors": ["Acme"],
                        "evidence_ids": ["ev_1"],
                    }
                ],
                "evidence_items": [
                    {
                        "id": "ev_1",
                        "competitor": "Acme",
                        "dimension_id": "pricing_model",
                        "url": "",
                    }
                ],
            }
        )

        self.assertFalse(result["messages"][-1]["payload"]["accepted"])
        self.assertTrue(
            any(
                "without source URLs" in finding["message"]
                for finding in result["quality_findings"]
            )
        )

    def test_accepts_existing_url_backed_evidence(self):
        result = self.run_quality(
            {
                "analysis_claims": [
                    {
                        "id": "claim_1",
                        "dimension": "pricing_model",
                        "claim": "Acme has public pricing.",
                        "competitors": ["Acme"],
                        "evidence_ids": ["ev_1"],
                    }
                ],
                "evidence_items": [
                    {
                        "id": "ev_1",
                        "competitor": "Acme",
                        "dimension_id": "pricing_model",
                        "url": "https://acme.example/pricing",
                    }
                ],
            }
        )

        self.assertTrue(result["messages"][-1]["payload"]["accepted"])
        self.assertEqual(result["quality_findings"], [])


if __name__ == "__main__":
    unittest.main()
