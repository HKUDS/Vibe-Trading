#!/usr/bin/env python3
"""Vibe-Trading API Server - RESTful API for finance research and backtesting.

V5: ReAct Agent + async /run + CORS env + SSE tool events.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
import csv
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Security, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from rich.console import Console

from src.ui_services import build_run_analysis, load_run_context

# UTF-8 on Windows
import sys as _sys
for _s in ("stdout", "stderr"):
    _r = getattr(getattr(_sys, _s, None), "reconfigure", None)
    if callable(_r):
        _r(encoding="utf-8", errors="replace")

RUNS_DIR = Path(__file__).resolve().parent / "runs"
SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"
UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB

# Rich console for colored logs
console = Console()


# ============================================================================
# Pydantic Models
# ============================================================================

class Artifact(BaseModel):
    """Artifact file metadata."""
    name: str = Field(..., description="File name")
    path: str = Field(..., description="File path")
    type: str = Field(..., description="File type: csv, json, txt, etc.")
    size: int = Field(..., description="Size in bytes")
    exists: bool = Field(..., description="Whether the file exists")


class BacktestMetrics(BaseModel):
    """Backtest summary metrics."""
    model_config = {"extra": "allow"}

    final_value: float = Field(..., description="Ending portfolio value")
    total_return: float = Field(..., description="Total return")
    annual_return: float = Field(..., description="Annualized return")
    max_drawdown: float = Field(..., description="Max drawdown")
    sharpe: float = Field(..., description="Sharpe ratio")
    win_rate: float = Field(..., description="Win rate")
    trade_count: int = Field(..., description="Number of trades")



class RAGSelection(BaseModel):
    """RAG routing result."""
    selected_api: str = Field(..., description="Selected API code")
    selected_name: str = Field(..., description="Selected API name")
    selected_score: float = Field(..., description="Match score")


class RunInfo(BaseModel):
    """Compact run row for list views."""
    run_id: str
    status: str
    created_at: str
    prompt: Optional[str] = None
    total_return: Optional[float] = None
    sharpe: Optional[float] = None
    codes: List[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class RunResponse(BaseModel):
    """API response payload for a single run."""

    status: str = Field(..., description="Run status: success, failed, aborted")
    run_id: str = Field(..., description="Run identifier")
    elapsed_seconds: float = Field(..., description="Execution time in seconds")
    reason: Optional[str] = Field(None, description="Failure reason when available")

    planner_output: Optional[Dict[str, Any]] = Field(None, description="Planner output")
    strategy_spec: Optional[Dict[str, Any]] = Field(None, description="Strategy specification")
    rag_selection: Optional[RAGSelection] = Field(None, description="Selected RAG metadata")

    metrics: Optional[BacktestMetrics] = Field(None, description="Backtest metrics")
    artifacts: List[Artifact] = Field(default_factory=list, description="Run artifacts")

    equity_curve: Optional[List[Dict[str, Any]]] = Field(None, description="Equity preview")
    trade_log: Optional[List[Dict[str, Any]]] = Field(None, description="Trade preview")

    artifacts_equity_csv: Optional[List[Dict[str, Any]]] = Field(None, description="Full equity rows")
    artifacts_metrics_csv: Optional[List[Dict[str, Any]]] = Field(None, description="Full metrics rows")
    artifacts_trades_csv: Optional[List[Dict[str, Any]]] = Field(None, description="Full trade rows")
    validation: Optional[Dict[str, Any]] = Field(None, description="Statistical validation results")

    run_directory: str = Field(..., description="Run directory path")
    run_stage: Optional[str] = Field(None, description="UI-facing run stage")
    run_context: Optional[Dict[str, Any]] = Field(None, description="Normalized request context")
    price_series: Optional[Dict[str, List[Dict[str, Any]]]] = Field(None, description="Grouped OHLC series")
    indicator_series: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = Field(
        None,
        description="Grouped indicator overlays",
    )
    trade_markers: Optional[List[Dict[str, Any]]] = Field(None, description="Trade markers for charts")
    run_logs: Optional[List[Dict[str, Any]]] = Field(None, description="Structured stdout/stderr lines")


class HealthResponse(BaseModel):
    """Health check payload."""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
    timestamp: str = Field(..., description="Server timestamp")


# ---- V4 Session Models ----

class CreateSessionRequest(BaseModel):
    """Create session request body."""
    title: str = Field("", description="Session title")
    config: Optional[Dict[str, Any]] = Field(None, description="Session config")


class SessionResponse(BaseModel):
    """Session record."""
    session_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    last_attempt_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Send chat message: natural-language strategy description."""
    content: str = Field(..., description="Natural language strategy description", min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    """Stored chat message."""
    message_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    linked_attempt_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None



# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Vibe-Trading API",
    description="Vibe-Trading API: natural-language finance research, backtesting, and swarm workflows",
    version="5.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS: override with CORS_ORIGINS (comma-separated)
_CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:8000,"
    "http://127.0.0.1:3000,http://127.0.0.1:5173,http://127.0.0.1:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _run_startup_preflight() -> None:
    """Run preflight checks on server startup."""
    from src.preflight import run_preflight

    run_preflight(console)


# ============================================================================
# API Key Authentication
# ============================================================================

_security = HTTPBearer(auto_error=False)
_API_KEY = os.getenv("API_AUTH_KEY")


async def require_auth(
    cred: HTTPAuthorizationCredentials = Security(_security),
) -> None:
    """Validate Bearer token against API_AUTH_KEY environment variable.

    If API_AUTH_KEY is not set, authentication is skipped (dev mode).
    Only write endpoints (POST/PUT/DELETE/PATCH) use this dependency.

    Args:
        cred: HTTP Bearer credentials extracted from the Authorization header.

    Raises:
        HTTPException: 401 when API_AUTH_KEY is set but the token is missing or wrong.
    """
    if not _API_KEY:
        return
    if not cred or cred.credentials != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ============================================================================
# Workflow Factory
# ============================================================================

# ============================================================================
# Helper Functions
# ============================================================================

def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON from disk if present."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _load_csv_to_dict(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load CSV rows into a list of dictionaries."""
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
        if limit is not None:
            rows = rows[:limit]
        return rows
    except Exception:
        return []



def _build_response_from_run_dir(run_dir: Path, elapsed: float, *, include_analysis: bool = False) -> RunResponse:
    """Build a run response from a persisted run directory."""
    run_id = run_dir.name

    response = RunResponse(
        status="unknown",
        run_id=run_id,
        elapsed_seconds=elapsed,
        run_directory=str(run_dir),
    )

    state_data = _load_json_file(run_dir / "state.json")
    if state_data:
        state_status = str(state_data.get("status") or "").lower()
        if state_status == "success":
            response.status = "success"
        elif state_status == "failed":
            response.status = "failed"
            response.reason = state_data.get("reason", "")
        else:
            response.status = state_status or "unknown"
    else:
        response.status = "unknown"

    planner_path = run_dir / "planner_output.json"
    response.planner_output = _load_json_file(planner_path)

    design_path = run_dir / "design_spec.json"
    response.strategy_spec = _load_json_file(design_path)

    rag_path = run_dir / "rag_metadata.json"
    rag_data = _load_json_file(rag_path)
    if rag_data:
        response.rag_selection = RAGSelection(
            selected_api=rag_data.get("selected_api") or rag_data.get("api_code", ""),
            selected_name=rag_data.get("selected_name") or rag_data.get("api_name", ""),
            selected_score=float(rag_data.get("selected_score") or rag_data.get("score", 0.0)),
        )

    metrics_path = run_dir / "artifacts" / "metrics.csv"
    if metrics_path.exists():
        metrics_dict_list = _load_csv_to_dict(metrics_path, limit=1)
        if metrics_dict_list:
            row = metrics_dict_list[0]
            try:
                # Pass ALL CSV columns to BacktestMetrics (extra="allow")
                parsed: dict = {}
                for k, v in row.items():
                    if not k or not v:
                        continue
                    try:
                        parsed[k] = int(float(v)) if k == "trade_count" or k == "max_consecutive_loss" else float(v)
                    except (ValueError, TypeError):
                        continue
                if "final_value" in parsed:
                    response.metrics = BacktestMetrics(**parsed)
            except (ValueError, TypeError):
                pass


    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists():
        for file_path in artifacts_dir.iterdir():
            if file_path.is_file():
                file_type = file_path.suffix.lstrip(".")
                response.artifacts.append(
                    Artifact(
                        name=file_path.name,
                        path=str(file_path),
                        type=file_type if file_type else "unknown",
                        size=file_path.stat().st_size,
                        exists=True,
                    )
                )

    equity_path = run_dir / "artifacts" / "equity.csv"
    if equity_path.exists():
        response.artifacts_equity_csv = _load_csv_to_dict(equity_path)

    metrics_csv_path = run_dir / "artifacts" / "metrics.csv"
    if metrics_csv_path.exists():
        response.artifacts_metrics_csv = _load_csv_to_dict(metrics_csv_path)

    trades_path = run_dir / "artifacts" / "trades.csv"
    if trades_path.exists():
        response.artifacts_trades_csv = _load_csv_to_dict(trades_path)

    validation_path = run_dir / "artifacts" / "validation.json"
    if validation_path.exists():
        try:
            response.validation = json.loads(validation_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    if response.artifacts_equity_csv:
        filtered_equity = []
        for row in response.artifacts_equity_csv[:1000]:
            filtered_row: Dict[str, Any] = {}
            if "timestamp" in row:
                filtered_row["time"] = row["timestamp"]
            if "equity" in row:
                filtered_row["equity"] = row["equity"]
            if "drawdown" in row:
                filtered_row["drawdown"] = row["drawdown"]
            filtered_equity.append(filtered_row)
        response.equity_curve = filtered_equity

    if response.artifacts_trades_csv:
        response.trade_log = response.artifacts_trades_csv[:500]

    if include_analysis:
        analysis = build_run_analysis(run_dir)
        response.run_stage = analysis.get("run_stage")
        response.run_context = analysis.get("run_context")
        response.price_series = analysis.get("price_series")
        response.indicator_series = analysis.get("indicator_series")
        response.trade_markers = analysis.get("trade_markers")
        response.run_logs = analysis.get("run_logs")

    return response


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/runs/{run_id}/code")
async def get_run_code(run_id: str):
    """Return strategy source files for a run.

    Args:
        run_id: Run identifier.

    Returns:
        Map filename -> source text.
    """
    run_dir = RUNS_DIR / run_id / "code"
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Code directory for run {run_id} not found")
    result = {}
    for f in ["signal_engine.py"]:
        p = run_dir / f
        if p.exists():
            result[f] = p.read_text(encoding="utf-8")
    return result


@app.get("/runs/{run_id}/pine")
async def get_run_pine(run_id: str):
    """Return Pine Script file for a run.

    Args:
        run_id: Run identifier.

    Returns:
        Object with pine script content and exists flag.
    """
    pine_path = RUNS_DIR / run_id / "artifacts" / "strategy.pine"
    if not pine_path.exists():
        return {"exists": False, "content": None}
    return {
        "exists": True,
        "content": pine_path.read_text(encoding="utf-8"),
    }


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run_result(run_id: str):
    """Fetch full details for a historical run by ``run_id``."""
    run_dir = RUNS_DIR / run_id

    if not run_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found"
        )

    response = _build_response_from_run_dir(run_dir, elapsed=0.0, include_analysis=True)

    return response


@app.get("/runs", response_model=List[RunInfo])
async def list_runs(limit: int = 20):
    """List recent runs with summary fields."""
    limit = min(max(1, limit), 100)
    runs_dir = RUNS_DIR
    
    if not runs_dir.exists():
        return []
    
    run_dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        key=lambda x: x.name,
        reverse=True
    )
    
    results = []
    for d in run_dirs[:limit]:
        run_id = d.name
        
        # Status from state.json or artifacts
        status_val = "unknown"
        state_file = _load_json_file(d / "state.json")
        if state_file:
            status_val = str(state_file.get("status") or "unknown").lower()
        elif (d / "artifacts" / "equity.csv").exists():
            status_val = "success"
        elif (d / "review_report.json").exists():
            status_val = "success"
        
        # Parse created_at from run_id (YYYYMMDD_HHMMSS or run_YYYYMMDD_HHMMSS)
        created_at = "Unknown"
        if run_id.startswith("run_"):
            parts = run_id.split('_')
            if len(parts) >= 3:
                d_str, t_str = parts[1], parts[2]
                if len(d_str) == 8 and len(t_str) == 6:
                    created_at = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]} {t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}"
        elif "_" in run_id:
            parts = run_id.split('_')
            if len(parts) >= 2:
                d_str, t_str = parts[0], parts[1]
                if len(d_str) == 8 and len(t_str) == 6:
                    created_at = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]} {t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}"
        
        if created_at == "Unknown":
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            created_at = mtime.strftime("%Y-%m-%d %H:%M:%S")
        
        prompt = None
        req_file = d / "req.json"
        planner_file = d / "planner_output.json"
        if req_file.exists():
            try:
                req_data = json.loads(req_file.read_text(encoding="utf-8"))
                prompt = req_data.get("prompt")
            except:
                pass
        
        if not prompt and planner_file.exists():
            try:
                planner_data = json.loads(planner_file.read_text(encoding="utf-8"))
                prompt = planner_data.get("user_goal") or planner_data.get("goal")
            except:
                pass
            
        if not prompt:
            prompt_file = d / "user_prompt.txt"
            if prompt_file.exists():
                prompt = prompt_file.read_text(encoding="utf-8").strip()
        
        total_return = None
        sharpe = None
        metrics_file = d / "artifacts" / "metrics.csv"
        if metrics_file.exists():
            try:
                import csv
                with open(metrics_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        total_return = float(row.get('total_return', 0) or 0)
                        sharpe = float(row.get('sharpe', 0) or 0)
                        break
            except:
                pass
        
        run_context = load_run_context(d)
        results.append(RunInfo(
            run_id=run_id,
            status=status_val,
            created_at=created_at,
            prompt=prompt or "Manual Analysis",
            total_return=total_return,
            sharpe=sharpe,
            codes=run_context.get("codes") or [],
            start_date=run_context.get("start_date"),
            end_date=run_context.get("end_date"),
        ))
        
    return results


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Liveness probe."""
    return HealthResponse(
        status="healthy",
        service="Vibe-Trading API",
        timestamp=datetime.now().isoformat()
    )


def _terminate_current_process() -> None:
    """Stop the current API process after the response has been sent."""
    time.sleep(0.25)
    os.kill(os.getpid(), signal.SIGTERM)


@app.post("/system/shutdown", dependencies=[Depends(require_auth)])
async def shutdown_local_api(background_tasks: BackgroundTasks, request: Request):
    """Shut down the local API server when requested from loopback clients."""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local access only")

    background_tasks.add_task(_terminate_current_process)
    return {
        "status": "shutting-down",
        "service": "Vibe-Trading API",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/skills")
async def list_skills():
    """List registered skills (name and description)."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    return [
        {
            "name": s.name,
            "description": s.description,
        }
        for s in loader.skills
    ]


@app.get("/api")
async def api_info():
    """Service metadata."""
    return {
        "service": "Vibe-Trading API",
        "version": "5.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# ============================================================================
# Session API
# ============================================================================

_session_service = None


def _get_session_service():
    """Lazy-init session service when ENABLE_SESSION_RUNTIME=true."""
    global _session_service
    if _session_service is not None:
        return _session_service

    if os.getenv("ENABLE_SESSION_RUNTIME", "true").lower() != "true":
        return None

    import asyncio
    from src.session.store import SessionStore
    from src.session.events import EventBus
    from src.session.service import SessionService

    store = SessionStore(base_dir=SESSIONS_DIR)
    event_bus = EventBus()

    try:
        loop = asyncio.get_event_loop()
        event_bus.set_loop(loop)
    except RuntimeError:
        pass

    _session_service = SessionService(
        store=store,
        event_bus=event_bus,
        runs_dir=RUNS_DIR,
    )
    return _session_service


@app.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_auth)])
async def create_session(request: CreateSessionRequest):
    """Create a chat session."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    session = svc.create_session(title=request.title, config=request.config)
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        status=session.status.value,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_attempt_id=session.last_attempt_id,
    )


@app.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(limit: int = Query(50, ge=1, le=200)):
    """List sessions."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    sessions = svc.list_sessions(limit=limit)
    return [
        SessionResponse(
            session_id=s.session_id,
            title=s.title,
            status=s.status.value,
            created_at=s.created_at,
            updated_at=s.updated_at,
            last_attempt_id=s.last_attempt_id,
        )
        for s in sessions
    ]


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get one session by id."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    session = svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        status=session.status.value,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_attempt_id=session.last_attempt_id,
    )


@app.delete("/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def delete_session(session_id: str):
    """Delete a session."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    deleted = svc.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"status": "deleted", "session_id": session_id}


class UpdateSessionRequest(BaseModel):
    """Session update fields."""
    title: Optional[str] = None


@app.patch("/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def update_session(session_id: str, req: UpdateSessionRequest):
    """Update session fields (e.g. title)."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    session = svc.store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if req.title is not None:
        session.title = req.title
    from datetime import datetime
    session.updated_at = datetime.now().isoformat()
    svc.store.update_session(session)
    return {"status": "updated", "session_id": session_id}


@app.post("/sessions/{session_id}/messages", dependencies=[Depends(require_auth)])
async def send_message(session_id: str, request: SendMessageRequest):
    """Send a user message and start the agent loop (natural language strategy)."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    try:
        result = await svc.send_message(session_id=session_id, content=request.content)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/sessions/{session_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_session(session_id: str):
    """Cancel the in-flight agent loop for this session."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    cancelled = svc.cancel_current(session_id)
    if not cancelled:
        return {"status": "no_active_loop"}
    return {"status": "cancelled"}


@app.get("/sessions/{session_id}/messages", response_model=List[MessageResponse])
async def get_messages(session_id: str, limit: int = Query(100, ge=1, le=1000)):
    """List messages for a session."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    messages = svc.get_messages(session_id, limit=limit)
    return [
        MessageResponse(
            message_id=m.message_id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            linked_attempt_id=m.linked_attempt_id,
            metadata=m.metadata if m.metadata else None,
        )
        for m in messages
    ]


@app.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    last_event_id: Optional[str] = Query(None, alias="Last-Event-ID"),
):
    """SSE stream for agent events."""
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    session = svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    header_id = request.headers.get("Last-Event-ID")
    event_id = header_id or last_event_id

    async def event_generator():
        async for event in svc.event_bus.subscribe(session_id, last_event_id=event_id):
            if await request.is_disconnected():
                break
            yield event.to_sse()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# File Upload
# ============================================================================

_BLOCKED_UPLOAD_EXT = {
    # binaries / executables we should never accept
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".app", ".dmg",
    ".so", ".dll", ".dylib",
    # archives — don't auto-extract; user can unpack locally
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
}


_SHADOW_ID_RE = __import__("re").compile(r"^shadow_[0-9a-f]{8}$")


@app.get("/shadow-reports/{shadow_id}")
async def get_shadow_report(shadow_id: str, format: str = "html"):
    """Serve a rendered Shadow Account report (HTML by default, PDF if available).

    Reports live under ``~/.vibe-trading/shadow_reports/<shadow_id>.{html,pdf}``.
    """
    if not _SHADOW_ID_RE.match(shadow_id):
        raise HTTPException(status_code=400, detail="invalid shadow_id")
    if format not in ("html", "pdf"):
        raise HTTPException(status_code=400, detail="format must be html or pdf")

    reports_dir = Path.home() / ".vibe-trading" / "shadow_reports"
    path = reports_dir / f"{shadow_id}.{format}"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Shadow report not found: {shadow_id}.{format}")

    media_type = "text/html; charset=utf-8" if format == "html" else "application/pdf"
    # Inline so browsers render HTML/PDF directly instead of forcing download.
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{shadow_id}.{format}"'},
    )


@app.post("/upload", dependencies=[Depends(require_auth)])
async def upload_file(file: UploadFile):
    """Upload any document or data file (max 50MB).

    Accepts most common formats: PDF, Word, Excel, PowerPoint, images,
    CSV/TSV, plain text, JSON/YAML/TOML, source code. Executables and
    archives are rejected — unpack locally before uploading.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    ext = Path(file.filename).suffix.lower()
    if ext in _BLOCKED_UPLOAD_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"File type {ext} is not allowed (executables/archives blocked).",
        )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / safe_name
    total_size = 0

    try:
        with dest.open("wb") as handle:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    handle.close()
                    if dest.exists():
                        dest.unlink()
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (limit {MAX_UPLOAD_SIZE // (1024 * 1024)} MB)",
                    )
                handle.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        if dest.exists():
            dest.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {exc}") from exc
    finally:
        await file.close()

    return {
        "status": "ok",
        "file_path": str(dest.resolve()),
        "filename": file.filename,
    }


# ============================================================================
# Swarm API
# ============================================================================

_swarm_runtime = None


def _get_swarm_runtime():
    """Lazy-init SwarmRuntime singleton."""
    global _swarm_runtime
    if _swarm_runtime is not None:
        return _swarm_runtime
    from src.swarm.store import SwarmStore
    from src.swarm.runtime import SwarmRuntime
    swarm_dir = Path(__file__).resolve().parent / ".swarm" / "runs"
    store = SwarmStore(base_dir=swarm_dir)
    _swarm_runtime = SwarmRuntime(store=store)
    return _swarm_runtime


@app.get("/swarm/presets")
async def list_swarm_presets():
    """List Swarm YAML presets."""
    from src.swarm.presets import list_presets
    return list_presets()


@app.post("/swarm/runs", dependencies=[Depends(require_auth)])
async def create_swarm_run(request: dict):
    """Start a swarm run: body must include preset_name and user_vars."""
    runtime = _get_swarm_runtime()
    preset_name = request.get("preset_name", "")
    user_vars = request.get("user_vars", {})
    try:
        run = runtime.start_run(preset_name, user_vars)
        return {"id": run.id, "status": run.status.value, "preset_name": run.preset_name}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/swarm/runs")
async def list_swarm_runs(limit: int = Query(20, ge=1, le=100)):
    """List swarm runs (newest first)."""
    runtime = _get_swarm_runtime()
    runs = runtime._store.list_runs(limit=limit)
    return [
        {
            "id": r.id,
            "preset_name": r.preset_name,
            "status": r.status.value,
            "created_at": r.created_at,
            "task_count": len(r.tasks),
            "completed_count": sum(1 for t in r.tasks if t.status.value == "completed"),
        }
        for r in runs
    ]


@app.get("/swarm/runs/{run_id}")
async def get_swarm_run(run_id: str):
    """Swarm run detail including task statuses."""
    from src.swarm.task_store import TaskStore

    runtime = _get_swarm_runtime()
    run = runtime._store.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Merge real-time task statuses from task_store (updated during execution)
    run_dir = runtime._store.run_dir(run_id)
    tasks_dir = run_dir / "tasks"
    if tasks_dir.exists():
        task_store = TaskStore(run_dir)
        live_tasks = task_store.load_all()
        if live_tasks:
            run.tasks = live_tasks

    return {
        "id": run.id,
        "preset_name": run.preset_name,
        "status": run.status.value,
        "user_vars": run.user_vars,
        "agents": [a.model_dump() for a in run.agents],
        "tasks": [t.model_dump() for t in run.tasks],
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "final_report": run.final_report,
    }


@app.get("/swarm/runs/{run_id}/events")
async def swarm_run_events(run_id: str, request: Request, last_index: int = Query(0, ge=0)):
    """SSE stream for a swarm run."""
    import asyncio
    runtime = _get_swarm_runtime()

    async def event_stream():
        idx = last_index
        while True:
            if await request.is_disconnected():
                break
            events = runtime._store.read_events(run_id, after_index=idx)
            for evt in events:
                idx += 1
                yield f"id: {idx}\nevent: {evt.type}\ndata: {json.dumps(evt.model_dump(), ensure_ascii=False)}\n\n"
            run = runtime._store.load_run(run_id)
            if run and run.status.value in ("completed", "failed", "cancelled"):
                yield f"event: done\ndata: {{\"status\": \"{run.status.value}\"}}\n\n"
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/swarm/runs/{run_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_swarm_run(run_id: str):
    """Cancel an active swarm run."""
    runtime = _get_swarm_runtime()
    ok = runtime.cancel_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No active run {run_id}")
    return {"status": "cancelled"}


# ============================================================================
# Main Entry Point
# ============================================================================

def serve_main(argv: list[str] | None = None) -> int:
    """Start the API server from CLI-style arguments."""
    import argparse
    import subprocess
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    parser = argparse.ArgumentParser(description="Vibe-Trading Server")
    parser.add_argument("--port", type=int, default=8000, help="Listen port (default 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--dev", action="store_true", help="Dev mode: spawn Vite on :5173")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    frontend_root = Path(__file__).resolve().parent.parent / "frontend"

    vite_proc = None
    if args.dev and frontend_root.exists():
        print("[dev] Starting Vite dev server on :5173 ...")
        vite_proc = subprocess.Popen(
            ["npx", "vite", "--host", "0.0.0.0"],
            cwd=str(frontend_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[dev] Vite PID={vite_proc.pid}")
        print("[dev] Frontend: http://localhost:5173")
        print(f"[dev] API: http://localhost:{args.port}")
    elif frontend_dist.exists():
        if not any(route.path == "/" for route in app.routes):
            app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
        print(f"[prod] Frontend served from {frontend_dist}")
    else:
        print(f"[warn] No frontend build found at {frontend_dist}")
        print("[warn] Run: cd frontend && npm run build")

    print("=" * 50)
    print("  Vibe-Trading Server")
    print(f"  http://127.0.0.1:{args.port}")
    print("=" * 50)

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        if vite_proc:
            vite_proc.terminate()
            print("[dev] Vite stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(serve_main())
