"""Session and goal HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_sessions_routes(app)``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================

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


class CreateGoalRequest(BaseModel):
    """Create or replace a finance research goal."""

    objective: str = Field(..., min_length=1, max_length=5000)
    criteria: List[str] = Field(default_factory=list)
    ui_summary: str = ""
    protocol: str = "thesis_review"
    risk_tier: str = "research_general"
    token_budget: Optional[int] = Field(None, ge=1)
    turn_budget: Optional[int] = Field(None, ge=1)
    time_budget_seconds: Optional[int] = Field(None, ge=1)


class UpdateGoalRequest(BaseModel):
    """Edit mutable finance research goal fields."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    objective: Optional[str] = Field(None, min_length=1, max_length=5000)
    ui_summary: Optional[str] = Field(None, max_length=500)


class AddGoalEvidenceRequest(BaseModel):
    """Append evidence to a finance research goal."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=10000)
    criterion_id: Optional[str] = None
    claim_id: Optional[str] = None
    evidence_type: str = "evidence"
    tool_call_id: Optional[str] = None
    run_id: Optional[str] = None
    source_provider: Optional[str] = None
    source_type: Optional[str] = None
    source_uri: Optional[str] = None
    symbol_universe: List[str] = Field(default_factory=list)
    benchmark: List[str] = Field(default_factory=list)
    timeframe: Optional[str] = None
    method: Optional[str] = None
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    artifact_path: Optional[str] = None
    artifact_hash: Optional[str] = None
    data_as_of: Optional[str] = None
    confidence: Optional[str] = None
    caveat: Optional[str] = None
    contradicts_claim_ids: List[str] = Field(default_factory=list)


class GoalSnapshotResponse(BaseModel):
    """Finance research goal snapshot."""

    goal: Dict[str, Any]
    claims: List[Dict[str, Any]]
    criteria: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    evidence_count: int = 0


class AddGoalEvidenceResponse(BaseModel):
    """Response after appending goal evidence."""

    evidence: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class GoalAuditRowRequest(BaseModel):
    """One criterion row for goal status audits."""

    criterion_id: str = Field(..., min_length=1)
    result: str = Field(..., min_length=1)
    evidence_ids: List[str] = Field(default_factory=list)
    notes: str = ""


class UpdateGoalStatusRequest(BaseModel):
    """Update a finance research goal status."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    audit: List[GoalAuditRowRequest] = Field(default_factory=list)
    recap: Optional[str] = None


class UpdateGoalStatusResponse(BaseModel):
    """Response after changing a goal status."""

    goal: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class UpdateGoalResponse(BaseModel):
    """Response after editing a goal."""

    goal: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class UpdateSessionRequest(BaseModel):
    """Session update fields."""
    title: Optional[str] = None


# ============================================================================
# State variables
# ============================================================================

_goal_store = None


# ============================================================================
# Helper Functions
# ============================================================================

def _get_goal_store():
    """Return the shared finance goal store."""
    global _goal_store
    if _goal_store is None:
        from src.goal import GoalStore

        _goal_store = GoalStore()
    return _goal_store

# ============================================================================
# SSE frame helpers for session events (module-level for re-export)
# ============================================================================

_PROPOSAL_TOOL_NAME = "propose_mandate_profiles"
_PROPOSAL_ID_RE = re.compile(r'"proposal_id"\s*:\s*"(mp_[0-9a-f]{32})"')


def _load_full_proposal(proposal_id: str) -> Optional[Dict[str, Any]]:
    """Reload a persisted mandate proposal by id, broker-agnostic."""
    try:
        from src.live.paths import live_root

        for proposal_path in live_root().glob(f"*/proposals/{proposal_id}.json"):
            try:
                data = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == "mandate.proposal":
                return data
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("mandate.proposal reload failed for %s", proposal_id, exc_info=True)
    return None


def _mandate_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a mandate.proposal SSE frame from a propose-tool tool_result."""
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    if data.get("tool") != _PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    proposal = _load_full_proposal(match.group(1))
    if proposal is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="mandate.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


_LIVE_ACTION_ID_RE = re.compile(r'"audit_id"\s*:\s*"(la_[0-9a-zA-Z]+)"')


def _load_live_action_record(audit_id: str) -> Optional[Dict[str, Any]]:
    """Reload a redacted live-action record from the ledger by audit_id."""
    try:
        from src.live.paths import live_root

        ledger = live_root() / "audit.jsonl"
        if not ledger.exists():
            return None
        for line in reversed(ledger.read_text(encoding="utf-8").splitlines()):
            if audit_id not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("audit_id") == audit_id:
                return record
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("live.action reload failed for %s", audit_id, exc_info=True)
    return None


def _live_action_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a live.action SSE frame from an order-guard tool_result."""
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    preview = str(data.get("preview") or "")
    if '"live_action"' not in preview:
        return None
    match = _LIVE_ACTION_ID_RE.search(preview)
    if not match:
        return None
    record = _load_live_action_record(match.group(1))
    if record is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="live.action",
        data=record,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()



# ============================================================================
# Registration
# ============================================================================

# >>> ICICI PAPER ORDER APPROVAL MODULE >>>
from datetime import datetime as _paper_dt, timedelta as _paper_td, timezone as _paper_tz
from threading import Lock as _PaperLock
from typing import Any as _PaperAny
from uuid import uuid4 as _paper_uuid4

from fastapi import HTTPException as _PaperHTTPException
from pydantic import BaseModel as _PaperBaseModel, Field as _PaperField

from src.trading.service import place_order as _paper_place_order


_PAPER_PROFILE_ID = "icici-breeze-paper-trade"
_PAPER_PROPOSAL_TTL_SECONDS = 300
_PAPER_TERMINAL_RETENTION_SECONDS = 3600
_paper_proposals: dict[str, dict[str, _PaperAny]] = {}
_paper_proposals_lock = _PaperLock()


class PaperOrderProposalRequest(_PaperBaseModel):
    profile_id: str = _PAPER_PROFILE_ID
    symbol: str = _PaperField(min_length=1, max_length=64)
    side: str
    quantity: float = _PaperField(gt=0)
    order_type: str = "limit"
    limit_price: float = _PaperField(gt=0)
    time_in_force: str = "day"
    reference_price: float | None = _PaperField(default=None, gt=0)


def _paper_now() -> _paper_dt:
    return _paper_dt.now(_paper_tz.utc)


def _paper_iso(value: _paper_dt | None) -> str | None:
    return value.isoformat() if value is not None else None


def _paper_public(record: dict[str, _PaperAny]) -> dict[str, _PaperAny]:
    return {
        "proposal_id": record["proposal_id"],
        "session_id": record["session_id"],
        "profile_id": record["profile_id"],
        "environment": "paper",
        "symbol": record["symbol"],
        "side": record["side"],
        "quantity": record["quantity"],
        "order_type": record["order_type"],
        "limit_price": record["limit_price"],
        "time_in_force": record["time_in_force"],
        "reference_price": record.get("reference_price"),
        "state": record["state"],
        "created_at": _paper_iso(record["created_at"]),
        "expires_at": _paper_iso(record["expires_at"]),
        "used_at": _paper_iso(record.get("used_at")),
        "result": record.get("result"),
        "error": record.get("error"),
    }


def _paper_cleanup_locked(now: _paper_dt) -> None:
    remove_ids: list[str] = []

    for proposal_id, record in _paper_proposals.items():
        if record["state"] == "pending" and now >= record["expires_at"]:
            record["state"] = "expired"
            record["used_at"] = now
            record["error"] = "proposal expired before approval"

        terminal_at = record.get("used_at")
        if terminal_at and (
            now - terminal_at
        ).total_seconds() > _PAPER_TERMINAL_RETENTION_SECONDS:
            remove_ids.append(proposal_id)

    for proposal_id in remove_ids:
        _paper_proposals.pop(proposal_id, None)

def _paper_get_record_locked(
    session_id: str,
    proposal_id: str,
) -> dict[str, _PaperAny]:
    _paper_cleanup_locked(_paper_now())
    record = _paper_proposals.get(proposal_id)

    if not record or record["session_id"] != session_id:
        raise _PaperHTTPException(
            status_code=404,
            detail="Paper-order proposal not found",
        )

    return record
# <<< ICICI PAPER ORDER APPROVAL MODULE <<<

def register_sessions_routes(app: FastAPI) -> None:
    """Mount the session/goal routes onto ``app``.

    Resolves shared dependencies from the host ``api_server`` module via
    ``sys.modules``.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_sessions_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    # Auth dependencies
    require_auth = host.require_auth
    require_event_stream_auth = host.require_event_stream_auth

    # Late-access closures for shared host symbols (monkeypatch-safe)
    def _host_get_session_service():
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._get_session_service()

    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._validate_path_param(value, kind)

    def _host_shell_tools_enabled_for_request(request: Request) -> bool:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._shell_tools_enabled_for_request(request)

    def _get_existing_session_or_404(session_id: str):
        """Return (service, session) or raise 404."""
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return svc, session

    # -----------------------------------------------------------------------
    # Session CRUD routes
    # -----------------------------------------------------------------------

    @app.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_auth)])
    async def create_session(request: CreateSessionRequest):
        """Create a chat session."""
        svc = _host_get_session_service()
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

    @app.get("/sessions", response_model=List[SessionResponse], dependencies=[Depends(require_auth)])
    async def list_sessions(limit: int = Query(50, ge=1, le=200)):
        """List sessions."""
        svc = _host_get_session_service()
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

    @app.get("/sessions/{session_id}", response_model=SessionResponse, dependencies=[Depends(require_auth)])
    async def get_session(session_id: str):
        """Get one session by id."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
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

    # -----------------------------------------------------------------------
    # Goal sub-group routes
    # -----------------------------------------------------------------------

    @app.post(
        "/sessions/{session_id}/goal",
        response_model=GoalSnapshotResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def create_session_goal(session_id: str, req: CreateGoalRequest):
        """Create or replace the current finance research goal for a session."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from src.goal import RiskTier
        from src.goal.context import default_goal_criteria

        criteria = [item.strip() for item in req.criteria if item.strip()]
        if not criteria:
            criteria = default_goal_criteria()
        try:
            risk_tier = RiskTier(req.risk_tier)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid risk_tier: {req.risk_tier}") from exc
        if risk_tier is RiskTier.LIVE_TRADING_OR_EXECUTION:
            raise HTTPException(status_code=400, detail="live trading or execution goals are not supported")

        goal_store = _get_goal_store()
        try:
            goal = goal_store.replace_goal(
                session_id=session_id,
                objective=req.objective,
                criteria=criteria,
                ui_summary=req.ui_summary,
                source="api",
                protocol=req.protocol,
                risk_tier=risk_tier,
                token_budget=req.token_budget,
                turn_budget=req.turn_budget,
                time_budget_seconds=req.time_budget_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = goal_store.get_goal_snapshot(goal.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal created but could not be reloaded")
        svc.event_bus.emit(session_id, "goal.created", {"goal": snapshot["goal"]})
        return snapshot

    @app.get(
        "/sessions/{session_id}/goal",
        response_model=GoalSnapshotResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_session_goal(session_id: str):
        """Return the current finance research goal snapshot for a session."""
        _host_validate_path_param(session_id, "session_id")
        _get_existing_session_or_404(session_id)
        snapshot = _get_goal_store().get_current_snapshot(session_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No current goal")
        return snapshot

    @app.patch(
        "/sessions/{session_id}/goal",
        response_model=UpdateGoalResponse,
        dependencies=[Depends(require_auth)],
    )
    async def update_session_goal(session_id: str, req: UpdateGoalRequest):
        """Edit the current finance research goal without replacing the session."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from src.goal import StaleGoalError

        if req.objective is None and req.ui_summary is None:
            raise HTTPException(status_code=400, detail="objective or ui_summary is required")

        goal_store = _get_goal_store()
        try:
            goal = goal_store.update_goal(
                session_id=session_id,
                goal_id=req.goal_id,
                expected_goal_id=req.expected_goal_id,
                objective=req.objective,
                ui_summary=req.ui_summary,
            )
        except StaleGoalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = goal_store.get_goal_snapshot(goal.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal snapshot could not be reloaded")
        svc.event_bus.emit(session_id, "goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
        return {"goal": snapshot["goal"], "snapshot": snapshot}

    @app.post(
        "/sessions/{session_id}/goal/evidence",
        response_model=AddGoalEvidenceResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def add_session_goal_evidence(session_id: str, req: AddGoalEvidenceRequest):
        """Append traceable evidence to the current finance research goal."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from dataclasses import asdict
        from src.goal import EvidenceInput, StaleGoalError

        goal_store = _get_goal_store()
        try:
            evidence = goal_store.append_evidence(
                session_id=session_id,
                goal_id=req.goal_id,
                expected_goal_id=req.expected_goal_id,
                evidence=EvidenceInput(
                    criterion_id=req.criterion_id,
                    claim_id=req.claim_id,
                    evidence_type=req.evidence_type,
                    text=req.text,
                    tool_call_id=req.tool_call_id,
                    run_id=req.run_id,
                    source_provider=req.source_provider,
                    source_type=req.source_type,
                    source_uri=req.source_uri,
                    symbol_universe=req.symbol_universe,
                    benchmark=req.benchmark,
                    timeframe=req.timeframe,
                    method=req.method,
                    assumptions=req.assumptions,
                    artifact_path=req.artifact_path,
                    artifact_hash=req.artifact_hash,
                    data_as_of=req.data_as_of,
                    confidence=req.confidence,
                    caveat=req.caveat,
                    contradicts_claim_ids=req.contradicts_claim_ids,
                ),
            )
        except StaleGoalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = goal_store.get_goal_snapshot(req.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal snapshot could not be reloaded")
        svc.event_bus.emit(
            session_id,
            "goal.evidence",
            {"evidence": asdict(evidence), "goal_id": req.goal_id},
        )
        return {"evidence": asdict(evidence), "snapshot": snapshot}

    @app.patch(
        "/sessions/{session_id}/goal/status",
        response_model=UpdateGoalStatusResponse,
        dependencies=[Depends(require_auth)],
    )
    async def update_session_goal_status(session_id: str, req: UpdateGoalStatusRequest):
        """Update the current finance research goal status."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from src.goal import AuditRow, GoalStatus, StaleGoalError

        try:
            next_status = GoalStatus(req.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid goal status: {req.status}") from exc

        goal_store = _get_goal_store()
        try:
            goal = goal_store.update_status(
                session_id=session_id,
                goal_id=req.goal_id,
                expected_goal_id=req.expected_goal_id,
                status=next_status,
                audit=[
                    AuditRow(
                        criterion_id=row.criterion_id,
                        result=row.result,
                        evidence_ids=row.evidence_ids,
                        notes=row.notes,
                    )
                    for row in req.audit
                ],
                recap=req.recap,
            )
        except StaleGoalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = goal_store.get_goal_snapshot(goal.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal snapshot could not be reloaded")
        svc.event_bus.emit(session_id, "goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
        return {"goal": snapshot["goal"], "snapshot": snapshot}

    # -----------------------------------------------------------------------
    # Session action routes
    # -----------------------------------------------------------------------

    @app.delete("/sessions/{session_id}", dependencies=[Depends(require_auth)])
    async def delete_session(session_id: str):
        """Delete a session."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        deleted = svc.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        _get_goal_store().delete_session_goals(session_id)
        return {"status": "deleted", "session_id": session_id}

    @app.patch("/sessions/{session_id}", dependencies=[Depends(require_auth)])
    async def update_session(session_id: str, req: UpdateSessionRequest):
        """Update session fields (e.g. title)."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        if req.title is not None:
            session.title = req.title
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.store.update_session(session)
        return {"status": "updated", "session_id": session_id}

    @app.post("/sessions/{session_id}/messages", dependencies=[Depends(require_auth)])
    async def send_message(session_id: str, payload: SendMessageRequest, http_request: Request):
        """Send a user message and start the agent loop (natural language strategy)."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        try:
            result = await svc.send_message(
                session_id=session_id,
                content=payload.content,
                include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/sessions/{session_id}/cancel", dependencies=[Depends(require_auth)])
    async def cancel_session(session_id: str):
        """Cancel the in-flight agent loop for this session."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        cancelled = svc.cancel_current(session_id)
        if not cancelled:
            return {"status": "no_active_loop"}
        return {"status": "cancelled"}

    @app.get("/sessions/{session_id}/messages", response_model=List[MessageResponse], dependencies=[Depends(require_auth)])
    async def get_messages(session_id: str, limit: int = Query(100, ge=1, le=1000)):
        """List messages for a session."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
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

    @app.get("/sessions/{session_id}/events", dependencies=[Depends(require_event_stream_auth)])
    async def session_events(
        session_id: str,
        request: Request,
        last_event_id: Optional[str] = Query(None, alias="Last-Event-ID"),
        replay: Optional[str] = Query(None),
    ):
        """SSE stream for agent events."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        header_id = request.headers.get("Last-Event-ID")
        event_id = header_id or last_event_id
        replay_active = (replay or "").lower() == "active"
        replay_all = False
        if replay_active and not event_id and session.last_attempt_id:
            attempt = svc.store.get_attempt(session_id, session.last_attempt_id)
            attempt_status = getattr(attempt.status, "value", attempt.status) if attempt else None
            replay_all = attempt_status == "running"

        async def event_generator():
            async for event in svc.event_bus.subscribe(
                session_id,
                last_event_id=event_id,
                replay_all=replay_all,
            ):
                if await request.is_disconnected():
                    break
                yield event.to_sse()
                relayed = _mandate_proposal_frame_from_tool_result(event)
                if relayed is not None:
                    yield relayed
                live_action = _live_action_frame_from_tool_result(event)
                if live_action is not None:
                    yield live_action

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    def _paper_require_session(session_id: str) -> None:
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()

        if not svc:
            raise _PaperHTTPException(
                status_code=501,
                detail="Session runtime not enabled",
            )

        if not svc.store.get_session(session_id):
            raise _PaperHTTPException(
                status_code=404,
                detail=f"Session {session_id} not found",
            )

    # >>> ICICI PAPER ORDER APPROVAL ROUTES >>>
    @app.post(
        "/sessions/{session_id}/paper-orders/proposals",
        dependencies=[Depends(require_auth)],
    )
    def create_paper_order_proposal(
        session_id: str,
        req: PaperOrderProposalRequest,
    ):
        """Create an immutable, expiring paper-order proposal. No order is placed."""
        _paper_require_session(session_id)

        profile_id = req.profile_id.strip()
        symbol = req.symbol.strip().upper()
        side = req.side.strip().lower()
        order_type = req.order_type.strip().lower()
        time_in_force = req.time_in_force.strip().lower()

        if profile_id != _PAPER_PROFILE_ID:
            raise _PaperHTTPException(
                status_code=400,
                detail=(
                    "Only the locked ICICI paper profile "
                    f"{_PAPER_PROFILE_ID!r} is allowed"
                ),
            )

        if side not in {"buy", "sell"}:
            raise _PaperHTTPException(
                status_code=400,
                detail="side must be buy or sell",
            )

        if order_type != "limit":
            raise _PaperHTTPException(
                status_code=400,
                detail="Only limit paper orders are supported",
            )

        if time_in_force != "day":
            raise _PaperHTTPException(
                status_code=400,
                detail="Only day time-in-force is supported",
            )

        now = _paper_now()
        proposal_id = "PAPER-PROP-" + _paper_uuid4().hex[:16].upper()

        record = {
            "proposal_id": proposal_id,
            "session_id": session_id,
            "profile_id": profile_id,
            "symbol": symbol,
            "side": side,
            "quantity": float(req.quantity),
            "order_type": order_type,
            "limit_price": float(req.limit_price),
            "time_in_force": time_in_force,
            "reference_price": (
                float(req.reference_price)
                if req.reference_price is not None
                else None
            ),
            "state": "pending",
            "created_at": now,
            "expires_at": now + _paper_td(
                seconds=_PAPER_PROPOSAL_TTL_SECONDS
            ),
            "used_at": None,
            "result": None,
            "error": None,
        }

        with _paper_proposals_lock:
            _paper_cleanup_locked(now)
            _paper_proposals[proposal_id] = record
            public = _paper_public(record)

        # >>> ICICI PAPER ORDER TIMELINE INTEGRATION >>>
        # Proposal creation is read-only. The SSE event only displays the immutable
        # approval card; no order is placed and no broker-write function is called.
        svc = _host_get_session_service()
        svc.event_bus.emit(session_id, "paper.order.proposal", public)
        # <<< ICICI PAPER ORDER TIMELINE INTEGRATION <<<
        return public


    @app.get(
        "/sessions/{session_id}/paper-orders/proposals/{proposal_id}",
        dependencies=[Depends(require_auth)],
    )
    def get_paper_order_proposal(
        session_id: str,
        proposal_id: str,
    ):
        """Return the current state of one proposal."""
        _paper_require_session(session_id)
        _host_validate_path_param(proposal_id, "proposal_id")

        with _paper_proposals_lock:
            record = _paper_get_record_locked(session_id, proposal_id)
            return _paper_public(record)


    @app.post(
        "/sessions/{session_id}/paper-orders/proposals/{proposal_id}/reject",
        dependencies=[Depends(require_auth)],
    )
    def reject_paper_order_proposal(
        session_id: str,
        proposal_id: str,
    ):
        """Reject a pending proposal without placing an order."""
        _paper_require_session(session_id)
        _host_validate_path_param(proposal_id, "proposal_id")
        now = _paper_now()

        with _paper_proposals_lock:
            record = _paper_get_record_locked(session_id, proposal_id)

            if record["state"] != "pending":
                raise _PaperHTTPException(
                    status_code=409,
                    detail=f"Proposal is already {record['state']}",
                )

            record["state"] = "rejected"
            record["used_at"] = now
            record["error"] = "rejected by user"
            return _paper_public(record)


    @app.post(
        "/sessions/{session_id}/paper-orders/proposals/{proposal_id}/approve",
        dependencies=[Depends(require_auth)],
    )
    def approve_paper_order_proposal(
        session_id: str,
        proposal_id: str,
    ):
        """
        Execute the immutable stored proposal once.

        The ICICI connector's paper risk controls run again through place_order
        with confirmed=True. The profile is hard-locked to paper trading.
        """
        _paper_require_session(session_id)
        _host_validate_path_param(proposal_id, "proposal_id")
        now = _paper_now()

        with _paper_proposals_lock:
            record = _paper_get_record_locked(session_id, proposal_id)

            if record["state"] != "pending":
                raise _PaperHTTPException(
                    status_code=409,
                    detail=f"Proposal is already {record['state']}",
                )

            if now >= record["expires_at"]:
                record["state"] = "expired"
                record["used_at"] = now
                record["error"] = "proposal expired before approval"

                raise _PaperHTTPException(
                    status_code=410,
                    detail="Paper-order proposal has expired",
                )

            record["state"] = "processing"
            record["used_at"] = now
            snapshot = dict(record)

        try:
            result = _paper_place_order(
                snapshot["symbol"],
                profile_id=_PAPER_PROFILE_ID,
                side=snapshot["side"],
                quantity=snapshot["quantity"],
                order_type=snapshot["order_type"],
                limit_price=snapshot["limit_price"],
                time_in_force=snapshot["time_in_force"],
                confirmed=True,
                session_id=session_id,
            )

            if not isinstance(result, dict):
                raise RuntimeError(
                    "Paper connector returned a non-dictionary result"
                )

            if result.get("paper") is not True:
                raise RuntimeError(
                    "Paper connector did not confirm paper mode"
                )

            if result.get("broker_write_called") is not False:
                raise RuntimeError(
                    "Safety invariant failed: broker_write_called was not false"
                )

            with _paper_proposals_lock:
                current = _paper_proposals[proposal_id]
                current["state"] = (
                    "approved"
                    if result.get("status") == "ok"
                    else "rejected_by_risk"
                )
                current["result"] = result
                current["error"] = result.get("error")
                return _paper_public(current)

        except _PaperHTTPException:
            raise

        except Exception as exc:
            with _paper_proposals_lock:
                current = _paper_proposals.get(proposal_id)

                if current:
                    current["state"] = "failed"
                    current["error"] = str(exc)

            raise _PaperHTTPException(
                status_code=500,
                detail=f"Paper-order approval failed: {exc}",
            ) from exc
    # <<< ICICI PAPER ORDER APPROVAL ROUTES <<<
