"""Rivalens agent module.

This module provides the main ResearchEngine class that orchestrates
autonomous research and report generation using LLMs and web search.
"""

import json
import os
from typing import Any

from .actions import (
    choose_agent,
    get_retrievers,
    get_search_results,
)
from .config import Config
from .memory import Memory
from .prompts import get_prompt_family
from .trace_context import (
    RIVALENS_EXCLUDED_CANONICAL_URLS_KEY,
    RIVALENS_SEARCH_QUERIES_KEY,
    RIVALENS_TRACE_CONTEXT_KEY,
)
from .skills.browser import BrowserManager
from .skills.context_manager import ContextManager
from .skills.researcher import ResearchConductor
from .skills.writer import ReportGenerator
from .utils.enum import ReportSource, ReportType, Tone
from .utils.llm import create_chat_completion
from .vector_store import VectorStoreWrapper


class ResearchEngine:
    """Main Rivalens agent class.

    This class orchestrates the entire research process including
    web searching, content scraping, context management, and
    report generation using LLMs.

    Attributes:
        query: The research query or question.
        report_type: Type of report to generate.
        cfg: Configuration object.
        context: Accumulated research context.
        research_costs: Total accumulated API costs.
        step_costs: Per-step cost breakdown dictionary.
    """

    def __init__(
        self,
        query: str,
        report_type: str = ReportType.ResearchReport.value,
        report_format: str = "markdown",
        report_source: str = ReportSource.Web.value,
        tone: Tone = Tone.Objective,
        source_urls: list[str] | None = None,
        document_urls: list[str] | None = None,
        complement_source_urls: bool = False,
        query_domains: list[str] | None = None,
        documents=None,
        vector_store=None,
        vector_store_filter=None,
        config_path=None,
        websocket=None,
        agent=None,
        role=None,
        visited_urls: set | None = None,
        verbose: bool = True,
        context=None,
        headers: dict | None = None,
        log_handler=None,
        prompt_family: str | None = None,
        mcp_configs: list[dict] | None = None,
        mcp_strategy: str | None = None,
        **kwargs
    ):
        """
        Initialize a Rivalens instance.
        
        Args:
            query (str): The research query or question.
            report_type (str): Type of report to generate.
            report_format (str): Format of the report (markdown, pdf, etc).
            report_source (str): Source of information for the report (web, local, etc).
            tone (Tone): Tone of the report.
            source_urls (list[str], optional): List of specific URLs to use as sources.
            document_urls (list[str], optional): List of document URLs to use as sources.
            complement_source_urls (bool): Whether to complement source URLs with web search.
            query_domains (list[str], optional): List of domains to restrict search to.
            documents: Document objects for LangChain integration.
            vector_store: Vector store for document retrieval.
            vector_store_filter: Filter for vector store queries.
            config_path: Path to configuration file.
            websocket: WebSocket for streaming output.
            agent: Pre-defined agent type.
            role: Pre-defined agent role.
            visited_urls: Set of already visited URLs.
            verbose (bool): Whether to output verbose logs.
            context: Pre-loaded research context.
            headers (dict, optional): Additional headers for requests and configuration.
            log_handler: Handler for logging events.
            prompt_family: Family of prompts to use.
            mcp_configs (list[dict], optional): List of MCP server configurations.
                Each dictionary can contain:
                - name (str): Name of the MCP server
                - command (str): Command to start the server
                - args (list[str]): Arguments for the server command
                - tool_name (str): Specific tool to use on the MCP server
                - env (dict): Environment variables for the server
                - connection_url (str): URL for WebSocket or HTTP connection
                - connection_type (str): Connection type (stdio, websocket, http)
                - connection_token (str): Authentication token for remote connections
                
                Example:
                ```python
                mcp_configs=[{
                    "command": "python",
                    "args": ["my_mcp_server.py"],
                    "name": "search"
                }]
                ```
            mcp_strategy (str, optional): MCP execution strategy. Options:
                - "fast" (default): Run MCP once with original query for best performance
                - "deep": Run MCP for all sub-queries for maximum thoroughness  
                - "disabled": Skip MCP entirely, use only web retrievers
        """
        self.rivalens_search_queries = kwargs.pop(RIVALENS_SEARCH_QUERIES_KEY, [])
        self.rivalens_trace_context = kwargs.pop(RIVALENS_TRACE_CONTEXT_KEY, {})
        self.rivalens_excluded_canonical_urls = kwargs.pop(
            RIVALENS_EXCLUDED_CANONICAL_URLS_KEY,
            [],
        )
        self.kwargs = kwargs
        self.query = query
        self.report_type = report_type
        self.cfg = Config(config_path)
        self.cfg.set_verbose(verbose)
        self.report_source = report_source if report_source else getattr(self.cfg, 'report_source', None)
        self.report_format = report_format
        self.tone = tone if isinstance(tone, Tone) else Tone.Objective
        self.source_urls = source_urls
        self.document_urls = document_urls
        self.complement_source_urls = complement_source_urls
        self.query_domains = query_domains or []
        self.research_sources = []  # The list of scraped sources including title, content and images
        self.research_images = []  # The list of selected research images
        self.documents = documents
        self.vector_store = VectorStoreWrapper(vector_store) if vector_store else None
        self.vector_store_filter = vector_store_filter
        self.websocket = websocket
        self.agent = agent
        self.role = role
        self.visited_urls = visited_urls or set()
        self.verbose = verbose
        self.context = context or []
        self.headers = headers or {}
        self.research_costs = 0.0
        self.step_costs: dict[str, float] = {}
        self._current_step: str = "general"
        self.log_handler = log_handler
        self.prompt_family = get_prompt_family(prompt_family or self.cfg.prompt_family, self.cfg)
        
        # Process MCP configurations if provided
        self.mcp_configs = mcp_configs
        if mcp_configs:
            self._process_mcp_configs(mcp_configs)
        
        self.retrievers = get_retrievers(self.headers, self.cfg)
        self.memory = Memory(
            self.cfg.embedding_provider, self.cfg.embedding_model, **self.cfg.embedding_kwargs
        )
        
        # Set default encoding to utf-8
        self.encoding = kwargs.get('encoding', 'utf-8')
        self.kwargs.pop('encoding', None)  # Remove encoding from kwargs to avoid passing it to LLM calls

        # Initialize components
        self.research_conductor: ResearchConductor = ResearchConductor(self)
        self.report_generator: ReportGenerator = ReportGenerator(self)
        self.context_manager: ContextManager = ContextManager(self)
        self.scraper_manager: BrowserManager = BrowserManager(self)

        self._research_id: str = ""  # Unique ID for this research session

        self.mcp_strategy = self._resolve_mcp_strategy(mcp_strategy)
    
    def _generate_research_id(self) -> str:
        """Generate a unique research ID for this session.
        
        Returns:
            A unique string identifier for this research session.
        """
        if not self._research_id:
            import hashlib
            import time
            # Create unique ID from query + timestamp
            unique_str = f"{self.query}_{time.time()}"
            self._research_id = f"research_{hashlib.md5(unique_str.encode()).hexdigest()[:12]}"
        return self._research_id

    def _resolve_mcp_strategy(self, mcp_strategy: str | None) -> str:
        """
        Resolve MCP strategy from parameters, config, or default.
        
        Priority:
        1. Parameter mcp_strategy
        2. Config MCP_STRATEGY
        3. Default "fast"
        
        Args:
            mcp_strategy: Strategy parameter.
            
        Returns:
            str: Resolved strategy ("fast", "deep", or "disabled")
        """
        if mcp_strategy is not None:
            if mcp_strategy in ["fast", "deep", "disabled"]:
                return mcp_strategy
            import logging
            logging.getLogger(__name__).warning(f"Invalid mcp_strategy '{mcp_strategy}', defaulting to 'fast'")
            return "fast"
        
        if hasattr(self.cfg, 'mcp_strategy'):
            config_strategy = self.cfg.mcp_strategy
            if config_strategy in ["fast", "deep", "disabled"]:
                return config_strategy
            
        return "fast"

    def _process_mcp_configs(self, mcp_configs: list[dict]) -> None:
        """
        Process MCP configurations from a list of configuration dictionaries.
        
        This method validates the MCP configurations. It only adds MCP to retrievers
        if no explicit retriever configuration is provided via environment variables.
        
        Args:
            mcp_configs (list[dict]): List of MCP server configuration dictionaries.
        """
        # Check if user explicitly set RETRIEVER environment variable
        user_set_retriever = os.getenv("RETRIEVER") is not None
        
        if not user_set_retriever:
            # Only auto-add MCP if user hasn't explicitly set retrievers
            if hasattr(self.cfg, 'retrievers') and self.cfg.retrievers:
                # If retrievers is set in config (but not via env var)
                current_retrievers = set(self.cfg.retrievers.split(",")) if isinstance(self.cfg.retrievers, str) else set(self.cfg.retrievers)
                if "mcp" not in current_retrievers:
                    current_retrievers.add("mcp")
                    self.cfg.retrievers = ",".join(filter(None, current_retrievers))
            else:
                # No retrievers configured, use mcp as default
                self.cfg.retrievers = "mcp"
        # If user explicitly set RETRIEVER, respect their choice and don't auto-add MCP
        
        # Store the mcp_configs for use by the MCP retriever
        self.mcp_configs = mcp_configs

    async def _log_event(self, event_type: str, **kwargs):
        """Helper method to handle logging events"""
        if self.log_handler:
            try:
                if event_type == "tool":
                    await self.log_handler.on_tool_start(kwargs.get('tool_name', ''), **kwargs)
                elif event_type == "action":
                    await self.log_handler.on_agent_action(kwargs.get('action', ''), **kwargs)
                elif event_type == "research":
                    await self.log_handler.on_research_step(kwargs.get('step', ''), kwargs.get('details', {}))

                # Add direct logging as backup
                import logging
                research_logger = logging.getLogger('research')
                research_logger.info(f"{event_type}: {json.dumps(kwargs, default=str)}")

            except Exception as e:
                import logging
                logging.getLogger('research').error(f"Error in _log_event: {e}", exc_info=True)

    async def conduct_research(self, on_progress=None):
        """Conduct the research process.

        This method orchestrates the main research workflow including
        agent selection, web searching, and context gathering.

        Args:
            on_progress: Optional callback for progress updates.

        Returns:
            The accumulated research context.
        """
        await self._log_event("research", step="start", details={
            "query": self.query,
            "report_type": self.report_type,
            "agent": self.agent,
            "role": self.role
        })

        if not (self.agent and self.role):
            self._current_step = "agent_selection"
            await self._log_event("action", action="choose_agent")
            # Filter out encoding parameter as it's not supported by LLM APIs
            # filtered_kwargs = {k: v for k, v in self.kwargs.items() if k != 'encoding'}
            self.agent, self.role = await choose_agent(
                query=self.query,
                cfg=self.cfg,
                cost_callback=self.add_costs,
                headers=self.headers,
                prompt_family=self.prompt_family,
                **self.kwargs,
                # **filtered_kwargs
            )
            await self._log_event("action", action="agent_selected", details={
                "agent": self.agent,
                "role": self.role
            })

        await self._log_event("research", step="conducting_research", details={
            "agent": self.agent,
            "role": self.role
        })
        self._current_step = "research"
        self.context = await self.research_conductor.conduct_research()

        await self._log_event("research", step="research_completed", details={
            "context_length": len(self.context)
        })
        
        return self.context

    async def write_report(
        self,
        ext_context=None,
        custom_prompt="",
    ) -> str:
        """Write the research report.

        Args:
            ext_context: External context to use instead of internal context.
            custom_prompt: Custom prompt to guide report generation.

        Returns:
            The generated report as a string.
        """
        self._current_step = "report_writing"
        await self._log_event("research", step="writing_report", details={
            "context_source": "external" if ext_context else "internal",
        })

        report = await self.report_generator.write_report(
            ext_context=ext_context or self.context,
            custom_prompt=custom_prompt,
        )

        await self._log_event("research", step="report_completed", details={
            "report_length": len(report),
        })
        return report

    async def quick_search(self, query: str, query_domains: list[str] = None, aggregated_summary: bool = False) -> list[Any] | str:
        """Perform a quick search without full research workflow.

        Args:
            query: The search query.
            query_domains: Optional list of domains to restrict search to.
            aggregated_summary: Whether to return an aggregated summary of the search results.

        Returns:
            List of search results or a synthesized summary string.
        """
        search_results = await get_search_results(query, self.retrievers[0], query_domains=query_domains)

        if not aggregated_summary:
            return search_results

        # Format results for summary
        context = ""
        for i, result in enumerate(search_results, 1):
            context += f"[{i}] {result.get('title', '')}: {result.get('content', '')} ({result.get('url', '')})\n\n"

        prompt = self.prompt_family.generate_quick_summary_prompt(query, context)

        summary = await create_chat_completion(
            model=self.cfg.smart_llm_model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=self.cfg.smart_llm_provider,
            max_tokens=self.cfg.smart_token_limit,
            llm_kwargs=self.cfg.llm_kwargs,
            cost_callback=self.add_costs,
            rivalens_operation="quick_search_summary",
        )

        return summary


    # Utility methods
    def get_research_images(self, top_k: int = 10) -> list[dict[str, Any]]:
        """Get the top research images collected during research.

        Args:
            top_k: Maximum number of images to return.

        Returns:
            List of image dictionaries.
        """
        return self.research_images[:top_k]

    def add_research_images(self, images: list[dict[str, Any]]) -> None:
        """Add images to the research image collection.

        Args:
            images: List of image dictionaries to add.
        """
        self.research_images.extend(images)

    def get_research_sources(self) -> list[dict[str, Any]]:
        """Get all research sources collected during research.

        Returns:
            List of source dictionaries containing title, content, and images.
        """
        return self.research_sources

    def add_research_sources(self, sources: list[dict[str, Any]]) -> None:
        """Add sources to the research source collection.

        Args:
            sources: List of source dictionaries to add.
        """
        self.research_sources.extend(sources)

    def get_source_urls(self) -> list:
        """Get all visited source URLs.

        Returns:
            List of visited URL strings.
        """
        return list(self.visited_urls)

    def get_research_context(self) -> list:
        """Get the accumulated research context.

        Returns:
            List of context items collected during research.
        """
        return self.context

    def get_costs(self) -> float:
        """Get the total accumulated API costs.

        Returns:
            Total cost in USD.
        """
        return self.research_costs

    def get_step_costs(self) -> dict[str, float]:
        """Get a breakdown of API costs per research step.

        Returns:
            Dictionary mapping step names to their costs in USD.
        """
        return dict(self.step_costs)

    def set_verbose(self, verbose: bool) -> None:
        """Set the verbose output mode.

        Args:
            verbose: Whether to enable verbose output.
        """
        self.verbose = verbose

    def add_costs(self, cost: float) -> None:
        """Add to the accumulated API costs.

        The cost is attributed to the current step set via ``_current_step``.

        Args:
            cost: Cost amount to add in USD.

        Raises:
            ValueError: If cost is not a number.
        """
        if not isinstance(cost, (float, int)):
            raise ValueError("Cost must be an integer or float")
        self.research_costs += cost
        step = self._current_step
        self.step_costs[step] = self.step_costs.get(step, 0.0) + cost
        if self.log_handler:
            self._log_event("research", step="cost_update", details={
                "cost": cost,
                "total_cost": self.research_costs,
                "step_name": step,
            })
