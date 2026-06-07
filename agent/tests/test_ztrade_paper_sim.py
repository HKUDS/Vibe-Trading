"""Tests for ztrade V47 paper-simulation promotion."""

from __future__ import annotations

import json
from pathlib import Path

from src.tools import build_registry
from src.ztrade_autoresearch.paper_sim import run_ztrade_paper_sim
from src.ztrade_autoresearch.protocol import DEFAULT_V47_PARAMS, STRATEGY_FAMILY


def _write_params(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "candidate_id": "candidate_mutable_v47",
                "strategy_family": STRATEGY_FAMILY,
                "score": 381.89663,
                "params": DEFAULT_V47_PARAMS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def test_run_ztrade_paper_sim_synthetic_materializes_live_like_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    params_path = _write_params(tmp_path / "v47_params.json")
    run_dir = tmp_path / "paper_synthetic"

    state = run_ztrade_paper_sim(
        run_dir,
        params_path=params_path,
        mode="synthetic",
        window_start="2026-03-02",
        synthetic_periods=45,
        initial_cash=500_000,
    )

    assert state["status"] == "ok"
    assert state["no_broker"] is True
    assert state["execution"] == "local_paper_simulation"
    assert state["strategy"]["evaluator_score"] == 381.89663
    assert (run_dir / "code" / "signal_engine.py").exists()
    assert (run_dir / "config.json").exists()
    assert (run_dir / "artifacts" / "paper_state.json").exists()
    assert (run_dir / "artifacts" / "positions.csv").exists()
    assert "places_real_orders" in state["safety"]
    assert state["safety"]["places_real_orders"] is False


def test_ztrade_paper_sim_tool_is_registered_and_runs_synthetic(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    registry = build_registry()

    assert "ztrade_paper_sim" in registry.tool_names
    payload = json.loads(
        registry.execute(
            "ztrade_paper_sim",
            {
                "run_dir": str(tmp_path / "paper_tool"),
                "mode": "synthetic",
                "window_start": "2026-03-02",
                "max_symbols": 5,
            },
        )
    )
    assert payload["status"] == "ok"
    assert payload["no_broker"] is True
    assert payload["artifacts"]["paper_state"].endswith("paper_state.json")
