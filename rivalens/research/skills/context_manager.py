"""Context manager skill for Rivalens.

This module provides the ContextManager class that handles context
retrieval, compression, and similarity matching for research queries.
"""

from ..actions.utils import stream_output
from ..context.compression import (
    ContextCompressor,
    VectorstoreCompressor,
)


class ContextManager:
    """Manages context retrieval and compression for research.

    This class handles finding similar content based on queries,
    managing context from various sources, and compressing content
    for efficient processing.

    Attributes:
        researcher: The parent ResearchEngine instance.
    """

    def __init__(self, researcher):
        """Initialize the ContextManager.

        Args:
            researcher: The ResearchEngine instance that owns this manager.
        """
        self.researcher = researcher

    async def get_similar_content_by_query(self, query: str, pages: list) -> str:
        """Get similar content from pages based on the query.

        Args:
            query: The search query to find similar content for.
            pages: List of page content to search through.

        Returns:
            Compressed context string of relevant content.
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "fetching_query_content",
                f"📚 Getting relevant content based on query: {query}...",
                self.researcher.websocket,
            )

        context_compressor = ContextCompressor(
            documents=pages,
            embeddings=self.researcher.memory.get_embeddings(),
            prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )
        return await context_compressor.async_get_context(
            query=query, max_results=10, cost_callback=self.researcher.add_costs
        )

    async def get_similar_content_by_query_with_vectorstore(self, query: str, filter: dict | None) -> str:
        """Get similar content from vectorstore based on the query.

        Args:
            query: The search query to find similar content for.
            filter: Optional filter dictionary for vectorstore queries.

        Returns:
            Compressed context string of relevant content from vectorstore.
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "fetching_query_format",
                f" Getting relevant content based on query: {query}...",
                self.researcher.websocket,
                )
        vectorstore_compressor = VectorstoreCompressor(
            self.researcher.vector_store, filter=filter, prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )
        return await vectorstore_compressor.async_get_context(query=query, max_results=8)
