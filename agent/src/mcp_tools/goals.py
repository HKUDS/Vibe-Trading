"""MCP research-goal tools (start / get / evidence / status)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from src.mcp_tools._shared import (
    audit_rows_from_payload,
    blank_to_none,
    clean_list,
    default_goal_criteria,
    get_goal_store,
    json_error,
    json_ok,
    resolve_session_id,
    risk_tier_from_text,
)


def start_research_goal(
    objective: str,
    session_id: str = "",
    criteria: list[str] | None = None,
    ui_summary: str = "",
    protocol: str = "thesis_review",
    risk_tier: str = "research_general",
    token_budget: int | None = None,
    turn_budget: int | None = None,
    time_budget_seconds: int | None = None,
) -> str:
    """Create or replace the current finance research goal for a session.

    This is the MCP entry point for long-running, research-only finance tasks.
    It creates an auditable goal with checklist criteria and supersedes any
    previous current goal for the same session.

    Args:
        objective: Research-only objective, not a trade execution request.
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
        criteria: Optional checklist. Defaults to the MVP finance protocol.
        ui_summary: Optional compact label for UI surfaces.
        protocol: Research protocol name. Defaults to thesis_review.
        risk_tier: One of the supported non-execution risk tiers.
        token_budget: Optional token budget.
        turn_budget: Optional turn budget.
        time_budget_seconds: Optional wall-clock budget.
    """
    try:
        clean_criteria = clean_list(criteria) or default_goal_criteria()
        goal = get_goal_store().replace_goal(
            session_id=resolve_session_id(session_id),
            objective=objective,
            criteria=clean_criteria,
            ui_summary=ui_summary,
            source="mcp",
            protocol=protocol,
            risk_tier=risk_tier_from_text(risk_tier),
            token_budget=token_budget,
            turn_budget=turn_budget,
            time_budget_seconds=time_budget_seconds,
        )
        snapshot = get_goal_store().get_goal_snapshot(goal.goal_id)
        return json_ok(snapshot=snapshot)
    except ValueError as exc:
        return json_error(str(exc), error_type="validation")


def get_research_goal(session_id: str = "") -> str:
    """Return the current finance research goal snapshot for a session.

    Args:
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
    """
    try:
        snapshot = get_goal_store().get_current_snapshot(resolve_session_id(session_id))
    except ValueError as exc:
        return json_error(str(exc), error_type="validation")
    if snapshot is None:
        return json_error("No current goal", error_type="not_found")
    return json_ok(snapshot=snapshot)


def add_goal_evidence(
    goal_id: str,
    expected_goal_id: str,
    text: str,
    session_id: str = "",
    criterion_id: str | None = None,
    claim_id: str | None = None,
    evidence_type: str = "evidence",
    tool_call_id: str | None = None,
    run_id: str | None = None,
    source_provider: str | None = None,
    source_type: str | None = None,
    source_uri: str | None = None,
    symbol_universe: list[str] | None = None,
    benchmark: list[str] | None = None,
    timeframe: str | None = None,
    method: str | None = None,
    assumptions: dict[str, Any] | None = None,
    artifact_path: str | None = None,
    artifact_hash: str | None = None,
    data_as_of: str | None = None,
    confidence: str | None = None,
    caveat: str | None = None,
    contradicts_claim_ids: list[str] | None = None,
) -> str:
    """Append traceable evidence to a finance research goal.

    Args:
        goal_id: Goal being mutated.
        expected_goal_id: Goal id captured before the tool/model turn started.
        text: Evidence note or result summary.
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
        criterion_id: Optional criterion this evidence satisfies.
        claim_id: Optional claim this evidence supports or contradicts.
        evidence_type: Evidence category, default evidence.
        tool_call_id: Source tool call id for traceability; it does not verify evidence by itself.
        run_id: Vibe-Trading run id. It verifies evidence only when the run directory exists.
        source_provider: Data/provider name such as yfinance, OKX, tushare.
        source_type: Source category such as market_data, document, backtest.
        source_uri: Optional source URL/path.
        symbol_universe: Symbols covered by the evidence.
        benchmark: Benchmark symbols covered by the evidence.
        timeframe: Market timeframe.
        method: Research method used.
        assumptions: Structured assumptions.
        artifact_path: Artifact path. It verifies evidence only when allowed by path policy and paired with a matching sha256 hash.
        artifact_hash: Required sha256 when artifact_path should verify evidence.
        data_as_of: ISO timestamp/date for data freshness.
        confidence: Optional confidence label.
        caveat: Optional limitation note.
        contradicts_claim_ids: Claim ids contradicted by this evidence.
    """
    try:
        from src.goal import EvidenceInput, StaleGoalError

        evidence = get_goal_store().append_evidence(
            session_id=resolve_session_id(session_id),
            goal_id=goal_id.strip(),
            expected_goal_id=expected_goal_id.strip(),
            evidence=EvidenceInput(
                criterion_id=blank_to_none(criterion_id),
                claim_id=blank_to_none(claim_id),
                evidence_type=evidence_type,
                text=text,
                tool_call_id=blank_to_none(tool_call_id),
                run_id=blank_to_none(run_id),
                source_provider=blank_to_none(source_provider),
                source_type=blank_to_none(source_type),
                source_uri=blank_to_none(source_uri),
                symbol_universe=clean_list(symbol_universe),
                benchmark=clean_list(benchmark),
                timeframe=blank_to_none(timeframe),
                method=blank_to_none(method),
                assumptions=assumptions or {},
                artifact_path=blank_to_none(artifact_path),
                artifact_hash=blank_to_none(artifact_hash),
                data_as_of=blank_to_none(data_as_of),
                confidence=blank_to_none(confidence),
                caveat=blank_to_none(caveat),
                contradicts_claim_ids=clean_list(contradicts_claim_ids),
            ),
        )
        snapshot = get_goal_store().get_goal_snapshot(goal_id.strip())
        if snapshot is None:
            return json_error("Goal snapshot could not be reloaded")
        from dataclasses import asdict

        return json_ok(evidence=asdict(evidence), snapshot=snapshot)
    except StaleGoalError as exc:
        return json_error(str(exc), error_type="stale_goal")
    except ValueError as exc:
        return json_error(str(exc), error_type="validation")


def update_research_goal_status(
    goal_id: str,
    expected_goal_id: str,
    status: str,
    session_id: str = "",
    audit: list[dict[str, Any]] | None = None,
    recap: str | None = None,
) -> str:
    """Update a finance research goal status after an audit.

    Use this to complete, cancel, block, pause, or otherwise move the current
    goal through its lifecycle. ``complete`` requires one audit row per
    required criterion and verified evidence for satisfied rows.

    Args:
        goal_id: Goal being mutated.
        expected_goal_id: Goal id captured before the tool/model turn started.
        status: Goal lifecycle status, e.g. complete, cancelled, blocked.
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
        audit: Optional list of criterion audit rows.
        recap: Optional concise status recap.
    """
    try:
        from src.goal import GoalStatus, StaleGoalError

        updated = get_goal_store().update_status(
            session_id=resolve_session_id(session_id),
            goal_id=goal_id.strip(),
            expected_goal_id=expected_goal_id.strip(),
            status=GoalStatus(status),
            audit=audit_rows_from_payload(audit),
            recap=blank_to_none(recap),
        )
        snapshot = get_goal_store().get_goal_snapshot(updated.goal_id)
        if snapshot is None:
            return json_error("Goal snapshot could not be reloaded")
        return json_ok(goal=snapshot["goal"], snapshot=snapshot)
    except StaleGoalError as exc:
        return json_error(str(exc), error_type="stale_goal")
    except ValueError as exc:
        return json_error(str(exc), error_type="validation")


def register(mcp: FastMCP) -> None:
    """Register the research-goal tools with the FastMCP instance."""
    mcp.tool()(start_research_goal)
    mcp.tool()(get_research_goal)
    mcp.tool()(add_goal_evidence)
    mcp.tool()(update_research_goal_status)
