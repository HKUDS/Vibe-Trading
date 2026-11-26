"""Regression: cmd_swarm_cancel (the --swarm-cancel flag / "/swarm cancel"
REPL command) must reach a run only known through the process-wide active-run
index (src/swarm/runtime.py's register_active_run/_ACTIVE_RUNS), not just one
its own freshly-constructed SwarmRuntime happened to start.

A run an agent tool call started (src/tools/swarm_tool.py) that kept running
in the background after its wait budget elapsed is registered there and
nowhere else -- src/api/swarm_routes.py's cancel endpoint already falls back
to cancel_indexed_run for exactly this case; cmd_swarm_cancel never did.
"""

from __future__ import annotations

from datetime import datetime, timezone

import cli._legacy as legacy
from src.swarm.models import RunStatus, SwarmRun
from src.swarm.runtime import register_active_run
from src.swarm.store import SwarmStore


def test_cancel_reaches_a_run_only_known_through_the_active_run_index(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(legacy, "SWARM_DIR", tmp_path)
    store = SwarmStore(base_dir=tmp_path)
    run = SwarmRun(
        id="run-abc123", preset_name="demo", status=RunStatus.running,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    store.create_run(run)

    signalled = []
    register_active_run(run.id, "session-xyz", lambda: signalled.append(run.id) or True)

    legacy.cmd_swarm_cancel(run.id)

    assert signalled == [run.id]
    assert "Cancel signal sent" in capsys.readouterr().out


def test_cancel_still_reports_failure_for_an_unknown_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(legacy, "SWARM_DIR", tmp_path)

    legacy.cmd_swarm_cancel("nonexistent-run")

    assert "not found or already finished" in capsys.readouterr().out


def test_cancel_records_a_durable_request_for_a_run_in_another_process(tmp_path, monkeypatch, capsys):
    """Regression for #2306 (remainder): a separate `--swarm-cancel` process
    shares no memory with the agent process, so the active-run index is empty
    for it and the in-process fallbacks cannot fire. It must leave a durable
    cancel request in the run dir for the owning runtime to pick up.
    """
    monkeypatch.setattr(legacy, "SWARM_DIR", tmp_path)
    store = SwarmStore(base_dir=tmp_path)
    run = SwarmRun(
        id="run-xproc",
        preset_name="demo",
        status=RunStatus.running,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    store.create_run(run)
    assert not store.cancel_requested(run.id)

    legacy.cmd_swarm_cancel(run.id)

    assert "Cancel signal sent" in capsys.readouterr().out
    assert store.cancel_requested(run.id)
    # Re-asking is idempotent: the marker is already there.
    legacy.cmd_swarm_cancel(run.id)
    assert "Cancel signal sent" in capsys.readouterr().out


def test_cancel_still_reports_failure_for_a_finished_run(tmp_path, monkeypatch, capsys):
    """A terminal run must not gain a cancel marker: there is no owner left
    to honour it, and reporting success would be a lie."""
    monkeypatch.setattr(legacy, "SWARM_DIR", tmp_path)
    store = SwarmStore(base_dir=tmp_path)
    run = SwarmRun(
        id="run-done",
        preset_name="demo",
        status=RunStatus.completed,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    store.create_run(run)

    legacy.cmd_swarm_cancel(run.id)

    assert "not found or already finished" in capsys.readouterr().out
    assert not store.cancel_requested(run.id)
