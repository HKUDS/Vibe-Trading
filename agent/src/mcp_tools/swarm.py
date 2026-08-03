"""MCP swarm orchestration, status, and history tools."""

from __future__ import annotations

import json

from fastmcp import Context, FastMCP

from src.mcp_tools._shared import include_shell_tools


def _get_swarm_store():
    from src.swarm.store import SwarmStore, swarm_runs_root

    swarm_dir = swarm_runs_root()
    swarm_dir.mkdir(parents=True, exist_ok=True)
    return SwarmStore(base_dir=swarm_dir)


def _run_to_dict(run, *, timed_out: bool = False, is_stale: bool = False) -> dict:
    """Public projection of a (live-hydrated) :class:`SwarmRun`.

    ``timed_out`` flips on only for the ``run_swarm`` wait-budget path. It does
    not change the run's actual status — callers can still see ``running`` and
    fetch the final report later via :func:`get_run_result`.

    ``is_stale`` is a read-only signal: ``True`` means the run is still
    ``running`` but its events.jsonl has been silent past the per-run
    threshold. No disk state is changed by setting this — the explicit
    :func:`reap_stale_runs` tool is what finalizes a stale run.
    """
    from src.swarm.serialization import run_level_error, serialize_task

    return {
        "run_id": run.id,
        "status": run.status.value,
        "preset": run.preset_name,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "error": run_level_error(run),
        "tasks": [serialize_task(t) for t in run.tasks],
        "final_report": run.final_report,
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "timed_out": timed_out,
        "is_stale": is_stale,
    }


def _build_run_payload(store, run_id: str, preset_name: str | None, *, timed_out: bool) -> dict:
    """Reconcile + project a run for the MCP response.

    Used by ``run_swarm`` (polling + start_only). Returns a normal payload on
    success and a ``{"status": "error", ...}`` envelope when the run record
    disappears (mid-run directory wipe / sandbox eviction).
    """
    run = store.load_run(run_id)
    if run is None:
        return {"status": "error", "error": "Run record lost", "run_id": run_id}
    reconciled = store.reconcile_run(run, write=True)
    payload = _run_to_dict(
        reconciled,
        timed_out=timed_out,
        is_stale=store.is_run_stale(reconciled),
    )
    if preset_name:
        payload["preset"] = preset_name
    return payload


def list_swarm_presets() -> str:
    """List available swarm multi-agent team presets.

    Each preset defines a team of specialized agents (e.g. investment committee,
    quant desk, risk committee) that collaborate on complex research tasks.
    Returns preset names, descriptions, agent counts, and required variables.
    """
    from src.swarm.presets import list_presets

    presets = list_presets()
    return json.dumps(presets, ensure_ascii=False, indent=2)


async def run_swarm(
    preset_name: str,
    variables: dict[str, str],
    wait_seconds: int = 3600,
    start_only: bool = False,
    ctx: Context | None = None,
) -> str:
    """Run a swarm multi-agent team and stream progress back to the caller.

    Assembles a team of specialized agents that collaborate through a DAG workflow.
    For example, the 'investment_committee' preset runs bull analyst, bear analyst,
    risk officer, and portfolio manager in sequence.

    Use list_swarm_presets() to see available presets and their required variables.

    The tool keeps the MCP call open via ``Context.report_progress`` while the
    swarm runs, so the caller sees live "N/M tasks complete" updates instead
    of timing out silently. Only if ``wait_seconds`` is exhausted does the
    tool return early with the current ``run_id`` — call ``get_run_result``
    afterwards to fetch the final report.

    Args:
        preset_name: Swarm preset name (e.g. 'investment_committee', 'quant_strategy_desk').
        variables: Required variables for the preset (e.g. {"target": "AAPL.US", "market": "US"}).
        wait_seconds: Maximum seconds to keep the MCP call open. Default 3600
            (1 hour); the progress-notification keepalive means the transport
            stays connected for the full budget.
        start_only: If True, kick off the run and return immediately with
            ``run_id`` + current status. Ignores ``wait_seconds``.
    """
    import asyncio
    import time

    from src.config import load_swarm_agent_config
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore, swarm_runs_root

    swarm_dir = swarm_runs_root()
    store = SwarmStore(base_dir=swarm_dir)
    # Boot-time / operator-trusted: resolved from env var or on-disk config.
    # The MCP caller (this tool's invoker) cannot influence the path — the
    # ``variables`` arg below is template data, never config (R-06).
    agent_config = load_swarm_agent_config()
    runtime = SwarmRuntime(store=store, agent_config=agent_config)

    try:
        run = runtime.start_run(preset_name, variables, include_shell_tools=include_shell_tools())
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": f"DAG validation failed: {exc}"}, ensure_ascii=False)

    if start_only or wait_seconds <= 0:
        return json.dumps(
            _build_run_payload(store, run.id, preset_name, timed_out=False),
            ensure_ascii=False,
            indent=2,
        )

    # Surface the run_id immediately in a fixed-format progress message so a
    # caller whose transport drops mid-run (or whose MCP client enforces a
    # hard tool-call timeout that ignores progress notifications) can still
    # recover the run via ``get_run_result(run_id)``. Parsers should match
    # ``swarm_started run_id=<id>`` literally; later frames are free-form.
    if ctx is not None:
        try:
            await ctx.report_progress(
                progress=0,
                total=1,
                message=f"swarm_started run_id={run.id} preset={preset_name}",
            )
        except Exception:
            pass

    terminal = {"completed", "failed", "cancelled"}
    started_at = time.monotonic()
    deadline = started_at + wait_seconds
    while True:
        payload = _build_run_payload(store, run.id, preset_name, timed_out=False)
        if payload["status"] == "error":
            return json.dumps(payload, ensure_ascii=False)
        if payload["status"] in terminal:
            return json.dumps(payload, ensure_ascii=False, indent=2)

        # Emit a progress frame every loop, NOT only on state change — MCP
        # clients use these as transport keepalive. A long task that doesn't
        # transition for 30 minutes still needs ticks or the client times out.
        # ``elapsed`` keeps the message content fresh so dedup-on-message
        # clients still see updates.
        if ctx is not None:
            tasks = payload.get("tasks") or []
            total = max(1, len(tasks))
            done = sum(1 for t in tasks if t.get("status") in terminal)
            elapsed = int(time.monotonic() - started_at)
            try:
                await ctx.report_progress(
                    progress=done,
                    total=total,
                    message=f"{done}/{total} tasks complete · {elapsed}s elapsed (run {run.id})",
                )
            except Exception:
                pass

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            payload = _build_run_payload(store, run.id, preset_name, timed_out=True)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        await asyncio.sleep(min(5.0, remaining))


def get_swarm_status(run_id: str) -> str:
    """Get the current status of a swarm run.

    Returns status, task progress, token usage, and an ``is_stale`` flag for
    the specified run. Use this to poll a long-running swarm without blocking.

    Args:
        run_id: The run ID returned by run_swarm.
    """
    store = _get_swarm_store()
    try:
        run = store.load_run(run_id)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    if run is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)
    reconciled = store.reconcile_run(run, write=True)
    return json.dumps(
        _run_to_dict(reconciled, is_stale=store.is_run_stale(reconciled)),
        ensure_ascii=False,
        indent=2,
    )


def get_run_result(run_id: str) -> str:
    """Get the final report and task summaries of a swarm run.

    Reconciles the run on read: an orphaned ``running`` run whose host
    process exited will be transitioned to its real terminal status
    (``completed`` / ``failed`` / ``cancelled`` derived from the task
    statuses), so the caller never sees a permanent zombie.

    Args:
        run_id: The run ID returned by run_swarm.
    """
    store = _get_swarm_store()
    try:
        run = store.load_run(run_id)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    if run is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)
    reconciled = store.reconcile_run(run, write=True)
    payload = _run_to_dict(reconciled, is_stale=store.is_run_stale(reconciled))
    payload["ready"] = payload["status"] in {"completed", "failed", "cancelled"}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def list_runs(limit: int = 20) -> str:
    """List recent swarm runs sorted by creation time (newest first).

    Each row includes task counts and an ``is_stale`` flag so callers can
    spot abandoned runs without a follow-up status call.

    Args:
        limit: Maximum number of runs to return (default 20).
    """
    store = _get_swarm_store()
    runs = store.list_runs(limit=limit)
    items = []
    for run in runs:
        # write=True so a zombie listed alongside live runs gets finalized;
        # the cost is bounded by ``limit`` (default 20) and most rows are
        # already terminal — reconcile is a no-op for those.
        reconciled = store.reconcile_run(run, write=True)
        counts = {"total": len(reconciled.tasks)}
        for t in reconciled.tasks:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        items.append(
            {
                "run_id": reconciled.id,
                "preset": reconciled.preset_name,
                "status": reconciled.status.value,
                "is_stale": store.is_run_stale(reconciled),
                "created_at": reconciled.created_at,
                "completed_at": reconciled.completed_at,
                "task_counts": counts,
                "total_input_tokens": reconciled.total_input_tokens,
                "total_output_tokens": reconciled.total_output_tokens,
            }
        )
    return json.dumps(items, ensure_ascii=False, indent=2)


def reap_stale_runs() -> str:
    """Mark every ``running`` run whose host process died as ``failed``.

    Walks the swarm store, applies the per-run stale threshold, and
    finalizes any run that has gone silent past it (writes ``run.json`` +
    ``tasks/*.json`` + appends a ``run_reaped`` event). Already-terminal
    runs and still-alive runs are left untouched.

    Returns:
        JSON list of reaped run IDs (empty when nothing was stale).
    """
    store = _get_swarm_store()
    reaped = store.reap_stale_running_runs()
    return json.dumps({"reaped": reaped}, ensure_ascii=False, indent=2)


def retry_run(run_id: str) -> str:
    """Retry a failed, stale, or cancelled swarm run.

    Re-launches a brand-new run with the same preset and variables as the
    original; the original run is left untouched as a record. Use this after
    spotting a ``failed`` or stale run via ``list_runs``. A still-``running``
    run cannot be retried — cancel or reap it first.

    Args:
        run_id: ID of the run to retry (from ``list_runs`` / ``get_swarm_status``).

    Returns:
        JSON payload for the newly created run (``run_id`` / ``status`` /
        ``preset`` …), or an ``error`` object if the run is missing or active.
    """
    from src.config import load_swarm_agent_config
    from src.swarm.models import RunStatus
    from src.swarm.runtime import SwarmRuntime

    store = _get_swarm_store()
    try:
        loaded = store.load_run(run_id)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    if loaded is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)

    # Reconcile first so a zombie "running" run whose host died is demoted
    # before we gate on status; only a genuinely active run blocks retry.
    reconciled = store.reconcile_run(loaded, write=True)
    if reconciled.status == RunStatus.running:
        return json.dumps(
            {"status": "error", "error": "Cannot retry a running run. Cancel or reap it first."},
            ensure_ascii=False,
        )

    agent_config = load_swarm_agent_config()
    runtime = SwarmRuntime(store=store, agent_config=agent_config)
    try:
        new_run = runtime.start_run(
            reconciled.preset_name,
            reconciled.user_vars or {},
            include_shell_tools=include_shell_tools(),
        )
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": f"DAG validation failed: {exc}"}, ensure_ascii=False)

    return json.dumps(
        _build_run_payload(store, new_run.id, new_run.preset_name, timed_out=False),
        ensure_ascii=False,
        indent=2,
    )


def register(mcp: FastMCP) -> None:
    """Register the swarm orchestration and status tools."""
    mcp.tool()(list_swarm_presets)
    mcp.tool()(run_swarm)
    mcp.tool()(get_swarm_status)
    mcp.tool()(get_run_result)
    mcp.tool()(list_runs)
    mcp.tool()(reap_stale_runs)
    mcp.tool()(retry_run)
