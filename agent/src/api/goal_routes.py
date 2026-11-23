"""Session goal requests, snapshots and evidence routes."""

from __future__ import annotations

from src.tools.path_utils import FileRoots

from src.config.accessor import get_env_config

from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from src.api.session_http import existing_session


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


_goal_store = None


def _get_goal_store():
    """Return the shared finance goal store."""
    global _goal_store
    if _goal_store is None:
        from src.goal import GoalStore

        _goal_store = GoalStore()
    return _goal_store


def register_goal_routes(app: FastAPI, host) -> None:
    """Register goals with the host authentication dependencies."""
    @app.post(
        "/sessions/{session_id}/goal",
        response_model=GoalSnapshotResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(host.require_auth)],
    )
    async def create_session_goal(session_id: str, req: CreateGoalRequest):
        """Create or replace the current finance research goal for a session."""
        host._validate_path_param(session_id, "session_id")
        svc, _session = existing_session(host, session_id)
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
        dependencies=[Depends(host.require_auth)],
    )
    async def get_session_goal(session_id: str):
        """Return the current finance research goal snapshot for a session."""
        host._validate_path_param(session_id, "session_id")
        existing_session(host, session_id)
        snapshot = _get_goal_store().get_current_snapshot(session_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No current goal")
        return snapshot

    @app.patch(
        "/sessions/{session_id}/goal",
        response_model=UpdateGoalResponse,
        dependencies=[Depends(host.require_auth)],
    )
    async def update_session_goal(session_id: str, req: UpdateGoalRequest):
        """Edit the current finance research goal without replacing the session."""
        host._validate_path_param(session_id, "session_id")
        svc, _session = existing_session(host, session_id)
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
        dependencies=[Depends(host.require_auth)],
    )
    async def add_session_goal_evidence(session_id: str, req: AddGoalEvidenceRequest):
        """Append traceable evidence to the current finance research goal."""
        host._validate_path_param(session_id, "session_id")
        svc, _session = existing_session(host, session_id)
        from dataclasses import asdict
        from src.goal import EvidenceInput, StaleGoalError

        goal_store = _get_goal_store()
        try:
            evidence = goal_store.append_evidence(
                roots=FileRoots.from_config(get_env_config().api),
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
        dependencies=[Depends(host.require_auth)],
    )
    async def update_session_goal_status(session_id: str, req: UpdateGoalStatusRequest):
        """Update the current finance research goal status."""
        host._validate_path_param(session_id, "session_id")
        svc, _session = existing_session(host, session_id)
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
