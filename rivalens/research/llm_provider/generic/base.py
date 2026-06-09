import aiofiles
import asyncio
import atexit
import importlib
import json
import os
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from enum import Enum
from typing import Any

from colorama import Fore, Style, init

_LLM_THREAD_POOL_SIZE = int(os.getenv("RIVALENS_LLM_THREAD_POOL_SIZE", "64"))
_llm_executor = ThreadPoolExecutor(
    max_workers=_LLM_THREAD_POOL_SIZE,
    thread_name_prefix="rivalens-llm",
)
atexit.register(_llm_executor.shutdown, wait=False)


def _get_llm_executor() -> ThreadPoolExecutor:
    """Dedicated thread pool for LLM API calls.

    Using a separate pool avoids the process-default executor (``min(32, cpu+4)``
    threads) becoming a bottleneck when deep research fires many concurrent
    ``asyncio.gather``-ed LLM calls.
    """
    return _llm_executor


_SUPPORTED_PROVIDERS = {
    "openai",
    "anthropic",
}

NO_SUPPORT_TEMPERATURE_MODELS = [
    "o1-mini",
    "o1-mini-2024-09-12",
    "o1",
    "o1-2024-12-17",
    "o3-mini",
    "o3-mini-2025-01-31",
    "o1-preview",
    "o3",
    "o3-2025-04-16",
    "o4-mini",
    "o4-mini-2025-04-16",
    # GPT-5 family: OpenAI enforces default temperature only
    "gpt-5",
    "gpt-5-mini",
]

NO_SUPPORT_TEMPERATURE_MODEL_PREFIXES: list[str] = []


def is_no_support_temperature_model(model: str) -> bool:
    """Check whether *model* is a reasoning model that doesn't support temperature
    and should not have max_tokens imposed externally."""
    if model in NO_SUPPORT_TEMPERATURE_MODELS:
        return True
    return any(
        model.startswith(prefix)
        for prefix in NO_SUPPORT_TEMPERATURE_MODEL_PREFIXES
    )


SUPPORT_REASONING_EFFORT_MODELS = [
    "o3-mini",
    "o3-mini-2025-01-31",
    "o3",
    "o3-2025-04-16",
    "o4-mini",
    "o4-mini-2025-04-16",
]

class ReasoningEfforts(Enum):
    High = "high"
    Medium = "medium"
    Low = "low"


class ChatLogger:
    """Helper utility to log all chat requests and their corresponding responses
    plus the stack trace leading to the call.
    """

    def __init__(self, fname: str):
        self.fname = fname
        self._lock = asyncio.Lock()

    async def log_request(self, messages, response):
        async with self._lock:
            async with aiofiles.open(self.fname, mode="a", encoding="utf-8") as handle:
                await handle.write(json.dumps({
                    "messages": messages,
                    "response": response,
                    "stacktrace": traceback.format_exc()
                }) + "\n")


def _content_summary(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"type": "str", "length": len(content)}
    if isinstance(content, list):
        return {"type": "list", "length": len(content)}
    if content is None:
        return {"type": "NoneType", "length": 0}
    return {"type": type(content).__name__, "length": len(str(content))}


def _safe_metadata(metadata: Any) -> Any:
    if not isinstance(metadata, dict):
        return metadata
    allowed_keys = {
        "finish_reason",
        "model_name",
        "model",
        "system_fingerprint",
        "service_tier",
        "token_usage",
        "usage",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "content_filter_results",
        "prompt_filter_results",
    }
    return {
        key: value
        for key, value in metadata.items()
        if key in allowed_keys or key.endswith("token_usage")
    }


def _message_debug_info(output: Any) -> dict[str, Any]:
    additional_kwargs = getattr(output, "additional_kwargs", {}) or {}
    response_metadata = getattr(output, "response_metadata", {}) or {}
    usage_metadata = getattr(output, "usage_metadata", None)
    debug_info = {
        "message_type": type(output).__name__,
        "content": _content_summary(getattr(output, "content", None)),
        "response_metadata": _safe_metadata(response_metadata),
        "usage_metadata": usage_metadata,
        "additional_kwargs_keys": sorted(additional_kwargs.keys()),
    }
    for key in ("finish_reason", "refusal", "reasoning_content"):
        if key in additional_kwargs:
            value = additional_kwargs[key]
            debug_info[f"additional_{key}"] = (
                {"type": type(value).__name__, "length": len(value)}
                if isinstance(value, str)
                else value
            )
    return debug_info


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
            elif hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


class GenericLLMProvider:

    def __init__(self, llm, chat_log: str | None = None,  verbose: bool = True):
        self.llm = llm
        self.chat_logger = ChatLogger(chat_log) if chat_log else None
        self.verbose = verbose
        self.last_response_debug: dict[str, Any] = {}
    @classmethod
    def from_provider(cls, provider: str, chat_log: str | None = None, verbose: bool=True, **kwargs: Any):
        if provider == "openai":
            _check_pkg("langchain_openai")
            from langchain_openai import ChatOpenAI

            # Support custom OpenAI-compatible APIs via OPENAI_BASE_URL
            if "openai_api_base" not in kwargs and os.environ.get("OPENAI_BASE_URL"):
                kwargs["openai_api_base"] = os.environ["OPENAI_BASE_URL"]

            llm = ChatOpenAI(**kwargs)
        elif provider == "anthropic":
            _check_pkg("langchain_anthropic")
            from langchain_anthropic import ChatAnthropic

            if "anthropic_api_key" not in kwargs and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
                kwargs["anthropic_api_key"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
            if "anthropic_api_url" not in kwargs and os.environ.get("ANTHROPIC_BASE_URL"):
                kwargs["anthropic_api_url"] = os.environ["ANTHROPIC_BASE_URL"]

            llm = ChatAnthropic(**kwargs)
        else:
            supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
            raise ValueError(
                f"Unsupported {provider}.\n\nSupported model providers are: {supported}"
            )
        return cls(llm, chat_log, verbose=verbose)


    async def get_chat_response(self, messages, stream, websocket=None, **kwargs):
        if not stream:
            # Run in thread pool to avoid anyio TCP connect issues on Windows
            # when using non-OpenAI endpoints behind istio-envoy proxies.
            loop = asyncio.get_running_loop()
            context = copy_context()
            output = await loop.run_in_executor(
                _get_llm_executor(), lambda: context.run(self.llm.invoke, messages, **kwargs)
            )

            self.last_response_debug = _message_debug_info(output)
            res = _content_to_text(output.content)

        else:
            self.last_response_debug = {"stream": True}
            res = await self.stream_response(messages, websocket, **kwargs)

        if self.chat_logger:
            await self.chat_logger.log_request(messages, res)

        return res

    def get_response_debug_info(self) -> dict[str, Any]:
        return dict(self.last_response_debug)

    async def stream_response(self, messages, websocket=None, **kwargs):
        paragraph = ""
        response = ""

        # Streaming the response using the chain astream method from langchain
        async for chunk in self.llm.astream(messages, **kwargs):
            content = _content_to_text(chunk.content)
            if not content:
                continue
            response += content
            paragraph += content
            if "\n" in paragraph:
                await self._send_output(paragraph, websocket)
                paragraph = ""

        if paragraph:
            await self._send_output(paragraph, websocket)

        return response

    async def _send_output(self, content, websocket=None):
        if websocket is not None:
            await websocket.send_json({"type": "report", "output": content})
        elif self.verbose:
            print(f"{Fore.GREEN}{content}{Style.RESET_ALL}", flush=True)


def _check_pkg(pkg: str) -> None:
    if not importlib.util.find_spec(pkg):
        pkg_kebab = pkg.replace("_", "-")
        # Import colorama and initialize it
        init(autoreset=True)

        try:
            print(f"{Fore.YELLOW}Installing {pkg_kebab}...{Style.RESET_ALL}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", pkg_kebab])
            print(f"{Fore.GREEN}Successfully installed {pkg_kebab}{Style.RESET_ALL}")

            # Try importing again after install
            importlib.import_module(pkg)

        except subprocess.CalledProcessError:
            raise ImportError(
                Fore.RED + f"Failed to install {pkg_kebab}. Please install manually with "
                f"`pip install -U {pkg_kebab}`"
            )
