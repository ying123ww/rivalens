"""LLM utilities for Rivalens.

This module provides utility functions for interacting with various
LLM providers through a unified interface.
"""
from __future__ import annotations

import logging
import os
from typing import Any
import asyncio

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from rivalens.research.llm_provider.generic.base import (
    NO_SUPPORT_TEMPERATURE_MODELS,
    SUPPORT_REASONING_EFFORT_MODELS,
    ReasoningEfforts,
)

from ..prompts import PromptFamily
from ..trace_context import RIVALENS_TRACE_CONTEXT_KEY, compact_trace_context
from .costs import estimate_llm_cost
from .llm_rate_limiter import get_llm_rate_limiter
from .validators import Subtopics


def _provider_runtime_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in kwargs.items()
        if not key.startswith("rivalens_")
    }


def _llm_log_context(
    *,
    llm_provider: str | None,
    model: str | None,
    kwargs: dict[str, Any],
) -> str:
    trace_context = compact_trace_context(kwargs.get(RIVALENS_TRACE_CONTEXT_KEY))
    langsmith_extra = kwargs.get("langsmith_extra") or {}
    metadata = langsmith_extra.get("metadata") if isinstance(langsmith_extra, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}

    fields = {
        "provider": llm_provider or "<unset>",
        "model": model or "<unset>",
        "operation": metadata.get("rivalens_operation") or kwargs.get("rivalens_operation"),
        "branch_id": trace_context.get("branch_id") or metadata.get("rivalens_branch_id"),
        "branch_ids": metadata.get("rivalens_branch_ids") or kwargs.get("rivalens_branch_ids"),
        "task_id": trace_context.get("id") or metadata.get("rivalens_id"),
        "dimension_id": trace_context.get("dimension_id") or metadata.get("rivalens_dimension_id"),
        "search_stage": trace_context.get("search_stage") or metadata.get("rivalens_search_stage"),
        "competitor": trace_context.get("competitor") or metadata.get("rivalens_competitor"),
        "evidence_count": metadata.get("rivalens_evidence_count") or kwargs.get("rivalens_evidence_count"),
    }
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [], {})]
    return "; ".join(parts)


def get_llm(llm_provider: str, **kwargs):
    """Get an LLM provider instance.

    Args:
        llm_provider: The name of the LLM provider (e.g., 'openai', 'anthropic').
        **kwargs: Additional keyword arguments passed to the provider.

    Returns:
        A GenericLLMProvider instance configured for the specified provider.
    """
    from rivalens.research.llm_provider import GenericLLMProvider
    return GenericLLMProvider.from_provider(llm_provider, **kwargs)


async def create_chat_completion(
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = 0.4,
        max_tokens: int | None = 4000,
        llm_provider: str | None = None,
        stream: bool = False,
        websocket: Any | None = None,
        llm_kwargs: dict[str, Any] | None = None,
        cost_callback: callable = None,
        reasoning_effort: str | None = ReasoningEfforts.Medium.value,
        **kwargs
) -> str:
    """Create a chat completion using the OpenAI API
    Args:
        messages (list[dict[str, str]]): The messages to send to the chat completion.
        model (str, optional): The model to use. Defaults to None.
        temperature (float, optional): The temperature to use. Defaults to 0.4.
        max_tokens (int, optional): The max tokens to use. Defaults to 4000.
        llm_provider (str, optional): The LLM Provider to use.
        stream (bool): Whether to stream the response. Defaults to False.
        webocket (WebSocket): The websocket used in the currect request,
        llm_kwargs (dict[str, Any], optional): Additional LLM keyword arguments. Defaults to None.
        cost_callback: Callback function for updating cost.
        reasoning_effort (str, optional): Reasoning effort for OpenAI's reasoning models. Defaults to 'low'.
        **kwargs: Additional keyword arguments.
    Returns:
        str: The response from the chat completion.
    """
    # validate input
    if model is None:
        raise ValueError("Model cannot be None")
    if max_tokens is not None and max_tokens > 32001:
        raise ValueError(
            f"Max tokens cannot be more than 32,000, but got {max_tokens}")

    # Get the provider from supported providers
    provider_kwargs = {'model': model}

    if llm_kwargs:
        provider_kwargs.update(llm_kwargs)

    if model in SUPPORT_REASONING_EFFORT_MODELS:
        provider_kwargs['reasoning_effort'] = reasoning_effort

    if model not in NO_SUPPORT_TEMPERATURE_MODELS:
        provider_kwargs['temperature'] = temperature
        provider_kwargs['max_tokens'] = max_tokens
    else:
        provider_kwargs['temperature'] = None
        provider_kwargs['max_tokens'] = None

    if llm_provider == "openai":
        base_url = os.environ.get("OPENAI_BASE_URL", None)
        if base_url:
            provider_kwargs['openai_api_base'] = base_url

    provider = get_llm(llm_provider, **provider_kwargs)
    response = ""

    # Rate-limit before the retry loop (don't re-limit on retries)
    limiter = get_llm_rate_limiter()
    if not await limiter.acquire(llm_provider):
        raise RuntimeError(
            f"LLM rate-limit timeout for {llm_provider}"
        )

    # create response
    max_attempts = 1 if (stream and websocket is not None) else 10
    last_exception: Exception | None = None
    provider_runtime_kwargs = _provider_runtime_kwargs(kwargs)
    log_context = _llm_log_context(
        llm_provider=llm_provider,
        model=model,
        kwargs=kwargs,
    )
    log_suffix = f"; {log_context}" if log_context else ""
    for attempt in range(1, max_attempts + 1):
        try:
            response = await provider.get_chat_response(
                messages, stream, websocket, **provider_runtime_kwargs
            )
        except Exception as exc:
            last_exception = exc
            logging.getLogger(__name__).warning(
                f"LLM request failed (attempt {attempt}/{max_attempts}{log_suffix}): {exc}"
            )
            if attempt < max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue
            break

        if not response:
            last_exception = RuntimeError("Empty response from LLM provider")
            response_debug = (
                provider.get_response_debug_info()
                if hasattr(provider, "get_response_debug_info")
                else {}
            )
            logging.getLogger(__name__).warning(
                "LLM returned empty response "
                f"(attempt {attempt}/{max_attempts}{log_suffix}; response_debug={response_debug})"
            )
            if attempt < max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue
            break

        if cost_callback:
            llm_costs = estimate_llm_cost(str(messages), response)
            cost_callback(llm_costs)

        return response

    logging.error(f"Failed to get response from {llm_provider} API{log_suffix}")
    raise RuntimeError(f"Failed to get response from {llm_provider} API") from last_exception


async def construct_subtopics(
    task: str,
    data: str,
    config,
    subtopics: list = [],
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> list:
    """
    Construct subtopics based on the given task and data.

    Args:
        task (str): The main task or topic.
        data (str): Additional data for context.
        config: Configuration settings.
        subtopics (list, optional): Existing subtopics. Defaults to [].
        prompt_family (PromptFamily): Family of prompts
        **kwargs: Additional keyword arguments.

    Returns:
        list: A list of constructed subtopics.
    """
    try:
        parser = PydanticOutputParser(pydantic_object=Subtopics)

        prompt = PromptTemplate(
            template=prompt_family.generate_subtopics_prompt(),
            input_variables=["task", "data", "subtopics", "max_subtopics"],
            partial_variables={
                "format_instructions": parser.get_format_instructions()},
        )

        provider_kwargs = {'model': config.smart_llm_model}

        if config.llm_kwargs:
            provider_kwargs.update(config.llm_kwargs)

        if config.smart_llm_model in SUPPORT_REASONING_EFFORT_MODELS:
            provider_kwargs['reasoning_effort'] = ReasoningEfforts.High.value
        else:
            provider_kwargs['temperature'] = config.temperature
            provider_kwargs['max_tokens'] = config.smart_token_limit

        provider = get_llm(config.smart_llm_provider, **provider_kwargs)

        model = provider.llm

        chain = prompt | model | parser

        output = await chain.ainvoke({
            "task": task,
            "data": data,
            "subtopics": subtopics,
            "max_subtopics": config.max_subtopics
        }, **_provider_runtime_kwargs(kwargs))

        return output

    except Exception as e:
        print("Exception in parsing subtopics : ", e)
        logging.getLogger(__name__).error("Exception in parsing subtopics : \n {e}")
        return subtopics
