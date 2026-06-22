import json
import os
import asyncio
from typing import Dict, List, Any
import time
import logging
import sys
import warnings
from pathlib import Path

# Suppress Pydantic V2 migration warnings
warnings.filterwarnings("ignore", message="Valid config keys have changed in V2")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile, BackgroundTasks, HTTPException, Depends, Header
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

# Add the parent directory to sys.path to make sure we can import from server
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from server.websocket_manager import WebSocketManager
from server.server_utils import (
    get_config_dict, sanitize_filename,
    update_environment_variables, handle_file_upload, handle_file_deletion,
    execute_rivalens_workflow, handle_websocket_communication,
    resolve_uploaded_file_paths,
)

from server.websocket_manager import run_agent
from rivalens.report_export import generate_report_files
from rivalens.research.utils.enum import Tone
from chat.chat import ChatAgentWithMemory
from rivalens.agents.industry_direction import (
    IndustryDirectionSkill,
    validate_query_no_direction_limits,
)
from rivalens.schema import IndustryDirectionPlanPayload

from server.auth import (
    AUTH_COOKIE_NAME,
    AuthResponse,
    InvalidTokenError,
    LoginRequest,
    RegisterRequest,
    UpdateCurrentUserRequest,
    UserPublic,
    create_access_token,
    decode_access_token,
    hash_password,
    to_public_user,
    verify_password,
)
from server.report_store import ReportStore
from server.evidence_vector_store import EvidenceVectorStore
from server.rivalens_runner import set_trace_store
from server.session_store import SessionStore
from server.trace_store import TraceStore
from server.user_store import DuplicateEmailError, UserStore

# Setup logging
logger = logging.getLogger(__name__)

# Don't override parent logger settings
logger.propagate = True

# Silence uvicorn reload logs
logging.getLogger("uvicorn.supervisors.ChangeReload").setLevel(logging.WARNING)

# Models


class ResearchRequest(BaseModel):
    task: str
    report_type: str
    report_source: str
    file_paths: List[str] = Field(default_factory=list)
    tone: str
    headers: dict | None = None
    repo_name: str
    branch_name: str
    generate_in_background: bool = True


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # Allow extra fields in the request
    
    report: str
    messages: List[Dict[str, Any]]
    research_id: str | None = None
    trace_summary: Dict[str, Any] | None = None
    assessments: Dict[str, Any] | None = None
    evidence_index: List[Dict[str, Any]] | None = None
    analysis_claims: List[Dict[str, Any]] | None = None
    claim_support_reviews: List[Dict[str, Any]] | None = None
    competitor_knowledge: List[Dict[str, Any]] | None = None
    state: Dict[str, Any] | None = None


class IndustryDirectionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    task: str
    competitors: List[Dict[str, Any]] = []
    custom_directions: List[str] = []
    selected_direction_ids: List[str] | None = None
    confirmed: bool = False


user_store = UserStore()
trace_store = TraceStore()
set_trace_store(trace_store)
session_store = SessionStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    os.makedirs("outputs", exist_ok=True)
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
    
    # Mount frontend static files
    frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
    if os.path.exists(frontend_path):
        app.mount("/site", StaticFiles(directory=frontend_path), name="frontend")
        logger.debug(f"Frontend mounted from: {frontend_path}")
        
        # Also mount the static directory directly for assets referenced as /static/
        static_path = os.path.join(frontend_path, "static")
        if os.path.exists(static_path):
            app.mount("/static", StaticFiles(directory=static_path), name="static")
            logger.debug(f"Static assets mounted from: {static_path}")
    else:
        logger.warning(f"Frontend directory not found: {frontend_path}")

    # Apply any pending database migrations before starting the API.
    # Set RIVALENS_AUTO_MIGRATE=false to skip.
    if os.getenv("RIVALENS_AUTO_MIGRATE", "true").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            from alembic.config import Config as AlembicConfig
            from alembic.command import upgrade as alembic_upgrade

            alembic_cfg = AlembicConfig(
                os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
            )
            alembic_upgrade(alembic_cfg, "head")
            logger.info("Database migrations applied")
        except Exception:
            logger.exception("Database migration failed")
            raise

    # 按需一次性导入旧 JSON 报告；默认关闭，避免已删除报告在重启后被回填。
    try:
        imported = await report_store.migrate_from_json()
        if imported:
            logger.info("Migrated %d reports from legacy JSON", imported)
    except Exception:
        logger.exception("Legacy report migration failed")

    logger.info("Rivalens API ready")
    yield
    # Shutdown
    logger.info("Research API shutting down")

# App initialization
app = FastAPI(lifespan=lifespan)

# Configure allowed origins for CORS
allowed_origins_env = os.getenv("CORS_ALLOW_ORIGINS")
ALLOWED_ORIGINS = (
    [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
    if allowed_origins_env
    else [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
)

# Standard JSON response - no custom MongoDB encoding needed

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use default JSON response class

# Mount static files for frontend
# Get the absolute path to the frontend directory
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

# Mount static directories
app.mount("/static", StaticFiles(directory=os.path.join(frontend_dir, "static")), name="static")
app.mount("/site", StaticFiles(directory=frontend_dir), name="site")

# WebSocket manager
manager = WebSocketManager()

report_store = ReportStore()
evidence_vector_store = EvidenceVectorStore()

# Constants
DOC_PATH = os.getenv("DOC_PATH", "./my-docs")
OUTPUTS_DIR = Path("outputs")


def _extract_rivalens_report_text(report_information: Any) -> str:
    if isinstance(report_information, str):
        return report_information
    if isinstance(report_information, dict):
        return str(report_information.get("report", ""))
    if isinstance(report_information, (tuple, list)):
        return str(report_information[0]) if report_information else ""
    return str(report_information)


def _report_has_evidence(report: Dict[str, Any]) -> bool:
    if isinstance(report.get("evidence_index"), list) and report["evidence_index"]:
        return True
    state = report.get("state")
    return bool(isinstance(state, dict) and state.get("evidence_items"))


async def _index_report_evidence(research_id: str, report: Dict[str, Any]) -> None:
    if not _report_has_evidence(report):
        return
    try:
        count = await asyncio.to_thread(
            evidence_vector_store.index_report,
            research_id,
            report,
        )
        logger.info("Indexed %d EvidenceItem vectors for report %s", count, research_id)
    except Exception:
        logger.exception("Failed to index EvidenceItem vectors for report %s", research_id)


async def _delete_report_evidence(research_id: str) -> None:
    try:
        await asyncio.to_thread(evidence_vector_store.delete_scope, research_id)
    except Exception:
        logger.exception("Failed to delete EvidenceItem vectors for report %s", research_id)


def _build_report_store_record(
    research_id: str,
    research_request: ResearchRequest,
    status: str,
    *,
    response: Dict[str, Any] | None = None,
    existing: Dict[str, Any] | None = None,
    error: str | None = None,
) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    existing = existing or {}
    response = response or {}
    report_text = str(response.get("report") or existing.get("answer") or "")

    ordered_data = existing.get("orderedData")
    if not isinstance(ordered_data, list):
        ordered_data = []
    if status == "completed" and not ordered_data:
        ordered_data = [
            {"type": "question", "content": research_request.task},
            {"type": "basic", "content": report_text},
        ]

    chat_messages = existing.get("chatMessages")
    if not isinstance(chat_messages, list):
        chat_messages = []

    record = {
        **existing,
        "id": research_id,
        "question": existing.get("question") or research_request.task,
        "answer": report_text,
        "orderedData": ordered_data,
        "chatMessages": chat_messages,
        "timestamp": now_ms,
        "status": status,
        "report_type": research_request.report_type,
        "report_source": research_request.report_source,
        "tone": research_request.tone,
    }

    for key in (
        "celery_task_id",
        "run_id",
        "research_information",
        "docx_path",
        "pdf_path",
        "markdown_path",
        "html_path",
        "artifacts",
        "report_artifacts",
        "trace_summary",
        "assessments",
        "evidence_index",
        "analysis_claims",
        "claim_support_reviews",
        "competitor_knowledge",
        "state",
    ):
        if key in response:
            record[key] = response[key]

    if error is not None:
        record["error"] = error
    elif "error" in record:
        record.pop("error")

    return record


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _enqueue_report_generation_task(
    research_request: ResearchRequest,
    research_id: str,
) -> str | None:
    if not _env_flag("RIVALENS_CELERY_ENABLED", default=False):
        return None
    try:
        from backend.server.celery_tasks import generate_report_task

        async_result = generate_report_task.delay(
            research_request.model_dump(mode="json"),
            research_id,
        )
        return str(async_result.id)
    except Exception:
        logger.exception(
            "Failed to enqueue Celery report generation task %s; falling back",
            research_id,
        )
        return None


async def _upsert_report_generation_record(
    research_id: str,
    research_request: ResearchRequest,
    status: str,
    *,
    response: Dict[str, Any] | None = None,
    error: str | None = None,
) -> Dict[str, Any]:
    existing = await report_store.get_report(research_id)
    record = _build_report_store_record(
        research_id,
        research_request,
        status,
        response=response,
        existing=existing,
        error=error,
    )
    await report_store.upsert_report(research_id, record)
    return record


async def write_report_and_store(research_request: ResearchRequest, research_id: str) -> Dict[str, Any]:
    try:
        response = await write_report(research_request, research_id)
        record = await _upsert_report_generation_record(
            research_id,
            research_request,
            "completed",
            response=response,
        )
        await _index_report_evidence(research_id, record)
        return response
    except Exception as exc:
        await _upsert_report_generation_record(
            research_id,
            research_request,
            "failed",
            error=str(exc),
        )
        raise

# Startup event


# Lifespan events now handled in the lifespan context manager above


# Routes
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend HTML page."""
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
    index_path = os.path.join(frontend_dir, "index.html")
    
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    return HTMLResponse(content=content)


def _build_auth_response(user: Dict[str, Any]) -> AuthResponse:
    access_token, expires_in = create_access_token(str(user["id"]))
    return AuthResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=to_public_user(user),
    )


def _require_current_user(
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="需要登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(authorization.removeprefix("Bearer ").strip())
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = user_store.get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="账户已停用")
    return user


def _optional_websocket_user(websocket: WebSocket) -> Dict[str, Any] | None:
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        return None
    user = user_store.get_user_by_id(payload["sub"])
    if user is None or user["status"] != "active":
        return None
    return user


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register_user(request: RegisterRequest):
    try:
        user = user_store.create_user(
            email=request.email,
            display_name=request.display_name,
            password_hash=hash_password(request.password.get_secret_value()),
        )
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _build_auth_response(user)


@app.post("/api/auth/login", response_model=AuthResponse)
def login_user(request: LoginRequest):
    user = user_store.get_user_by_email(request.email)
    if user is None or not verify_password(
        request.password.get_secret_value(),
        user["password_hash"],
    ):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="账户已停用")

    updated_user = user_store.record_successful_login(user["id"]) or user
    return _build_auth_response(updated_user)


@app.get("/api/auth/me", response_model=UserPublic)
def get_current_user(user: Dict[str, Any] = Depends(_require_current_user)):
    return to_public_user(user)


@app.patch("/api/auth/me", response_model=UserPublic)
def update_current_user(
    request: UpdateCurrentUserRequest,
    user: Dict[str, Any] = Depends(_require_current_user),
):
    updated_user = user_store.update_user_profile(
        user["id"],
        display_name=request.display_name,
    )
    if updated_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return to_public_user(updated_user)


# ── Session API ──────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    title: str = "新对话"


class UpdateSessionMemoryRequest(BaseModel):
    messages: list[dict[str, Any]] = []


class UpdateSessionMetaRequest(BaseModel):
    title: str | None = None


class AppendMessageRequest(BaseModel):
    message: dict[str, Any]


@app.get("/api/sessions")
def list_sessions(
    user: dict[str, Any] = Depends(_require_current_user),
):
    sessions = session_store.get_sidebar_sessions(user["id"])
    return {"sessions": sessions}


@app.post("/api/sessions", status_code=201)
def create_session(
    request: CreateSessionRequest,
    user: dict[str, Any] = Depends(_require_current_user),
):
    session = session_store.create_session(user["id"], title=request.title)
    return {"session": session}


@app.get("/api/sessions/{session_id}")
def get_session(
    session_id: str,
    user: dict[str, Any] = Depends(_require_current_user),
):
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != str(user["id"]) and user["role"] != "admin":
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session": session}


@app.put("/api/sessions/{session_id}/memory")
def update_session_memory(
    session_id: str,
    request: UpdateSessionMemoryRequest,
    user: dict[str, Any] = Depends(_require_current_user),
):
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    session_store.update_session_memory(session_id, request.messages)
    return {"success": True}


@app.post("/api/sessions/{session_id}/messages")
def append_message(
    session_id: str,
    request: AppendMessageRequest,
    user: dict[str, Any] = Depends(_require_current_user),
):
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    session_store.append_message(session_id, request.message)
    return {"success": True}


@app.patch("/api/sessions/{session_id}")
def update_session_meta(
    session_id: str,
    request: UpdateSessionMetaRequest,
    user: dict[str, Any] = Depends(_require_current_user),
):
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    kwargs = {}
    if request.title is not None:
        kwargs["title"] = request.title
    if kwargs:
        session_store.update_session_meta(session_id, **kwargs)
    return {"success": True}


@app.delete("/api/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: dict[str, Any] = Depends(_require_current_user),
):
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != str(user["id"]) and user["role"] != "admin":
        raise HTTPException(status_code=404, detail="会话不存在")
    deleted = session_store.delete_session(session_id)
    return {"success": deleted}


@app.get("/api/trace/runs/{run_id}")
def get_trace_run(
    run_id: str,
    user: Dict[str, Any] = Depends(_require_current_user),
):
    if not trace_store.enabled:
        raise HTTPException(status_code=503, detail="流程溯源持久化未启用")
    try:
        trace = trace_store.get_run_trace(run_id)
    except Exception as exc:
        logger.exception("Failed to read Rivalens trace %s", run_id)
        raise HTTPException(status_code=503, detail="流程溯源数据暂时不可用") from exc
    if trace is None:
        raise HTTPException(status_code=404, detail="未找到流程溯源记录")
    owner_id = trace["run"].get("user_id")
    if (
        owner_id
        and str(owner_id) != str(user["id"])
        and user["role"] != "admin"
    ):
        raise HTTPException(status_code=404, detail="未找到流程溯源记录")
    return trace


@app.get("/report/{research_id}")
async def read_report(request: Request, research_id: str):
    docx_path = os.path.join('outputs', f"{research_id}.docx")
    if not os.path.exists(docx_path):
        return {"message": "Report not found."}
    return FileResponse(docx_path)


def _resolve_output_download_path(file_path: str) -> Path:
    clean_path = file_path.strip().lstrip("/")
    if clean_path.startswith("outputs/"):
        clean_path = clean_path[len("outputs/"):]
    if not clean_path:
        raise HTTPException(status_code=400, detail="Missing output file path")

    output_dir = OUTPUTS_DIR.resolve()
    target_path = (output_dir / clean_path).resolve()
    try:
        target_path.relative_to(output_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output file path")

    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")
    return target_path


@app.get("/api/download/{file_path:path}")
async def download_output_file(file_path: str):
    target_path = _resolve_output_download_path(file_path)
    return FileResponse(
        target_path,
        filename=target_path.name,
        media_type="application/octet-stream",
    )


# 报告路由仍使用文件存储。
@app.get("/api/reports")
async def get_all_reports(report_ids: str = None):
    report_ids_list = report_ids.split(",") if report_ids else None
    reports = await report_store.list_reports(report_ids_list)
    return {"reports": reports}


@app.get("/api/reports/{research_id}")
async def get_report_by_id(research_id: str):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}


@app.get("/api/reports/{research_id}/status")
async def get_report_status(research_id: str):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {
        "research_id": research_id,
        "status": report.get("status") or ("completed" if report.get("answer") else "unknown"),
        "celery_task_id": report.get("celery_task_id"),
        "timestamp": report.get("timestamp"),
        "error": report.get("error"),
        "artifacts": report.get("artifacts"),
        "report_artifacts": report.get("report_artifacts"),
        "trace_summary": report.get("trace_summary"),
    }


@app.post("/api/reports")
async def create_or_update_report(request: Request):
    try:
        data = await request.json()
        research_id = data.get("id", "temp_id")

        now_ms = int(time.time() * 1000)
        existing = await report_store.get_report(research_id)
        incoming_timestamp = data.get("timestamp")
        timestamp = incoming_timestamp if isinstance(incoming_timestamp, int) else now_ms
        if existing and isinstance(existing.get("timestamp"), int):
            timestamp = max(timestamp, existing["timestamp"])

        report = {
            **(existing or {}),
            "id": research_id,
            "question": data.get("question"),
            "answer": data.get("answer"),
            "orderedData": data.get("orderedData") or [],
            "chatMessages": data.get("chatMessages") or [],
            "timestamp": timestamp,
        }
        for key in (
            "trace_summary",
            "assessments",
            "evidence_index",
            "analysis_claims",
            "claim_support_reviews",
            "competitor_knowledge",
            "state",
        ):
            if key in data:
                report[key] = data[key]

        await report_store.upsert_report(research_id, report)
        await _index_report_evidence(research_id, report)
        return {"success": True, "id": research_id}
    except Exception as e:
        logger.error(f"Error processing report creation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/reports/{research_id}")
async def update_report(research_id: str, request: Request):
    existing = await report_store.get_report(research_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Report not found")

    data = await request.json()
    now_ms = int(time.time() * 1000)

    updated = {
        **existing,
        **{k: v for k, v in data.items() if v is not None},
        "id": research_id,
        "timestamp": now_ms,
    }

    await report_store.upsert_report(research_id, updated)
    await _index_report_evidence(research_id, updated)
    return {"success": True, "id": research_id}


@app.delete("/api/reports/{research_id}")
async def delete_report(research_id: str):
    existed = await report_store.delete_report(research_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Report not found")
    await _delete_report_evidence(research_id)
    return {"success": True}


@app.get("/api/reports/{research_id}/chat")
async def get_report_chat(research_id: str):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"chatMessages": report.get("chatMessages") or []}


@app.post("/api/reports/{research_id}/chat")
async def add_report_chat_message(research_id: str, request: Request):
    report = await report_store.get_report(research_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    message = await request.json()
    chat_messages = report.get("chatMessages") or []
    if isinstance(chat_messages, list):
        chat_messages = [*chat_messages, message]
    else:
        chat_messages = [message]

    now_ms = int(time.time() * 1000)
    updated = {
        **report,
        "chatMessages": chat_messages,
        "timestamp": now_ms,
    }

    await report_store.upsert_report(research_id, updated)
    return {"success": True, "id": research_id}


async def write_report(research_request: ResearchRequest, research_id: str = None):
    report_information = await run_agent(
        task=research_request.task,
        report_type=research_request.report_type,
        report_source=research_request.report_source,
        source_urls=[],
        document_urls=[],
        tone=Tone[research_request.tone],
        websocket=None,
        stream_output=None,
        headers=research_request.headers,
        query_domains=[],
        config_path="",
        return_researcher=True,
        run_id=research_id,
        files=research_request.file_paths,
    )

    if research_request.report_type != "rivalens":
        report, researcher = report_information
        artifacts = await generate_report_files(
            report,
            research_id,
            quote_paths=True,
            include_legacy_md_key=True,
        )
        response = {
            "research_id": research_id,
            "research_information": {
                "source_urls": researcher.get_source_urls(),
                "research_costs": researcher.get_costs(),
                "visited_urls": list(researcher.visited_urls),
                "research_images": researcher.get_research_images(),
                # "research_sources": researcher.get_research_sources(),  # Raw content of sources may be very large
            },
            "report": report,
            "docx_path": artifacts["docx"],
            "pdf_path": artifacts["pdf"],
            "markdown_path": artifacts["markdown"],
            "html_path": artifacts["html"],
            "artifacts": artifacts,
        }
    else:
        report = _extract_rivalens_report_text(report_information)
        artifacts = await generate_report_files(
            report,
            research_id,
            quote_paths=True,
            include_legacy_md_key=True,
        )
        report_artifacts = dict(report_information.get("report_artifacts") or {}) if isinstance(report_information, dict) else {}
        report_artifacts.update(artifacts)
        response = {
            "research_id": research_id,
            "run_id": report_information.get("run_id", research_id) if isinstance(report_information, dict) else research_id,
            "report": report,
            "docx_path": artifacts["docx"],
            "pdf_path": artifacts["pdf"],
            "markdown_path": artifacts["markdown"],
            "html_path": artifacts["html"],
            "artifacts": artifacts,
            "report_artifacts": report_artifacts,
            "trace_summary": report_information.get("trace_summary", {}) if isinstance(report_information, dict) else {},
            "assessments": report_information.get("assessments", {}) if isinstance(report_information, dict) else {},
            "evidence_index": report_information.get("evidence_index", []) if isinstance(report_information, dict) else [],
            "analysis_claims": report_information.get("analysis_claims", []) if isinstance(report_information, dict) else [],
            "claim_support_reviews": (
                report_information.get("claim_support_reviews")
                or (report_information.get("assessments", {}) or {}).get("claim_support_reviews", [])
            ) if isinstance(report_information, dict) else [],
            "competitor_knowledge": report_information.get("competitor_knowledge", []) if isinstance(report_information, dict) else [],
            "state": report_information.get("state", {}) if isinstance(report_information, dict) else {},
        }

    return response

@app.post("/report/")
async def generate_report(research_request: ResearchRequest, background_tasks: BackgroundTasks):
    research_request.file_paths = resolve_uploaded_file_paths(
        research_request.file_paths
        if research_request.report_source in {"local", "hybrid"}
        else [],
        DOC_PATH,
    )
    research_id = sanitize_filename(f"task_{int(time.time())}_{research_request.task}")
    await _upsert_report_generation_record(research_id, research_request, "running")

    if research_request.generate_in_background:
        celery_task_id = _enqueue_report_generation_task(research_request, research_id)
        if celery_task_id:
            await _upsert_report_generation_record(
                research_id,
                research_request,
                "queued",
                response={"celery_task_id": celery_task_id},
            )
            return {
                "message": "Your report is queued for background generation.",
                "research_id": research_id,
                "status": "queued",
                "celery_task_id": celery_task_id,
                "status_url": f"/api/reports/{research_id}/status",
            }
        background_tasks.add_task(write_report_and_store, research_request=research_request, research_id=research_id)
        return {"message": "Your report is being generated in the background. Please check back later.",
                "research_id": research_id,
                "status": "running",
                "status_url": f"/api/reports/{research_id}/status"}
    else:
        response = await write_report_and_store(research_request, research_id)
        return response


@app.get("/files/")
async def list_files():
    root = Path(DOC_PATH).resolve()
    root.mkdir(parents=True, exist_ok=True)
    files = sorted(path.name for path in root.iterdir() if path.is_file())
    file_paths = [str(Path(DOC_PATH) / filename) for filename in files]
    print(f"Files in {root}: {files}")
    return {"files": files, "file_paths": file_paths}


@app.get("/files/{filename}")
async def download_uploaded_file(filename: str):
    file_path = Path(
        resolve_uploaded_file_paths([os.path.basename(filename)], DOC_PATH)[0]
    )
    return FileResponse(file_path, filename=file_path.name)


@app.post("/api/rivalens")
async def run_rivalens():
    return await execute_rivalens_workflow(manager)


@app.post("/api/industry-directions")
async def preview_industry_directions(request: IndustryDirectionRequest):
    competitor_names = [
        c.get("name", "") for c in (request.competitors or [])
    ]
    limit_error = validate_query_no_direction_limits(request.task, competitor_names)
    if limit_error:
        raise HTTPException(status_code=422, detail=limit_error)

    plan = IndustryDirectionSkill().build_plan(
        query=request.task,
        competitors=request.competitors,
        user_directions=request.custom_directions,
        selected_direction_ids=request.selected_direction_ids,
        user_confirmed=request.confirmed,
    )
    # Validate through Pydantic before returning — ensures the frontend
    # always receives a well-formed IndustryDirectionPlan.
    try:
        validated = IndustryDirectionPlanPayload(**plan)
        return {"plan": validated.model_dump()}
    except Exception as e:
        logger.error(f"IndustryDirectionPlan validation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Plan validation error: {str(e)}",
        )


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    return await handle_file_upload(file, DOC_PATH)


@app.delete("/files/{filename}")
async def delete_file(filename: str):
    return await handle_file_deletion(filename, DOC_PATH)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    user = _optional_websocket_user(websocket)
    websocket.scope.setdefault("rivalens", {})["user_id"] = (
        str(user["id"]) if user else None
    )
    await manager.connect(websocket)
    try:
        await handle_websocket_communication(websocket, manager, report_store=report_store)
    except WebSocketDisconnect as e:
        # Disconnect with more detailed logging about the WebSocket disconnect reason
        logger.info(f"WebSocket disconnected with code {e.code} and reason: '{e.reason}'")
        await manager.disconnect(websocket)
    except Exception as e:
        # More general exception handling
        logger.error(f"Unexpected WebSocket error: {str(e)}")
        await manager.disconnect(websocket)

@app.post("/api/chat")
async def chat(chat_request: ChatRequest):
    """Process a chat request with a report and message history.

    Args:
        chat_request: ChatRequest object containing report text and message history

    Returns:
        JSON response with the assistant's message and any tool usage metadata
    """
    try:
        logger.info(f"Received chat request with {len(chat_request.messages)} messages")
        report_record = None
        if chat_request.research_id:
            try:
                report_record = await report_store.get_report(chat_request.research_id)
            except Exception:
                logger.exception("Failed to load report context for chat")

        evidence_context = {
            "research_id": chat_request.research_id or (report_record or {}).get("id"),
            "run_id": (report_record or {}).get("run_id"),
            "trace_summary": chat_request.trace_summary or (report_record or {}).get("trace_summary") or {},
            "assessments": chat_request.assessments or (report_record or {}).get("assessments") or {},
            "evidence_index": chat_request.evidence_index or (report_record or {}).get("evidence_index") or [],
            "analysis_claims": chat_request.analysis_claims or (report_record or {}).get("analysis_claims") or [],
            "claim_support_reviews": (
                chat_request.claim_support_reviews
                or (report_record or {}).get("claim_support_reviews")
                or ((report_record or {}).get("assessments") or {}).get("claim_support_reviews")
                or []
            ),
            "competitor_knowledge": chat_request.competitor_knowledge or (report_record or {}).get("competitor_knowledge") or [],
            "state": chat_request.state or (report_record or {}).get("state") or {},
        }

        # Create chat agent with the report
        chat_agent = ChatAgentWithMemory(
            report=chat_request.report or (report_record or {}).get("answer", ""),
            config_path="default",
            headers=None,
            evidence_context=evidence_context,
        )

        # Process the chat and get response with metadata
        response_content, tool_calls_metadata = await chat_agent.chat(chat_request.messages, None)
        logger.info(f"response_content: {response_content}")
        logger.info(f"Got chat response of length: {len(response_content) if response_content else 0}")
        
        if tool_calls_metadata:
            logger.info(f"Tool calls used: {json.dumps(tool_calls_metadata)}")

        # Format response as a ChatMessage object with role, content, timestamp and metadata
        response_message = {
            "role": "assistant",
            "content": response_content,
            "timestamp": int(time.time() * 1000),  # Current time in milliseconds
            "metadata": {
                "tool_calls": tool_calls_metadata
            } if tool_calls_metadata else None
        }

        logger.info(f"Returning formatted response: {json.dumps(response_message)[:100]}...")
        return {"response": response_message}
    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}", exc_info=True)
        return {"error": str(e)}

