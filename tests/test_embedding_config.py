import os
import unittest
from unittest.mock import patch

from rivalens.research.config.config import Config
from rivalens.research.config.variables.default import DEFAULT_CONFIG
from rivalens.research.memory.embeddings import (
    Memory,
    _openai_embedding_api_base,
    _openai_embedding_api_key,
)
from rivalens.research.utils.costs import estimate_embedding_cost


class EmbeddingConfigTest(unittest.TestCase):
    def test_default_embedding_model_is_text_embedding_v4(self):
        self.assertEqual(
            DEFAULT_CONFIG["EMBEDDING"],
            "openai:text-embedding-v4",
        )

        with patch.dict(os.environ, {}, clear=True):
            cfg = Config()

        self.assertEqual(cfg.embedding_provider, "openai")
        self.assertEqual(cfg.embedding_model, "text-embedding-v4")

    def test_embedding_credentials_prefer_dedicated_env(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "shared-key",
                "OPENAI_BASE_URL": "https://shared.example/v1",
                "OPENAI_EMBEDDING_API_KEY": "embedding-key",
                "OPENAI_EMBEDDING_BASE_URL": "https://embedding.example/v1",
            },
            clear=True,
        ):
            self.assertEqual(_openai_embedding_api_key(), "embedding-key")
            self.assertEqual(
                _openai_embedding_api_base(),
                "https://embedding.example/v1",
            )

    def test_embedding_credentials_fall_back_to_shared_openai_env(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "shared-key",
                "OPENAI_BASE_URL": "https://shared.example/v1",
            },
            clear=True,
        ):
            self.assertEqual(_openai_embedding_api_key(), "shared-key")
            self.assertEqual(
                _openai_embedding_api_base(),
                "https://shared.example/v1",
            )

    def test_openai_embedding_model_overrides_deprecated_provider_path(self):
        with patch.dict(
            os.environ,
            {
                "EMBEDDING_PROVIDER": "openai",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-v4",
            },
            clear=True,
        ):
            cfg = Config()

        self.assertEqual(cfg.embedding_provider, "openai")
        self.assertEqual(cfg.embedding_model, "text-embedding-v4")

    def test_openai_embedding_disables_internal_context_length_check(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            embeddings = Memory("openai", "text-embedding-v4").get_embeddings()

        self.assertEqual(embeddings.model, "text-embedding-v4")
        self.assertFalse(embeddings.check_embedding_ctx_length)

    def test_explicit_embedding_context_length_check_is_preserved(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            embeddings = Memory(
                "openai",
                "text-embedding-v4",
                check_embedding_ctx_length=True,
            ).get_embeddings()

        self.assertTrue(embeddings.check_embedding_ctx_length)

    def test_embedding_cost_estimate_supports_text_embedding_v4(self):
        cost = estimate_embedding_cost(
            model="text-embedding-v4",
            docs=["淘宝是综合电商平台。"],
        )

        self.assertGreater(cost, 0)


if __name__ == "__main__":
    unittest.main()
