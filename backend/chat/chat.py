import logging
import os
import uuid
import json
import re
from fastapi import WebSocket
from typing import List, Dict, Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import InMemoryVectorStore
from rivalens.research.memory import Memory
from rivalens.research.config.config import Config
from rivalens.research.utils.llm import create_chat_completion
from rivalens.research.utils.tools import create_chat_completion_with_tools, create_search_tool
from tavily import TavilyClient
from datetime import datetime

try:
    from server.evidence_vector_store import EvidenceVectorStore
except Exception:
    EvidenceVectorStore = None

# Setup logging
# Get logger instance
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # Only log to console
    ]
)

# Note: LLM client is now handled through Rivalens's unified LLM system
# This supports all configured providers (OpenAI, Google Gemini, Anthropic, etc.)

def get_tools():
    """Define tools for LLM function calling (primarily for OpenAI-compatible providers)"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "quick_search",
                "description": "Search for current events or online information when you need new knowledge that doesn't exist in the current context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    return tools

class ChatAgentWithMemory:
    def __init__(
        self,
        report: str,
        config_path="default",
        headers=None,
        vector_store=None,
        evidence_context=None
    ):
        self.report = report
        self.headers = headers
        self.config = Config(config_path)
        self.vector_store = vector_store
        self.retriever = None
        self.search_metadata = None
        self.evidence_context = evidence_context or {}
        self.evidence_vector_store = EvidenceVectorStore() if EvidenceVectorStore is not None else None
        
        # Initialize Tavily client (optional - only if API key is available)
        tavily_api_key = os.environ.get("TAVILY_API_KEY")
        if tavily_api_key:
            self.tavily_client = TavilyClient(api_key=tavily_api_key)
        else:
            self.tavily_client = None
            logger.warning("TAVILY_API_KEY not set - web search in chat will be disabled")
        
        # Process document and create vector store if not provided
        if not self.vector_store and False:
            self._setup_vector_store()
    
    def _setup_vector_store(self):
        """Setup vector store for document retrieval"""
        # Process document into chunks
        documents = self._process_document(self.report)
        
        # Create unique thread ID
        self.thread_id = str(uuid.uuid4())
        
        # Setup embeddings and vector store
        cfg = Config()
        self.embedding = Memory(
            cfg.embedding_provider,
            cfg.embedding_model,
            **cfg.embedding_kwargs
        ).get_embeddings()
        
        # Create vector store and retriever
        self.vector_store = InMemoryVectorStore(self.embedding)
        self.vector_store.add_texts(documents)
        self.retriever = self.vector_store.as_retriever(k=4)
        
    def _process_document(self, report):
        """Split Report into Chunks"""
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1024,
            chunk_overlap=20,
            length_function=len,
            is_separator_regex=False,
        )
        documents = text_splitter.split_text(report)
        return documents

    def quick_search(self, query):
        """Perform a web search for current information using Tavily"""
        try:
            # Check if Tavily client is available
            if self.tavily_client is None:
                logger.warning(f"Tavily client not available, skipping web search for: {query}")
                self.search_metadata = {
                    "query": query,
                    "sources": [],
                    "error": "Web search is disabled - TAVILY_API_KEY not configured"
                }
                return {
                    "error": "Web search is disabled - TAVILY_API_KEY not configured",
                    "results": []
                }
            
            logger.info(f"Performing web search for: {query}")
            results = self.tavily_client.search(query=query, max_results=5)
            
            # Store search metadata for frontend
            self.search_metadata = {
                "query": query,
                "sources": [
                    {"title": result.get("title", ""), 
                     "url": result.get("url", ""),
                     "content": result.get("content", "")[:200] + "..." if len(result.get("content", "")) > 200 else result.get("content", "")}
                    for result in results.get("results", [])
                ]
            }
            
            return results
        except Exception as e:
            logger.error(f"Error performing web search: {str(e)}", exc_info=True)
            return {
                "error": str(e),
                "results": []
            }


    async def process_chat_completion(self, messages: List[Dict[str, str]]):
        """Process chat completion using configured LLM provider with tool calling support"""
        # Create a search tool using the utility function
        search_tool = create_search_tool(self.quick_search)
        
        # Use the tool-enabled chat completion utility
        response, tool_calls_metadata = await create_chat_completion_with_tools(
            messages=messages,
            tools=[search_tool],
            model=self.config.smart_llm_model,
            llm_provider=self.config.smart_llm_provider,
            llm_kwargs=self.config.llm_kwargs,
        )
        
        # Process metadata to match the expected format for the chat system
        processed_metadata = []
        for metadata in tool_calls_metadata:
            if metadata.get("tool") == "search_tool":
                # Extract query from args
                query = metadata.get("args", {}).get("query", "")
                
                # Trigger search again to get metadata (the search was already executed by LangChain)
                if query:
                    self.quick_search(query)  # This populates self.search_metadata
                    
                processed_metadata.append({
                    "tool": "quick_search",
                    "query": query,
                    "search_metadata": self.search_metadata
                })
        
        return response, processed_metadata

    def _get_context_list(self, key: str):
        value = self.evidence_context.get(key)
        if isinstance(value, list):
            return value

        state = self.evidence_context.get("state")
        if isinstance(state, dict):
            value = state.get(key)
            if isinstance(value, list):
                return value

        return []

    def _truncate_text(self, value: Any, limit: int = 420) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _compact_evidence_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        retrieval = item.get("retrieval") if isinstance(item.get("retrieval"), dict) else {}
        return {
            "id": item.get("id", ""),
            "citation_ref": item.get("citation_ref", ""),
            "title": self._truncate_text(item.get("title"), 180),
            "url": item.get("url", "") or item.get("source_url", ""),
            "competitor": item.get("competitor", ""),
            "dimension": item.get("dimension_name") or item.get("analysis_dimension_id") or item.get("dimension_id", ""),
            "source_type": item.get("source_type", ""),
            "is_primary_source": item.get("is_primary_source"),
            "confidence": item.get("confidence"),
            "excerpt": self._truncate_text(item.get("excerpt") or item.get("summary") or item.get("content"), 520),
            "retrieval_distance": retrieval.get("distance"),
        }

    def _compact_claim(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": claim.get("id", ""),
            "claim": self._truncate_text(claim.get("claim"), 520),
            "competitors": claim.get("competitors", []),
            "evidence_ids": claim.get("evidence_ids", []),
            "confidence": claim.get("confidence"),
            "reasoning": self._truncate_text(claim.get("reasoning"), 360),
            "analysis_dimension_id": claim.get("analysis_dimension_id", ""),
            "report_section_id": claim.get("report_section_id", ""),
        }

    def _compact_support_review(self, review: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": review.get("id", ""),
            "claim_id": review.get("claim_id", ""),
            "support_status": review.get("support_status", ""),
            "evidence_ids": review.get("evidence_ids", []),
            "retrieved_evidence_ids": review.get("retrieved_evidence_ids", []),
            "retrieval_notes": self._truncate_text(review.get("retrieval_notes"), 240),
            "unsupported_phrases": review.get("unsupported_phrases", []),
            "reviewer_notes": self._truncate_text(review.get("reviewer_notes"), 360),
            "confidence": review.get("confidence"),
        }

    def _score_context_item(self, item: Dict[str, Any], query: str) -> int:
        if not query:
            return 0
        haystack = json.dumps(item, ensure_ascii=False).lower()
        query_lower = query.lower()
        score = 0
        item_id = str(item.get("id", "")).lower()
        if item_id and item_id in query_lower:
            score += 20
        url = str(item.get("url", "") or item.get("source_url", "")).lower()
        if url and url in query_lower:
            score += 20
        for token in re.findall(r"[\w\-\u4e00-\u9fff]{2,}", query_lower):
            if token in haystack:
                score += 1
        return score

    def _select_context_items(self, items: List[Dict[str, Any]], query: str, limit: int):
        scored = [
            (self._score_context_item(item, query), index, item)
            for index, item in enumerate(items)
            if isinstance(item, dict)
        ]
        matched = [entry for entry in scored if entry[0] > 0]
        if matched:
            selected = [item for _, _, item in sorted(matched, key=lambda entry: (-entry[0], entry[1]))]
            selected_ids = {id(item) for item in selected}
            selected.extend(item for _, _, item in scored if id(item) not in selected_ids)
            return selected[:limit]
        return [item for _, _, item in scored[:limit]]

    def _is_weakness_query(self, query: str) -> bool:
        query_lower = query.lower()
        return any(
            token in query_lower
            for token in (
                "不足",
                "薄弱",
                "弱",
                "缺证据",
                "不可靠",
                "保守",
                "weak",
                "unsupported",
                "unverifiable",
                "conservative",
            )
        )

    def _claim_weakness_score(self, claim: Dict[str, Any], reviews_by_claim_id: Dict[str, Dict[str, Any]]) -> int:
        score = 0
        evidence_ids = claim.get("evidence_ids") or []
        if not evidence_ids:
            score += 20
        elif len(evidence_ids) == 1:
            score += 5

        try:
            confidence = float(claim.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and confidence < 0.45:
            score += 10

        review = reviews_by_claim_id.get(claim.get("id", ""))
        support_status = str((review or {}).get("support_status", "")).lower()
        if support_status in {"weak", "unverifiable", "contradicted"}:
            score += 15
        return score

    def _select_claims(self, claims: List[Dict[str, Any]], reviews: List[Dict[str, Any]], query: str, limit: int):
        if not self._is_weakness_query(query):
            return self._select_context_items(claims, query, limit)

        reviews_by_claim_id = {
            review.get("claim_id"): review
            for review in reviews
            if isinstance(review, dict) and review.get("claim_id")
        }
        scored = [
            (
                self._claim_weakness_score(claim, reviews_by_claim_id),
                self._score_context_item(claim, query),
                index,
                claim,
            )
            for index, claim in enumerate(claims)
            if isinstance(claim, dict)
        ]
        return [
            claim
            for _, _, _, claim in sorted(scored, key=lambda entry: (-entry[0], -entry[1], entry[2]))[:limit]
        ]

    def _last_user_message(self, messages: List[Dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""

    def _retrieve_evidence_items(self, query: str, claims: List[Dict[str, Any]], limit: int = 24) -> List[Dict[str, Any]]:
        if self.evidence_vector_store is None:
            return []

        research_id = self.evidence_context.get("research_id")
        run_id = self.evidence_context.get("run_id")
        if not research_id and not run_id:
            return []
        retrieval_query = query.strip()
        if not retrieval_query:
            retrieval_query = "\n".join(
                str(claim.get("claim", ""))
                for claim in claims[:8]
                if isinstance(claim, dict) and claim.get("claim")
            )
        if not retrieval_query:
            return []

        try:
            return self.evidence_vector_store.search(
                retrieval_query,
                research_id=str(research_id) if research_id else None,
                run_id=str(run_id) if run_id else None,
                limit=limit,
            )
        except Exception:
            logger.exception("Evidence retrieval failed for chat context")
            return []

    def _build_evidence_context_text(self, messages: List[Dict[str, Any]]) -> str:
        query = self._last_user_message(messages)
        evidence_items = self._get_context_list("evidence_index") or self._get_context_list("evidence_items")
        claims = self._get_context_list("analysis_claims")
        support_reviews = self._get_context_list("claim_support_reviews")
        knowledge_facts = self._get_context_list("knowledge_facts")
        competitor_knowledge = self._get_context_list("competitor_knowledge")

        selected_claims = self._select_claims(claims, support_reviews, query, 90)
        retrieved_evidence = self._retrieve_evidence_items(query, selected_claims)
        claim_evidence_ids = {
            evidence_id
            for claim in selected_claims
            for evidence_id in claim.get("evidence_ids", [])
            if evidence_id
        }

        evidence_by_id = {
            item.get("id"): item
            for item in evidence_items
            if isinstance(item, dict) and item.get("id")
        }
        selected_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in claim_evidence_ids
            if evidence_id in evidence_by_id
        ]
        selected_evidence_ids = {item.get("id") for item in selected_evidence}
        for item in retrieved_evidence:
            item_id = item.get("id")
            if item_id and item_id not in selected_evidence_ids:
                selected_evidence.append(item)
                selected_evidence_ids.add(item_id)
        for item in self._select_context_items(evidence_items, query, 120):
            if item.get("id") not in selected_evidence_ids:
                selected_evidence.append(item)
                selected_evidence_ids.add(item.get("id"))
            if len(selected_evidence) >= 120:
                break

        payload = {
            "coverage": {
                "total_claims": len(claims),
                "total_evidence_items": len(evidence_items),
                "selected_claims": len(selected_claims),
                "selected_evidence_items": len(selected_evidence),
                "retrieved_evidence_items": len(retrieved_evidence),
            },
            "retrieval": {
                "research_id": self.evidence_context.get("research_id", ""),
                "run_id": self.evidence_context.get("run_id", ""),
                "source": "pgvector:evidence_embeddings",
                "query": self._truncate_text(query, 360),
                "retrieved_evidence_ids": [item.get("id", "") for item in retrieved_evidence if item.get("id")],
            },
            "claims": [self._compact_claim(claim) for claim in selected_claims],
            "evidence_items": [self._compact_evidence_item(item) for item in selected_evidence],
            "claim_support_reviews": [
                self._compact_support_review(review)
                for review in self._select_context_items(support_reviews, query, 80)
            ],
            "knowledge_facts": [
                {
                    "id": fact.get("id", ""),
                    "statement": self._truncate_text(fact.get("statement"), 420),
                    "competitor": fact.get("competitor", ""),
                    "evidence_ids": fact.get("evidence_ids", []),
                    "confidence": fact.get("confidence"),
                }
                for fact in self._select_context_items(knowledge_facts, query, 80)
            ],
            "competitor_knowledge": [
                {
                    "id": item.get("id", ""),
                    "competitor": item.get("competitor", ""),
                    "evidence_ids": item.get("evidence_ids", []),
                    "confidence": item.get("confidence"),
                    "feature_count": len(item.get("feature_tree", []) or []),
                    "persona_count": len(item.get("user_personas", []) or []),
                    "pricing_model": item.get("pricing_model", {}),
                }
                for item in self._select_context_items(competitor_knowledge, query, 30)
            ],
        }

        if not evidence_items and not claims:
            return "No structured evidence context was provided for this report."

        return json.dumps(payload, ensure_ascii=False, indent=2)


    async def chat(self, messages, websocket=None):
        """Chat with configured LLM provider (supports OpenAI, Google Gemini, Anthropic, etc.)
        
        Args:
            messages: List of chat messages with role and content
            websocket: Optional websocket for streaming responses
        
        Returns:
            tuple: (str: The AI response message, dict: metadata about tool usage)
        """
        try:
            evidence_context_text = self._build_evidence_context_text(messages)
            
            # Format system prompt with the report context
            system_prompt = f"""
            You are Rivalens, an AI-driven competitor analysis agent system.
            Help users reason from traceable evidence and clearly separate sourced facts from analysis.
            
            This is a chat about a research report that you created. Answer based on the given report and the structured
            evidence context below.
            
            Evidence QA rules:
            - Prefer retrieved pgvector evidence_context over narrative report prose when answering source, support, or claim questions.
            - Use retrieval.retrieved_evidence_ids and evidence_items first; use the report only as secondary framing.
            - When explaining a claim, include the relevant claim id, evidence id, source URL, and a short support note.
            - When asked which conclusions are weak, flag claims with no evidence_ids, low confidence, unverifiable/weak support reviews,
              missing URLs, or evidence that only partially supports the wording.
            - When asked to expand a source, summarize the EvidenceItem title, URL, source type, excerpt, linked claims, and any caveat.
            - When asked to make analysis more conservative, rewrite only what the evidence supports and keep evidence ids/URLs beside
              supported statements.
            - Never invent evidence ids, source URLs, or citations. If the context is missing, say what cannot be traced.
            - If the user writes in Chinese, answer in Chinese.
            
            You may use the quick_search tool when the user asks about information that might require current data 
            not found in the report, such as recent events, updated statistics, or news. If there's no report available,
            you can use the quick_search tool to find information online.
            
            You must respond in markdown format. You must make it readable with paragraphs, tables, etc when possible. 
            Remember that you're answering in a chat not a report.
            
            Assume the current time is: {datetime.now()}.
            
            Structured evidence_context:
            {evidence_context_text}
            
            Report: {self.report}
            
            """
            
            # Format message history for OpenAI input
            formatted_messages = []
            
            # Add system message first
            formatted_messages.append({
                "role": "system", 
                "content": system_prompt
            })
            
            # Add user/assistant message history - filter out non-essential fields
            for msg in messages:
                if 'role' in msg and 'content' in msg:
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                else:
                    logger.warning(f"Skipping message with missing role or content: {msg}")
            
            # Process the chat using configured LLM provider
            ai_message, tool_calls_metadata = await self.process_chat_completion(formatted_messages)
            
            # Provide fallback response if message is empty
            if not ai_message:
                logger.warning("No AI message content found in response, using fallback message")
                ai_message = "I apologize, but I couldn't generate a proper response. Please try asking your question again."
            
            logger.info(f"Generated response: {ai_message[:100]}..." if len(ai_message) > 100 else f"Generated response: {ai_message}")
            
            # Return both the message and any metadata about tools used
            return ai_message, tool_calls_metadata
            
        except Exception as e:
            logger.error(f"Error in chat: {str(e)}", exc_info=True)
            raise

    def get_context(self):
        """return the current context of the chat"""
        return self.report
