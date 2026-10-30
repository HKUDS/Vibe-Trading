"""Tests for local agent research goal tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.agent.skills import SkillsLoader
from src.goal import GoalStore
from src.tools.goal_tool import (
    AddGoalEvidenceTool,
    GetResearchGoalTool,
    StartResearchGoalTool,
    UpdateResearchGoalStatusTool,
    UpdateResearchGoalTool,
)


def test_local_goal_tools_use_injected_session(tmp_path: Path) -> None:
    """Agent tools can start, inspect, and mutate the current session goal."""
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    get = GetResearchGoalTool(default_session_id="session-1", store=store)
    add = AddGoalEvidenceTool(default_session_id="session-1", store=store)

    created = json.loads(
        start.execute(
            objective="Evaluate NVDA momentum as a research-only thesis.",
            criteria=["Define thesis", "Check price action"],
        )
    )

    assert created["status"] == "ok"
    assert created["snapshot"]["goal"]["session_id"] == "session-1"

    fetched = json.loads(get.execute())
    assert fetched["status"] == "ok"
    assert fetched["snapshot"]["goal"]["goal_id"] == created["snapshot"]["goal"]["goal_id"]

    evidence = json.loads(
        add.execute(
            criterion_index=2,
            text="NVDA outperformed QQQ over the last 5 sessions.",
            source_provider="pytest",
            source_type="manual_note",
        )
    )

    assert evidence["status"] == "ok"
    assert evidence["snapshot"]["evidence_count"] == 1
    assert (
        evidence["evidence"]["criterion_id"]
        == created["snapshot"]["criteria"][1]["criterion_id"]
    )


def test_goal_tool_without_session_returns_validation_error(tmp_path: Path) -> None:
    """Goal tools fail cleanly when no session id was injected or supplied."""
    store = GoalStore(tmp_path / "goals.db")
    result = json.loads(GetResearchGoalTool(store=store).execute())

    assert result["status"] == "error"
    assert result["error_type"] == "validation"
    assert "session_id" in result["error"]


def test_goal_tool_rejects_live_trading_objective(tmp_path: Path) -> None:
    """Local agent tools keep the research-only boundary."""
    store = GoalStore(tmp_path / "goals.db")
    tool = StartResearchGoalTool(default_session_id="session-1", store=store)

    result = json.loads(tool.execute(objective="Buy 1 BTC now."))

    assert result["status"] == "error"
    assert result["error_type"] == "validation"
    assert "live trading" in result["error"]


def test_registry_injects_session_id_into_goal_tools() -> None:
    """SessionService can build a registry with session-scoped goal tools."""
    from src.tools import build_registry

    registry = build_registry(session_id="session-xyz")
    tool = registry.get("start_research_goal")

    assert tool is not None
    assert getattr(tool, "_default_session_id") == "session-xyz"


def test_goal_tools_emit_mutation_events(tmp_path: Path) -> None:
    """Goal tools notify the host when they mutate session-scoped goal state."""
    store = GoalStore(tmp_path / "goals.db")
    events: list[tuple[str, dict]] = []

    def emit(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    start = StartResearchGoalTool(default_session_id="session-1", store=store, event_callback=emit)
    add = AddGoalEvidenceTool(default_session_id="session-1", store=store, event_callback=emit)

    created = json.loads(
        start.execute(
            objective="Evaluate NVDA momentum as a research-only thesis.",
            criteria=["Define thesis", "Check price action"],
        )
    )
    evidence = json.loads(
        add.execute(
            goal_id=created["snapshot"]["goal"]["goal_id"],
            criterion_index=1,
            text="Evidence from a local tool call.",
        )
    )

    assert created["status"] == "ok"
    assert evidence["status"] == "ok"
    assert [item[0] for item in events] == ["goal.created", "goal.evidence"]
    assert events[0][1]["goal"]["session_id"] == "session-1"
    assert events[1][1]["goal_id"] == created["snapshot"]["goal"]["goal_id"]


def test_goal_evidence_tool_binds_runtime_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Runtime run_dir artifacts become verified goal evidence automatically."""
    run_root = tmp_path / "runs"
    run_dir = run_root / "goal-tool-run"
    artifact = run_dir / "artifacts" / "metrics.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("symbol,return\nNVDA,0.12\n", encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(run_root))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(run_root))

    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    add = AddGoalEvidenceTool(default_session_id="session-1", store=store)
    created = json.loads(
        start.execute(
            objective="Evaluate NVDA momentum as a research-only thesis.",
            criteria=["Check price action"],
        )
    )

    result = json.loads(
        add.execute(
            goal_id=created["snapshot"]["goal"]["goal_id"],
            criterion_index=1,
            text="Generated metrics artifact for NVDA momentum.",
            source_provider="pytest",
            source_type="market_data",
            artifact_path="artifacts/metrics.csv",
            run_dir=str(run_dir),
        )
    )

    expected_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    evidence = result["evidence"]
    assert result["status"] == "ok"
    assert evidence["run_id"] == "goal-tool-run"
    assert evidence["artifact_path"] == str(artifact.resolve())
    assert evidence["artifact_hash"] == expected_hash
    assert evidence["verification_status"] == "verified"


def test_goal_evidence_rejects_absolute_artifact_path_from_another_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An absolute artifact_path from a different run must not be recorded
    under the current run_dir's claimed run_id.

    The relative-path branch already rejects a path that escapes run_dir;
    an absolute path pointing at a sibling run's artifact must be rejected
    the same way, not accepted with the current run's id attached to a hash
    that actually belongs to the other run.
    """
    run_root = tmp_path / "runs"
    current_run_dir = run_root / "current-run"
    other_run_dir = run_root / "other-run"
    current_artifact = current_run_dir / "artifacts" / "metrics.csv"
    other_artifact = other_run_dir / "artifacts" / "metrics.csv"
    current_artifact.parent.mkdir(parents=True)
    other_artifact.parent.mkdir(parents=True)
    current_artifact.write_text("symbol,return\nNVDA,0.12\n", encoding="utf-8")
    other_artifact.write_text("symbol,return\nAAPL,0.34\n", encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(run_root))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(run_root))

    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    add = AddGoalEvidenceTool(default_session_id="session-1", store=store)
    created = json.loads(
        start.execute(
            objective="Evaluate NVDA momentum as a research-only thesis.",
            criteria=["Check price action"],
        )
    )

    result = json.loads(
        add.execute(
            goal_id=created["snapshot"]["goal"]["goal_id"],
            criterion_index=1,
            text="Generated metrics artifact for NVDA momentum.",
            source_provider="pytest",
            source_type="market_data",
            artifact_path=str(other_artifact.resolve()),
            run_dir=str(current_run_dir),
        )
    )

    assert result["status"] == "error"
    assert "escapes" in result["error"]


def test_goal_evidence_preserves_exact_tool_call_provenance(tmp_path: Path) -> None:
    """Tool-backed goal evidence keeps the exact source call id beside its own evidence id."""
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    add = AddGoalEvidenceTool(default_session_id="session-1", store=store)
    created = json.loads(
        start.execute(
            objective="Audit one tool-backed metric.",
            criteria=["Record the metric provenance"],
        )
    )
    call_id = "call_iDflHZFxCGQG1VfvfLoNBXCk|fc_0fa4bc82"

    result = json.loads(
        add.execute(
            goal_id=created["snapshot"]["goal"]["goal_id"],
            criterion_index=1,
            text="The source tool returned the audited metric.",
            tool_call_id=call_id,
            source_provider="pytest",
            source_type="market_data",
        )
    )

    evidence = result["evidence"]
    assert result["status"] == "ok"
    assert evidence["evidence_id"].startswith("ev_")
    assert evidence["tool_call_id"] == call_id
    assert evidence["evidence_id"] != evidence["tool_call_id"]
    assert result["snapshot"]["evidence"][0]["tool_call_id"] == call_id


def test_goal_evidence_can_remain_manual_without_tool_call_id(tmp_path: Path) -> None:
    """Manual evidence does not acquire an invented tool provenance id."""
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    add = AddGoalEvidenceTool(default_session_id="session-1", store=store)
    created = json.loads(
        start.execute(
            objective="Record a manual research note.",
            criteria=["Record the note"],
        )
    )

    result = json.loads(
        add.execute(
            goal_id=created["snapshot"]["goal"]["goal_id"],
            criterion_index=1,
            text="Manual reasoning note.",
            source_provider="pytest",
            source_type="manual_note",
        )
    )

    assert result["status"] == "ok"
    assert result["evidence"]["tool_call_id"] is None


def test_goal_evidence_tool_schema_distinguishes_call_and_evidence_ids() -> None:
    """The always-visible tool schema tells the model which id belongs in grounding provenance."""
    description = AddGoalEvidenceTool.description
    call_description = AddGoalEvidenceTool.parameters["properties"]["tool_call_id"]["description"]

    assert "exact tool_call_id" in description
    assert "evidence_id (ev_...)" in description
    assert "copy its tool_call_id verbatim" in call_description
    assert "Never substitute an evidence_id" in call_description


def test_goal_status_tool_can_cancel_current_goal(tmp_path: Path) -> None:
    """Agent tools can move a current goal to a terminal status."""
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    update = UpdateResearchGoalStatusTool(default_session_id="session-1", store=store)
    created = json.loads(
        start.execute(
            objective="Evaluate NVDA momentum as a research-only thesis.",
            criteria=["Define thesis"],
        )
    )
    goal_id = created["snapshot"]["goal"]["goal_id"]

    result = json.loads(
        update.execute(
            goal_id=goal_id,
            expected_goal_id=goal_id,
            status="cancelled",
            recap="Cancelled during tool test.",
        )
    )

    assert result["status"] == "ok"
    assert result["snapshot"]["goal"]["status"] == "cancelled"
    assert store.get_current_snapshot("session-1") is None


def test_update_goal_tool_edits_objective_without_resetting_progress(tmp_path: Path) -> None:
    """The agent can refine an objective in place, unlike start_research_goal
    which would mint a new goal and reset all criteria to pending.
    """
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    add_evidence = AddGoalEvidenceTool(default_session_id="session-1", store=store)
    update = UpdateResearchGoalTool(default_session_id="session-1", store=store)

    created = json.loads(
        start.execute(
            objective="Evaluate NVDA momentum as a research-only thesis.",
            criteria=["Define thesis", "Check price action"],
        )
    )
    goal_id = created["snapshot"]["goal"]["goal_id"]
    add_evidence.execute(criterion_index=1, text="NVDA shows strong momentum.")

    result = json.loads(
        update.execute(objective="Evaluate NVDA and AMD momentum as a research-only thesis.")
    )

    assert result["status"] == "ok"
    snapshot = result["snapshot"]
    assert snapshot["goal"]["goal_id"] == goal_id
    assert snapshot["goal"]["objective"] == "Evaluate NVDA and AMD momentum as a research-only thesis."
    assert snapshot["evidence_count"] == 1
    assert [c["status"] for c in snapshot["criteria"]] == ["covered", "pending"]


def test_update_goal_tool_requires_a_field_to_change(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    update = UpdateResearchGoalTool(default_session_id="session-1", store=store)
    start.execute(objective="Evaluate NVDA momentum.", criteria=["Define thesis"])

    result = json.loads(update.execute())

    assert result == {"status": "error", "error_type": "validation", "error": "objective or ui_summary is required"}


def test_update_goal_tool_rejects_a_stale_expected_goal_id(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "goals.db")
    start = StartResearchGoalTool(default_session_id="session-1", store=store)
    update = UpdateResearchGoalTool(default_session_id="session-1", store=store)
    start.execute(objective="Evaluate NVDA momentum.", criteria=["Define thesis"])

    result = json.loads(
        update.execute(objective="A different objective.", expected_goal_id="not-the-real-id")
    )

    assert result["status"] == "error"
    assert result["error_type"] == "stale_goal"


def test_registry_injects_goal_event_callback() -> None:
    """SessionService can build goal tools that emit through the event bus."""
    from src.tools import build_registry

    events: list[tuple[str, dict]] = []
    registry = build_registry(
        session_id="session-xyz",
        event_callback=lambda event_type, data: events.append((event_type, data)),
    )
    tool = registry.get("start_research_goal")

    assert tool is not None
    assert getattr(tool, "_event_callback") is not None


def test_research_goal_skill_is_bundled() -> None:
    """The agent can load workflow guidance for self-managed goals."""
    content = SkillsLoader().get_content("research-goal")

    assert "start_research_goal" in content
    assert "add_goal_evidence" in content
    assert "exact `tool_call_id`" in content
    assert "`ev_...::field`" in content
