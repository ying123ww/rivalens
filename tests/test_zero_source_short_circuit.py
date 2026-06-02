import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from rivalens.research.skills.researcher import ResearchConductor


class ZeroSourceShortCircuitTest(unittest.IsolatedAsyncioTestCase):
    async def test_scrape_data_by_urls_skips_browser_when_no_sources(self):
        scraper_manager = SimpleNamespace(browse_urls=AsyncMock())
        researcher = SimpleNamespace(
            verbose=False,
            websocket=None,
            scraper_manager=scraper_manager,
            vector_store=None,
        )
        conductor = ResearchConductor(researcher)
        conductor._search_relevant_source_urls = AsyncMock(return_value=([], []))

        result = await conductor._scrape_data_by_urls("钉钉 SaaS 定价")

        self.assertEqual(result, [])
        scraper_manager.browse_urls.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
