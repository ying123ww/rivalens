"""OpenAI embedding provider management for Rivalens."""

import os
from typing import Any

OPENAI_EMBEDDING_MODEL = os.environ.get(
    "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
)


def _openai_embedding_api_key(default: str | None = None) -> str | None:
    return (
        os.getenv("OPENAI_EMBEDDING_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or default
    )


def _openai_embedding_api_base(default: str | None = None) -> str | None:
    return (
        os.getenv("OPENAI_EMBEDDING_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or default
    )


_SUPPORTED_PROVIDERS = {"openai"}


class Memory:
    """Manages OpenAI embeddings for document similarity and retrieval.

    Attributes:
        _embeddings: The underlying LangChain embeddings instance.

    Example:
        ```python
        memory = Memory("openai", "text-embedding-3-small")
        embeddings = memory.get_embeddings()
        ```
    """

    def __init__(self, embedding_provider: str, model: str, **embedding_kwargs: Any):
        """Initialize the Memory with a specific embedding provider.

        Args:
            embedding_provider: The name of the embedding provider to use.
                Only ``openai`` is supported.
            model: The model name/ID to use for embeddings.
            **embedding_kwargs: Additional keyword arguments passed to the
                embedding provider's constructor.

        Raises:
            ValueError: If the embedding provider is not supported.
        """
        _embeddings = None
        match embedding_provider:
            case "openai":
                from langchain_openai import OpenAIEmbeddings

                # Prefer embedding-specific credentials, then fall back to shared OpenAI settings.
                embedding_api_key = _openai_embedding_api_key()
                embedding_api_base = _openai_embedding_api_base()
                if "openai_api_key" not in embedding_kwargs and embedding_api_key:
                    embedding_kwargs["openai_api_key"] = embedding_api_key
                if "openai_api_base" not in embedding_kwargs and embedding_api_base:
                    embedding_kwargs["openai_api_base"] = embedding_api_base
                embedding_kwargs.setdefault("check_embedding_ctx_length", False)
                embedding_kwargs.setdefault("chunk_size", 10)

                _embeddings = OpenAIEmbeddings(model=model, **embedding_kwargs)
            case _:
                supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
                raise ValueError(
                    f"Unsupported embedding provider {embedding_provider}. "
                    f"Supported embedding providers are: {supported}"
                )

        self._embeddings = _embeddings

    def get_embeddings(self):
        """Get the configured embeddings instance.

        Returns:
            The LangChain embeddings instance configured for this Memory.
        """
        return self._embeddings
