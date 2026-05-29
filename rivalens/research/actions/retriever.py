"""Retriever factory and utilities for Rivalens.

This module provides functions to instantiate and manage various
search retriever implementations.
"""


def get_retriever(retriever: str):
    """Get a retriever class by name.

    Args:
        retriever: The name of the retriever to get (e.g., 'google', 'tavily', 'duckduckgo').

    Returns:
        The retriever class if found, None otherwise.

    Supported retrievers:
        - google: Google Custom Search
        - searx: SearX search engine
        - searchapi: SearchAPI service
        - serpapi: SerpAPI service
        - serper: Serper API
        - duckduckgo: DuckDuckGo search
        - bing: Bing search
        - arxiv: arXiv academic search
        - tavily: Tavily search API
        - exa: Exa search
        - semantic_scholar: Semantic Scholar academic search
        - pubmed_central: PubMed Central medical literature
        - custom: Custom user-defined retriever
        - mcp: Model Context Protocol retriever
        - xquik: Xquik X/Twitter search
    """
    match retriever:
        case "google":
            from rivalens.research.retrievers import GoogleSearch

            return GoogleSearch
        case "searx":
            from rivalens.research.retrievers import SearxSearch

            return SearxSearch
        case "searchapi":
            from rivalens.research.retrievers import SearchApiSearch

            return SearchApiSearch
        case "serpapi":
            from rivalens.research.retrievers import SerpApiSearch

            return SerpApiSearch
        case "serper":
            from rivalens.research.retrievers import SerperSearch

            return SerperSearch
        case "duckduckgo":
            from rivalens.research.retrievers import Duckduckgo

            return Duckduckgo
        case "bing":
            from rivalens.research.retrievers import BingSearch

            return BingSearch
        case "bocha":
            from rivalens.research.retrievers import BoChaSearch

            return BoChaSearch
        case "arxiv":
            from rivalens.research.retrievers import ArxivSearch

            return ArxivSearch
        case "tavily":
            from rivalens.research.retrievers import TavilySearch

            return TavilySearch
        case "unifuncs_deepsearch":
            from rivalens.research.retrievers import UniFuncsDeepSearch

            return UniFuncsDeepSearch
        case "exa":
            from rivalens.research.retrievers import ExaSearch

            return ExaSearch
        case "semantic_scholar":
            from rivalens.research.retrievers import SemanticScholarSearch

            return SemanticScholarSearch
        case "pubmed_central":
            from rivalens.research.retrievers import PubMedCentralSearch

            return PubMedCentralSearch
        case "custom":
            from rivalens.research.retrievers import CustomRetriever

            return CustomRetriever
        case "mcp":
            from rivalens.research.retrievers import MCPRetriever

            return MCPRetriever
        case "xquik":
            from rivalens.research.retrievers import XquikSearch

            return XquikSearch

        case _:
            return None


def get_retrievers(headers: dict[str, str], cfg):
    """
    Determine which retriever(s) to use based on headers, config, or default.

    Args:
        headers (dict): The headers dictionary
        cfg: The configuration object

    Returns:
        list: A list of retriever classes to be used for searching.
    """
    # Check headers first for multiple retrievers
    if headers.get("retrievers"):
        retrievers = headers.get("retrievers").split(",")
    # If not found, check headers for a single retriever
    elif headers.get("retriever"):
        retrievers = [headers.get("retriever")]
    # If not in headers, check config for multiple retrievers
    elif cfg.retrievers:
        # Handle both list and string formats for config retrievers
        if isinstance(cfg.retrievers, str):
            retrievers = cfg.retrievers.split(",")
        else:
            retrievers = cfg.retrievers
        # Strip whitespace from each retriever name
        retrievers = [r.strip() for r in retrievers]
    # If not found, check config for a single retriever
    elif cfg.retriever:
        retrievers = [cfg.retriever]
    # If still not set, use default retriever
    else:
        retrievers = [get_default_retriever().__name__]

    # Convert retriever names to actual retriever classes
    # Use get_default_retriever() as a fallback for any invalid retriever names
    retriever_classes = [get_retriever(r) or get_default_retriever() for r in retrievers]
    
    return retriever_classes


def get_default_retriever():
    """Get the default retriever class.

    Returns:
        The TavilySearch retriever class as the default search provider.
    """
    from rivalens.research.retrievers import TavilySearch

    return TavilySearch
