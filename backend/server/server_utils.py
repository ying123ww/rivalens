import asyncio
import json
import os
import re
import time
import shutil
import traceback
from typing import Awaitable, Dict, List, Any
from fastapi.responses import JSONResponse, FileResponse
from rivalens.research.document.document import DocumentLoader
from rivalens.research import ResearchEngine
from pathlib import Path
from datetime import datetime
from fastapi import HTTPException
import logging
import hashlib

from rivalens.report_export import generate_report_files
from .rivalens_runner import run_rivalens_task

# Import chat agent
try:
    import sys
    backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from chat.chat import ChatAgentWithMemory
except ImportError:
    ChatAgentWithMemory = None

logger = logging.getLogger(__name__)

class CustomLogsHandler:
    """Custom handler to capture streaming logs from the research process"""
    def __init__(self, websocket, task: str):
        self.logs = []
        self.websocket = websocket
        self.websocket_closed = False
        self.log_batch_size = self._env_int("RIVALENS_WS_LOG_BATCH_SIZE", 20, minimum=1)
        self.pending_log_batch: list[Dict[str, Any]] = []
        sanitized_filename = sanitize_filename(f"task_{int(time.time())}_{task}")
        self.log_file = os.path.join("outputs", f"{sanitized_filename}.json")
        self.timestamp = datetime.now().isoformat()
        # Initialize log file with metadata
        os.makedirs("outputs", exist_ok=True)
        with open(self.log_file, 'w') as f:
            json.dump({
                "timestamp": self.timestamp,
                "events": [],
                "content": {
                    "query": "",
                    "sources": [],
                    "context": [],
                    "report": "",
                    "costs": 0.0
                }
            }, f, indent=2)

    async def send_json(self, data: Dict[str, Any]) -> None:
        """Store log data and send to websocket when it is still connected."""
        self._write_log_data(data)

        if not self.websocket or self.websocket_closed:
            return

        if data.get("type") == "logs":
            self.pending_log_batch.append(data)
            if len(self.pending_log_batch) >= self.log_batch_size:
                await self.flush_log_batch()
            return

        if data.get("type") != "report":
            await self.flush_log_batch()

        try:
            await self.websocket.send_json(data)
        except Exception as exc:
            self.websocket_closed = True
            self.websocket = None
            self._record_websocket_disconnect(exc, data)
            log_method = logger.warning if _is_websocket_disconnect_error(exc) else logger.error
            log_method(
                "WebSocket send failed; live updates stopped but server-side logging will continue: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=not _is_websocket_disconnect_error(exc),
            )

    async def flush_log_batch(self) -> None:
        if not self.pending_log_batch or not self.websocket or self.websocket_closed:
            self.pending_log_batch = []
            return

        batch = self.pending_log_batch
        self.pending_log_batch = []
        summary = self._log_batch_summary(batch)
        try:
            await self.websocket.send_json(summary)
        except Exception as exc:
            self.websocket_closed = True
            self.websocket = None
            self._record_websocket_disconnect(exc, summary)
            log_method = logger.warning if _is_websocket_disconnect_error(exc) else logger.error
            log_method(
                "WebSocket log batch send failed; server-side logging will continue: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=not _is_websocket_disconnect_error(exc),
            )

    def _log_batch_summary(self, batch: list[Dict[str, Any]]) -> Dict[str, Any]:
        content_counts: dict[str, int] = {}
        for item in batch:
            content = str(item.get("content", "log"))
            content_counts[content] = content_counts.get(content, 0) + 1

        latest = [
            {
                "content": item.get("content"),
                "output": self._truncate(str(item.get("output", "")), 180),
            }
            for item in batch[-5:]
        ]
        return {
            "type": "logs",
            "content": "log_batch",
            "output": f"{len(batch)} log events batched on the server.",
            "metadata": {
                "batched": True,
                "count": len(batch),
                "content_counts": content_counts,
                "latest": latest,
            },
        }

    def _truncate(self, value: str, limit: int) -> str:
        return value if len(value) <= limit else value[: limit - 3] + "..."

    def _env_int(self, env_name: str, default: int, minimum: int = 0) -> int:
        raw_value = os.getenv(env_name)
        if raw_value in (None, ""):
            return default
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed)

    def _write_log_data(self, data: Dict[str, Any]) -> None:
        # Read current log file
        with open(self.log_file, 'r') as f:
            log_data = json.load(f)
            
        # Update appropriate section based on data type
        if data.get('type') == 'logs':
            log_data['events'].append({
                "timestamp": datetime.now().isoformat(),
                "type": "event",
                "data": data
            })
        elif data.get('type') == 'report':
            log_data['content']['report'] = (
                log_data['content'].get('report', '') + str(data.get('output', ''))
            )
        else:
            # Update content section for other types of data
            log_data['content'].update(data)
            
        # Save updated log file
        with open(self.log_file, 'w') as f:
            json.dump(log_data, f, indent=2)

    def _record_websocket_disconnect(self, exc: Exception, failed_data: Dict[str, Any]) -> None:
        failed_type = failed_data.get("type")
        failed_content = failed_data.get("content")
        self._write_log_data({
            "type": "logs",
            "content": "websocket_disconnected",
            "output": (
                "WebSocket disconnected while streaming results. "
                "The browser will not receive further live updates for this run."
            ),
            "metadata": {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failed_message_type": failed_type,
                "failed_message_content": failed_content,
            },
        })


def _is_websocket_disconnect_error(exc: Exception) -> bool:
    error_type = type(exc).__name__
    error_msg = str(exc).lower()
    return (
        error_type in {
            "WebSocketDisconnect",
            "ClientDisconnected",
            "ConnectionClosed",
            "ConnectionClosedError",
            "ConnectionClosedOK",
        }
        or "websocketdisconnect" in error_msg
        or "client disconnected" in error_msg
        or "connectionclosed" in error_msg
        or "close message has been sent" in error_msg
        or "no close frame received" in error_msg
    )


async def _safe_websocket_send_json(websocket, data: Dict[str, Any]) -> bool:
    try:
        await websocket.send_json(data)
        return True
    except Exception as exc:
        log_method = logger.warning if _is_websocket_disconnect_error(exc) else logger.error
        log_method(
            "Unable to send WebSocket message: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=not _is_websocket_disconnect_error(exc),
        )
        return False


class Researcher:
    def __init__(self, query: str, report_type: str = "research_report"):
        self.query = query
        self.report_type = report_type
        # Generate unique ID for this research task
        self.research_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(query)}"
        # Initialize logs handler with research ID
        self.logs_handler = CustomLogsHandler(None, self.research_id)
        self.researcher = ResearchEngine(
            query=query,
            report_type=report_type,
            websocket=self.logs_handler
        )

    async def research(self) -> dict:
        """Conduct research and return paths to generated files"""
        await self.researcher.conduct_research()
        report = await self.researcher.write_report()
        
        # Generate the files
        sanitized_filename = sanitize_filename(f"task_{int(time.time())}_{self.query}")
        file_paths = await generate_report_files(
            report,
            sanitized_filename,
            quote_paths=True,
            include_legacy_md_key=True,
        )
        
        # Get the JSON log path that was created by CustomLogsHandler
        json_relative_path = os.path.relpath(self.logs_handler.log_file)
        
        return {
            "output": {
                **file_paths,  # Include PDF, DOCX, and MD paths
                "json": json_relative_path
            }
        }

def sanitize_filename(filename: str) -> str:
    # Split into components
    prefix, timestamp, *task_parts = filename.split('_')
    task = '_'.join(task_parts)
    task_hash = hashlib.md5(task.encode('utf-8', errors='ignore')).hexdigest()[:10]
            
    # Reassemble and clean the filename
    sanitized = f"{prefix}_{timestamp}_{task_hash}"
    return re.sub(r"[^\w\s-]", "", sanitized).strip()


async def handle_start_command(websocket, data: str, manager, on_log_handler=None):
    json_data = json.loads(data[6:])
    (
        task,
        report_type,
        source_urls,
        document_urls,
        tone,
        headers,
        report_source,
        query_domains,
        mcp_enabled,
        mcp_strategy,
        mcp_configs,
        max_search_results,
        industry_direction_plan,
    ) = extract_command_data(json_data)

    if not task or not report_type:
        print("Error: Missing task or report_type")
        return

    # Create logs handler with websocket and task
    logs_handler = CustomLogsHandler(websocket, task)
    if on_log_handler:
        on_log_handler(logs_handler)
    # Initialize log content with query
    await logs_handler.send_json({
        "query": task,
        "sources": [],
        "context": [],
        "report": ""
    })

    sanitized_filename = sanitize_filename(f"task_{int(time.time())}_{task}")

    report_payload = await manager.start_streaming(
        task,
        report_type,
        report_source,
        source_urls,
        document_urls,
        tone,
        logs_handler,
        headers,
        query_domains,
        mcp_enabled,
        mcp_strategy,
        mcp_configs,
        max_search_results,
        industry_direction_plan,
    )
    report = (
        str(report_payload.get("report", ""))
        if isinstance(report_payload, dict)
        else str(report_payload)
    )
    file_paths = await generate_report_files(
        report,
        sanitized_filename,
        quote_paths=True,
        include_legacy_md_key=True,
    )
    # Add JSON log path to file_paths
    file_paths["json"] = os.path.relpath(logs_handler.log_file)
    if isinstance(report_payload, dict):
        file_paths["rivalens_response"] = report_payload
    await send_file_paths(logs_handler, file_paths)


async def handle_human_feedback(data: str):
    feedback_data = json.loads(data[14:])  # Remove "human_feedback" prefix
    print(f"Received human feedback: {feedback_data}")
    # TODO: Add logic to forward the feedback to the appropriate agent or update the research state


async def handle_chat_command(websocket, data: str):
    """Handle chat command from WebSocket."""
    try:
        # Parse chat data - format is "chat {json_data}"
        json_str = data[5:].strip()  # Remove "chat " prefix
        chat_data = json.loads(json_str)
        
        message = chat_data.get("message", "")
        report = chat_data.get("report", "")
        messages = chat_data.get("messages", [])
        
        # If only message is provided, convert to messages format
        if message and not messages:
            messages = [{"role": "user", "content": message}]
        
        if not messages:
            await websocket.send_json({
                "type": "chat",
                "content": "No message provided.",
                "role": "assistant"
            })
            return
        
        # Check if ChatAgentWithMemory is available
        if ChatAgentWithMemory is None:
            await websocket.send_json({
                "type": "chat",
                "content": "Chat functionality is not available. Please check the server configuration.",
                "role": "assistant"
            })
            return
        
        # Create chat agent with the report context
        chat_agent = ChatAgentWithMemory(
            report=report,
            config_path="default",
            headers=None
        )
        
        # Process the chat
        response_content, tool_calls_metadata = await chat_agent.chat(messages, websocket)
        
        # Send response back via WebSocket
        await websocket.send_json({
            "type": "chat",
            "content": response_content,
            "role": "assistant",
            "metadata": {
                "tool_calls": tool_calls_metadata
            } if tool_calls_metadata else None
        })
        
        logger.info(f"Chat response sent successfully")
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse chat data: {e}")
        await websocket.send_json({
            "type": "chat",
            "content": f"Error: Invalid message format - {str(e)}",
            "role": "assistant"
        })
    except Exception as e:
        logger.error(f"Error handling chat command: {e}\n{traceback.format_exc()}")
        await websocket.send_json({
            "type": "chat",
            "content": f"Error processing your message: {str(e)}",
            "role": "assistant"
        })

async def send_file_paths(websocket, file_paths: Dict[str, str]):
    await websocket.send_json({"type": "path", "output": file_paths})


def get_config_dict(
    langchain_api_key: str, openai_api_key: str, tavily_api_key: str,
    google_api_key: str, google_cx_key: str, bing_api_key: str,
    searchapi_api_key: str, serpapi_api_key: str, serper_api_key: str, searx_url: str
) -> Dict[str, str]:
    return {
        "LANGCHAIN_API_KEY": langchain_api_key or os.getenv("LANGCHAIN_API_KEY", ""),
        "OPENAI_API_KEY": openai_api_key or os.getenv("OPENAI_API_KEY", ""),
        "TAVILY_API_KEY": tavily_api_key or os.getenv("TAVILY_API_KEY", ""),
        "GOOGLE_API_KEY": google_api_key or os.getenv("GOOGLE_API_KEY", ""),
        "GOOGLE_CX_KEY": google_cx_key or os.getenv("GOOGLE_CX_KEY", ""),
        "BING_API_KEY": bing_api_key or os.getenv("BING_API_KEY", ""),
        "SEARCHAPI_API_KEY": searchapi_api_key or os.getenv("SEARCHAPI_API_KEY", ""),
        "SERPAPI_API_KEY": serpapi_api_key or os.getenv("SERPAPI_API_KEY", ""),
        "SERPER_API_KEY": serper_api_key or os.getenv("SERPER_API_KEY", ""),
        "SEARX_URL": searx_url or os.getenv("SEARX_URL", ""),
        "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2", "true"),
        "DOC_PATH": os.getenv("DOC_PATH", "./my-docs"),
        "RETRIEVER": os.getenv("RETRIEVER", ""),
        "EMBEDDING_MODEL": os.getenv("OPENAI_EMBEDDING_MODEL", "")
    }


def update_environment_variables(config: Dict[str, str]):
    for key, value in config.items():
        os.environ[key] = value


async def handle_file_upload(file, DOC_PATH: str) -> Dict[str, str]:
    file_path = os.path.join(DOC_PATH, os.path.basename(file.filename))
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    print(f"File uploaded to {file_path}")

    document_loader = DocumentLoader(DOC_PATH)
    await document_loader.load()

    return {"filename": file.filename, "path": file_path}


async def handle_file_deletion(filename: str, DOC_PATH: str) -> JSONResponse:
    file_path = os.path.join(DOC_PATH, os.path.basename(filename))
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"File deleted: {file_path}")
        return JSONResponse(content={"message": "File deleted successfully"})
    else:
        print(f"File not found: {file_path}")
        return JSONResponse(status_code=404, content={"message": "File not found"})


async def execute_rivalens_workflow(manager) -> Any:
    websocket = manager.active_connections[0] if manager.active_connections else None
    if websocket:
        report = await run_rivalens_task("Is AI in a hype cycle?", websocket, stream_output)
        return {"report": report}
    else:
        return JSONResponse(status_code=400, content={"message": "No active WebSocket connection"})


async def handle_websocket_communication(websocket, manager):
    running_task: asyncio.Task | None = None
    active_log_handler: CustomLogsHandler | None = None

    def set_active_log_handler(log_handler: CustomLogsHandler) -> None:
        nonlocal active_log_handler
        active_log_handler = log_handler

    def run_long_running_task(awaitable: Awaitable) -> asyncio.Task:
        async def safe_run():
            try:
                await awaitable
            except asyncio.CancelledError:
                logger.info("Task cancelled.")
                raise
            except Exception as e:
                logger.error(f"Error running task: {e}\n{traceback.format_exc()}")
                await _safe_websocket_send_json(
                    websocket,
                    {
                        "type": "logs",
                        "content": "error",
                        "output": f"Error: {e}",
                    }
                )

        return asyncio.create_task(safe_run())

    try:
        while True:
            try:
                data = await websocket.receive_text()
                logger.info(f"Received WebSocket message: {data[:50]}..." if len(data) > 50 else data)
                
                if data == "ping":
                    await websocket.send_text("pong")
                elif running_task and not running_task.done():
                    # discard any new request if a task is already running
                    logger.warning(
                        f"Received request while task is already running. Request data preview: {data[: min(20, len(data))]}..."
                    )
                    await _safe_websocket_send_json(
                        websocket,
                        {
                            "type": "logs",
                            "content": "warning",
                            "output": "Task already running. Please wait.",
                        }
                    )
                # Normalize command detection by checking startswith after stripping whitespace
                elif data.strip().startswith("start"):
                    logger.info(f"Processing start command")
                    running_task = run_long_running_task(
                        handle_start_command(
                            websocket,
                            data,
                            manager,
                            on_log_handler=set_active_log_handler,
                        )
                    )
                elif data.strip().startswith("human_feedback"):
                    logger.info(f"Processing human_feedback command")
                    running_task = run_long_running_task(handle_human_feedback(data))
                elif data.strip().startswith("chat"):
                    logger.info(f"Processing chat command")
                    running_task = run_long_running_task(handle_chat_command(websocket, data))
                else:
                    error_msg = f"Error: Unknown command or not enough parameters provided. Received: '{data[:100]}...'" if len(data) > 100 else f"Error: Unknown command or not enough parameters provided. Received: '{data}'"
                    logger.error(error_msg)
                    print(error_msg)
                    await _safe_websocket_send_json(websocket, {
                        "type": "error",
                        "content": "error",
                        "output": "Unknown command received by server"
                    })
            except Exception as e:
                if _is_websocket_disconnect_error(e):
                    logger.warning("WebSocket disconnected while handling messages: %s: %s", type(e).__name__, e)
                else:
                    logger.error(f"WebSocket error: {str(e)}\n{traceback.format_exc()}")
                print(f"WebSocket error: {e}")
                break
    finally:
        if running_task and not running_task.done():
            if active_log_handler:
                active_log_handler._write_log_data({
                    "type": "logs",
                    "content": "websocket_disconnected",
                    "output": (
                        "WebSocket disconnected before this run completed. "
                        "The active server task was cancelled, so a final report may not be available."
                    ),
                    "metadata": {
                        "running_task_cancelled": True,
                    },
                })
            running_task.cancel()
            try:
                await running_task
            except asyncio.CancelledError:
                pass

def extract_command_data(json_data: Dict) -> tuple:
    return (
        json_data.get("task"),
        json_data.get("report_type"),
        json_data.get("source_urls"),
        json_data.get("document_urls"),
        json_data.get("tone"),
        json_data.get("headers", {}),
        json_data.get("report_source"),
        json_data.get("query_domains", []),
        json_data.get("mcp_enabled", False),
        json_data.get("mcp_strategy", "fast"),
        json_data.get("mcp_configs", []),
        json_data.get("max_search_results"),
        json_data.get("industry_direction_plan"),
    )
