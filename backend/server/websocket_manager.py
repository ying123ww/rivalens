import os
import asyncio
import datetime
import json
import logging
import os
import traceback
from typing import Any, Dict, List

from fastapi import WebSocket

from report_type import BasicReport

from rivalens.research.utils.enum import ReportType, Tone
from rivalens.research.actions import stream_output  # Import stream_output
from .rivalens_runner import run_rivalens_task
from .server_utils import CustomLogsHandler

logger = logging.getLogger(__name__)


def _list_field(state: dict[str, Any], key: str) -> list[Any]:
    value = state.get(key)
    return value if isinstance(value, list) else []


def _dict_field(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    return value if isinstance(value, dict) else {}


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)


def build_rivalens_structured_response(
    state: dict[str, Any],
    *,
    fallback_run_id: str | None = None,
) -> dict[str, Any]:
    task = _dict_field(state, "task")
    run_id = str(task.get("run_id") or fallback_run_id or "")
    evidence_items = _list_field(state, "evidence_items")
    coverage_assessments = _list_field(state, "coverage_assessments")
    evidence_reviews = _list_field(state, "evidence_reviews")
    claim_support_reviews = _list_field(state, "claim_support_reviews")
    analysis_claims = _list_field(state, "analysis_claims")
    agent_events = _list_field(state, "agent_events")
    published_artifacts = _dict_field(state, "published_artifacts")

    return {
        "run_id": run_id,
        "report": str(state.get("report", "")),
        "report_artifacts": published_artifacts,
        "trace_summary": {
            "event_count": len(agent_events),
            "agents": [event.get("agent", "") for event in agent_events if isinstance(event, dict)],
            "latest_events": _json_safe(agent_events[-10:]),
            "research_branch_count": len(_list_field(state, "research_branches")),
            "research_task_count": len(_list_field(state, "research_tasks")),
            "evidence_count": len(evidence_items),
            "claim_count": len(analysis_claims),
        },
        "assessments": {
            "coverage": _json_safe(coverage_assessments),
            "evidence_reviews": _json_safe(evidence_reviews),
            "claim_support_reviews": _json_safe(claim_support_reviews),
        },
        "evidence_index": _json_safe(evidence_items),
        "analysis_claims": _json_safe(analysis_claims),
        "claim_support_reviews": _json_safe(claim_support_reviews),
        "competitor_knowledge": _json_safe(_list_field(state, "competitor_knowledge")),
        "state": _json_safe(state),
    }

class WebSocketManager:
    """Manage websockets"""

    def __init__(self):
        """Initialize the WebSocketManager class."""
        self.active_connections: List[WebSocket] = []
        self.sender_tasks: Dict[WebSocket, asyncio.Task] = {}
        self.message_queues: Dict[WebSocket, asyncio.Queue] = {}

    async def start_sender(self, websocket: WebSocket):
        """Start the sender task."""
        queue = self.message_queues.get(websocket)
        if not queue:
            return

        while True:
            try:
                message = await queue.get()
                if message is None:  # Shutdown signal
                    break
                    
                if websocket in self.active_connections:
                    if message == "ping":
                        await websocket.send_text("pong")
                    else:
                        await websocket.send_text(message)
                else:
                    break
            except Exception as e:
                print(f"Error in sender task: {e}")
                break

    async def connect(self, websocket: WebSocket):
        """Connect a websocket."""
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            self.message_queues[websocket] = asyncio.Queue()
            self.sender_tasks[websocket] = asyncio.create_task(
                self.start_sender(websocket))
        except Exception as e:
            print(f"Error connecting websocket: {e}")
            if websocket in self.active_connections:
                await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a websocket."""
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                
                # Cancel sender task if it exists
                if websocket in self.sender_tasks:
                    try:
                        self.sender_tasks[websocket].cancel()
                        await self.message_queues[websocket].put(None)
                    except Exception as e:
                        logger.error(f"Error canceling sender task: {e}")
                    finally:
                        # Always try to clean up regardless of errors
                        if websocket in self.sender_tasks:
                            del self.sender_tasks[websocket]
                
                # Clean up message queue
                if websocket in self.message_queues:
                    del self.message_queues[websocket]
                
                # Finally close the WebSocket
                try:
                    await websocket.close()
                except Exception as e:
                    logger.info(f"WebSocket already closed: {e}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnection: {e}")
            # Still try to close the connection if possible
            try:
                await websocket.close()
            except Exception:
                pass  # If this fails too, there's nothing more we can do

    async def start_streaming(self, task, report_type, report_source, source_urls, document_urls, tone, websocket, headers=None, query_domains=[], mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], max_search_results=None, industry_direction_plan=None, user_id=None):
        """Start streaming the output."""
        tone = Tone[tone]
        # add customized JSON config file path here
        config_path = os.environ.get("CONFIG_PATH", "default")

        # Pass MCP parameters to run_agent
        report = await run_agent(
            task, report_type, report_source, source_urls, document_urls, tone, websocket, 
            headers=headers, query_domains=query_domains, config_path=config_path,
            mcp_enabled=mcp_enabled, mcp_strategy=mcp_strategy, mcp_configs=mcp_configs,
            max_search_results=max_search_results,
            industry_direction_plan=industry_direction_plan,
            user_id=user_id,
        )
        return report

async def run_agent(task, report_type, report_source, source_urls, document_urls, tone: Tone, websocket, stream_output=stream_output, headers=None, query_domains=[], config_path="", return_researcher=False, mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], max_search_results=None, industry_direction_plan=None, run_id=None, user_id=None):
    """Run the agent."""    
    # Reuse the request-scoped log handler when the WebSocket entrypoint already
    # created one, otherwise create one for direct/backend-only calls.
    logs_handler = (
        websocket
        if isinstance(websocket, CustomLogsHandler)
        else CustomLogsHandler(websocket, task)
    )

    # MCP configuration is passed via mcp_configs/mcp_strategy parameters to
    # the researcher constructors.  _process_mcp_configs() in agent.py handles
    # the actual setup without touching global env vars.
    if mcp_enabled and mcp_configs:
        print(f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)")
        await logs_handler.send_json({
            "type": "logs",
            "content": "mcp_init",
            "output": f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)"
        })

    # Initialize researcher based on report type
    if report_type == "rivalens":
        state = await run_rivalens_task(
            query=task, 
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            stream_output=stream_output, 
            tone=tone, 
            headers=headers,
            industry_direction_plan=industry_direction_plan,
            industry_directions_confirmed=bool(industry_direction_plan),
            run_id=run_id,
            user_id=user_id,
        )
        report = build_rivalens_structured_response(
            state if isinstance(state, dict) else {"report": str(state)},
            fallback_run_id=run_id,
        )

    else:
        researcher = BasicReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # Use logs_handler instead of raw websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            max_search_results=max_search_results,
        )
        report = await researcher.run()

    if report_type != "rivalens" and return_researcher:
        return report, researcher.research_engine
    else:
        return report
