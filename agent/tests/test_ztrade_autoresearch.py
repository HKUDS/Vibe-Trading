from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from src.tools import build_registry
from src.ztrade_autoresearch.candidate_strategy import (
    ZTradeV47SignalEngine,
    _PendingSell,
    _Position,
    _with_indicators,
)
from src.ztrade_autoresearch.protocol import BASELINE_ID, DEFAULT_V47_PARAMS
from src.ztrade_autoresearch.research_loop import (
    MUTABLE_CANDIDATE_ID,
    initialize_karpathy_workspace,
    load_mutable_v47_params,
    write_results_tsv,
)
from src.ztrade_autoresearch.runner import (
    _synthetic_data_map,
    discover_ztrade_csv_universe,
    run_synthetic_research,
    run_ztrade_csv_research,
)


def _sample_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=90)
    close = pd.Series([20 + i * 0.06 for i in range(90)], index=dates)
    close.iloc[35:40] -= [1.5, 1.2, 0.9, 0.4, 0.0]
    open_ = close.shift(1).fillna(close.iloc[0]) * 0.995
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.01
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.99
    volume = pd.Series(1_000_000.0, index=dates)
    volume.iloc[40] = 2_500_000.0
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_strategy_generates_long_only_signals() -> None:
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)
    signals = engine.generate({"000001.SZ": _sample_frame()})

    series = signals["000001.SZ"]
    assert set(series.unique()).issubset({0.0, 1.0})
    assert series.index.equals(_sample_frame().index)


def test_default_v47_params_match_reference_profile() -> None:
    assert DEFAULT_V47_PARAMS == {
        "s1_window": 7,
        "s1_volume_ratio_min": 1.2,
        "s1_max_age": 2,
        "s1_stale_age_min": None,
        "s1_stale_volume_ratio_min": None,
        "early_failure_exit_enable": True,
        "early_failure_max_hold_days": 2,
        "early_failure_loss_pct": 1.0,
        "early_failure_market_weak_enable": True,
        "early_failure_market_ma_window": 20,
        "early_failure_market_min_coverage": 2000,
        "early_failure_market_below_ma_ratio_min": 0.55,
        "early_failure_market_down_ratio_min": 0.50,
        "early_failure_gap_guard_pct": 3.0,
        "early_failure_gap_guard_capitulation_pct": 6.0,
        "early_failure_gap_guard_capitulation_below_ma_ratio_max": 0.65,
        "early_failure_gap_guard_capitulation_down_ratio_max": 0.75,
        "early_failure_weak_breadth_guard_enable": True,
        "early_failure_weak_breadth_below_ma_ratio_max": 0.62,
        "early_failure_weak_breadth_down_ratio_max": 0.70,
    }


def test_v47_entry_uses_brick_filters_and_s1_exclusion() -> None:
    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)
    assert passed is True
    assert factors
    assert factors["brick_ratio"] > 0
    assert factors["dif_val"] >= 0

    s1_blocked = hist.copy()
    s1_blocked.iloc[-2, s1_blocked.columns.get_loc("close")] = s1_blocked.iloc[-3]["close"] * 0.98
    s1_blocked.iloc[-2, s1_blocked.columns.get_loc("volume")] = s1_blocked["volume"].tail(7).max() * 10
    blocked, _ = engine._passes_filters(s1_blocked)
    assert blocked is False


def test_v47_ranking_and_active_start_do_not_carry_warmup_positions() -> None:
    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS, max_positions=1, active_start_date="2025-11-05")

    signals = engine.generate(data)

    assert signals["600519.SH"].loc["2025-10-15"] == 0.0
    assert signals["000001.SZ"].loc["2025-11-05"] == 0.0
    assert signals["000001.SZ"].loc["2025-11-27"] == 1.0


def test_v47_uses_symbol_next_bar_for_buy_when_global_next_date_missing() -> None:
    signal_ts = pd.Timestamp("2026-01-02")
    missing_next = pd.DataFrame(
        {
            "open": [10.0, 10.5],
            "high": [10.2, 10.7],
            "low": [9.8, 10.3],
            "close": [10.0, 10.6],
            "volume": [1_000_000, 1_000_000],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-06"]),
    )
    other_symbol = pd.DataFrame(
        {
            "open": [20.0, 20.2],
            "high": [20.1, 20.3],
            "low": [19.9, 20.1],
            "close": [20.0, 20.2],
            "volume": [1_000_000, 1_000_000],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS, max_positions=1)
    factors = {"brick_ratio": 1.0, "vol_ratio": 1.0, "dif_val": 1.0, "gain_margin": 1.0, "near_score": 1.0}
    engine._passes_filters = lambda hist: (bool(hist["close"].iloc[-1] == 10.0), factors)  # type: ignore[method-assign]
    frames = {"000001.SZ": missing_next, "000002.SZ": other_symbol}
    positions: dict[str, _Position] = {}

    engine._select_buys(signal_ts, 0, pd.DatetimeIndex(sorted(set(missing_next.index) | set(other_symbol.index))), frames, positions, {})

    assert positions["000001.SZ"].buy_i == 1
    assert positions["000001.SZ"].buy_price == 10.5


def test_v47_max_hold_uses_symbol_calendar_not_union_calendar() -> None:
    idx = pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-12"])
    frame = pd.DataFrame(
        {
            "open": [10.0, 10.1, 10.2],
            "high": [10.2, 10.3, 10.4],
            "low": [9.8, 9.9, 10.0],
            "close": [10.0, 10.1, 10.2],
            "volume": [1_000_000, 1_000_000, 1_000_000],
            "红柱": [True, True, True],
            "绿柱": [False, False, False],
            "砖型图": [4.0, 5.0, 6.0],
        },
        index=idx,
    )
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS, max_hold_days=2)
    positions = {"000001.SZ": _Position("000001.SZ", buy_i=0, buy_price=10.0, entry_score=1.0, buy_trade_i=0)}

    engine._detect_exits(idx[1], 5, {"000001.SZ": frame}, pd.DataFrame(), positions, {})
    assert "000001.SZ" in positions

    engine._detect_exits(idx[2], 6, {"000001.SZ": frame}, pd.DataFrame(), positions, {})
    assert positions == {}


def test_v47_pending_sell_confirms_or_cancels_next_close() -> None:
    idx = pd.bdate_range("2026-01-01", periods=3)
    frame = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0],
            "high": [10.5, 10.5, 10.5],
            "low": [9.5, 9.5, 9.5],
            "close": [10.0, 9.8, 10.2],
            "volume": [1_000_000, 1_000_000, 1_000_000],
            "红柱": [True, False, True],
            "绿柱": [False, True, False],
            "砖型图": [5.0, 4.0, 5.0],
        },
        index=idx,
    )
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)
    positions = {"000001.SZ": _Position("000001.SZ", buy_i=0, buy_price=10.0, entry_score=1.0)}
    pending = {"000001.SZ": _PendingSell("000001.SZ", detect_i=1, stored_red_count=1)}

    engine._execute_pending(idx[2], 2, {"000001.SZ": frame}, positions, pending)

    assert "000001.SZ" in positions
    assert "000001.SZ" not in pending
    assert positions["000001.SZ"].red_count == 1


def test_v47_four_red_take_profit_uses_stored_red_count() -> None:
    idx = pd.bdate_range("2026-01-01", periods=6)
    frame = pd.DataFrame(
        {
            "open": [10.0, 10.1, 10.2, 10.3, 10.4, 10.5],
            "high": [10.5, 10.6, 10.7, 10.8, 10.9, 10.9],
            "low": [9.9, 10.0, 10.1, 10.2, 10.3, 10.1],
            "close": [10.0, 10.2, 10.3, 10.4, 10.5, 10.1],
            "volume": [1_000_000] * 6,
            "红柱": [False, True, True, True, True, False],
            "绿柱": [False, False, False, False, False, True],
            "砖型图": [4.0, 5.0, 6.0, 7.0, 8.0, 7.0],
        },
        index=idx,
    )
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)
    positions = {
        "000001.SZ": _Position("000001.SZ", buy_i=0, buy_price=10.0, entry_score=1.0, red_count=4)
    }
    pending: dict[str, _PendingSell] = {}

    engine._detect_exits(idx[5], 5, {"000001.SZ": frame}, pd.DataFrame(), positions, pending)

    assert positions == {}
    assert pending == {}


def test_v47_early_failure_gap_and_breadth_guards() -> None:
    params = {**DEFAULT_V47_PARAMS, "early_failure_market_min_coverage": 1}
    engine = ZTradeV47SignalEngine(**params)

    assert engine._early_failure_skip_reason(-2.0, True, {"below_ma_ratio": 0.60, "down_ratio": 0.60}) == ""
    assert engine._early_failure_skip_reason(-4.0, True, {"below_ma_ratio": 0.60, "down_ratio": 0.60}) == "gap_guard"
    assert (
        engine._early_failure_skip_reason(-7.0, True, {"below_ma_ratio": 0.60, "down_ratio": 0.60})
        == ""
    )
    assert (
        engine._early_failure_skip_reason(-2.0, True, {"below_ma_ratio": 0.80, "down_ratio": 0.60})
        == "market_too_weak"
    )


def test_synthetic_research_writes_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    workspace_dir = tmp_path / "autoresearch"
    summary = run_synthetic_research(tmp_path / "research", max_iterations=2, workspace_dir=workspace_dir)

    assert summary["status"] == "ok"
    assert summary["baseline_id"] == BASELINE_ID
    assert len(summary["iterations"]) == 2
    assert (tmp_path / "research" / "summary.json").exists()
    assert (tmp_path / "research" / "metrics_rows.json").exists()
    assert (workspace_dir / "program.md").exists()
    assert (workspace_dir / "evaluator_contract.md").exists()
    assert (workspace_dir / "results.tsv").exists()
    assert (workspace_dir / "results.template.tsv").exists()
    assert (workspace_dir / "latest_state.template.json").exists()
    assert not (tmp_path / "research" / "autoresearch").exists()
    assert list((tmp_path / "research").glob("*/rw_*/*run_card.json"))


def test_karpathy_workspace_preserves_mutable_candidate_and_writes_proposal_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run_dir = tmp_path / "karpathy_run"
    workspace_dir = tmp_path / "autoresearch"
    workspace = initialize_karpathy_workspace(workspace_dir, mode="synthetic_smoke")
    mutable_path = workspace_dir / "mutable" / "v47_params.json"
    payload = json.loads(mutable_path.read_text(encoding="utf-8"))
    payload["params"]["s1_volume_ratio_min"] = 1.35
    mutable_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = run_synthetic_research(
        run_dir,
        max_iterations=4,
        use_mutable_candidate=True,
        workspace_dir=workspace_dir,
    )

    assert summary["karpathy_workspace"]["mutable_candidate_id"] == MUTABLE_CANDIDATE_ID
    assert summary["karpathy_workspace"]["program"] == workspace["program"]
    assert load_mutable_v47_params(workspace_dir)["s1_volume_ratio_min"] == 1.35

    iterations = summary["iterations"]
    assert [record["candidate_id"] for record in iterations] == [MUTABLE_CANDIDATE_ID]

    program = (workspace_dir / "program.md").read_text(encoding="utf-8")
    assert "Swarm agents and Alpha Zoo are inside the Think step" in program
    assert "Required Evaluator Invocation" in program
    assert "NEVER STOP after a single iteration" in program
    assert "Baseline First" in program
    assert "Git Advance/Revert Discipline" in program
    assert "Timeouts and Crashes" in program
    assert "Simplicity Criterion" in program

    evaluator_contract = (workspace_dir / "evaluator_contract.md").read_text(encoding="utf-8")
    assert "agent/src/ztrade_autoresearch/evaluator.py" in evaluator_contract
    assert "Alternate scoring paths are forbidden" in evaluator_contract
    assert "Do not hand-edit evaluator results" in evaluator_contract
    assert "autoresearch/results.template.tsv" in evaluator_contract

    alpha_context = json.loads((workspace_dir / "context" / "alpha_zoo_context.json").read_text())
    assert alpha_context["status"] in {"ok", "unavailable"}
    assert "policy" in alpha_context

    swarm_request = json.loads((workspace_dir / "proposals" / "swarm_proposal_request.json").read_text())
    assert [role["role"] for role in swarm_request["roles"]] == [
        "factor_librarian",
        "v47_researcher",
        "regime_analyst",
        "overfit_skeptic",
        "proposal_writer",
    ]
    assert "autoresearch/evaluator_contract.md" in swarm_request["inputs"]
    assert "autoresearch/results.template.tsv" in swarm_request["inputs"]
    assert "do not decide KEEP or DISCARD" in swarm_request["hard_limits"]

    ledger = (workspace_dir / "results.tsv").read_text(encoding="utf-8")
    assert ledger.splitlines()[0].startswith("iteration\tcandidate_id\tverdict")
    assert MUTABLE_CANDIDATE_ID in ledger
    assert (workspace_dir / "latest_state.json").exists()
    assert not (run_dir / "autoresearch").exists()


def test_karpathy_results_tsv_appends_experiment_history(tmp_path) -> None:
    workspace_dir = tmp_path / "autoresearch"
    initialize_karpathy_workspace(workspace_dir, mode="synthetic_smoke")
    record = {
        "candidate_id": MUTABLE_CANDIDATE_ID,
        "verdict": "DISCARD",
        "score": 0.0,
        "reasons": ["return_delta"],
        "rationale": "fixture",
        "diagnostics": {
            "return_delta": 0.0,
            "average_max_drawdown_delta": 0.0,
            "trade_retention": 1.0,
            "candidate_trades": 2,
        },
        "rows": [{"win_rate": 0.5}],
    }

    write_results_tsv(workspace_dir, [record])
    write_results_tsv(workspace_dir, [record])

    lines = (workspace_dir / "results.tsv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[1].startswith("1\t")
    assert lines[2].startswith("2\t")


def test_repo_autoresearch_templates_and_ignore_policy() -> None:
    required_json = [
        REPO_ROOT / "autoresearch" / "best" / "v47_params.json",
        REPO_ROOT / "autoresearch" / "context" / "alpha_zoo_context.json",
        REPO_ROOT / "autoresearch" / "latest_state.template.json",
        REPO_ROOT / "autoresearch" / "mutable" / "v47_params.json",
        REPO_ROOT / "autoresearch" / "proposals" / "swarm_proposal_request.json",
    ]
    for path in required_json:
        assert path.exists(), path
        json.loads(path.read_text(encoding="utf-8"))
    assert (REPO_ROOT / "autoresearch" / "results.template.tsv").exists()

    ignored = subprocess.run(
        ["git", "check-ignore", "autoresearch/results.tsv", "autoresearch/latest_state.json"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "autoresearch/results.tsv" in ignored.stdout
    assert "autoresearch/latest_state.json" in ignored.stdout


def test_tool_registry_discovers_ztrade_autoresearch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    registry = build_registry()
    assert "ztrade_autoresearch" in registry.tool_names

    run_dir = tmp_path / "tool_run"
    payload = json.loads(
        registry.execute(
            "ztrade_autoresearch",
            {
                "run_dir": str(run_dir),
                "max_iterations": 1,
                "use_mutable_candidate": True,
                "workspace_dir": str(tmp_path / "autoresearch"),
            },
        )
    )
    assert payload["status"] == "ok"
    assert payload["karpathy_workspace"]["mutable_candidate_id"] == MUTABLE_CANDIDATE_ID


def test_ztrade_autoresearch_rejects_unconfigured_absolute_run_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)

    with pytest.raises(ValueError, match="outside allowed run roots"):
        run_synthetic_research(tmp_path / "blocked", max_iterations=1)


def test_ztrade_csv_research_uses_local_csv_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    data_dir = tmp_path / "ztrade_data"
    data_dir.mkdir()
    _write_csv(data_dir / "000001.csv", offset=0.0)
    _write_csv(data_dir / "600000.csv", offset=8.0)
    _write_csv(data_dir / "300750.csv", offset=20.0)

    universe = discover_ztrade_csv_universe(
        data_dir,
        start_date="2026-01-01",
        end_date="2026-03-31",
        max_symbols=2,
        min_rows=15,
    )
    assert len(universe) == 2
    assert all("." in code for code in universe)

    summary = run_ztrade_csv_research(
        tmp_path / "csv_research",
        data_dir=data_dir,
        max_iterations=1,
        max_symbols=2,
        workspace_dir=tmp_path / "autoresearch",
        windows=[
            {"id": "rw_fixture", "type": "rolling", "regime": "fixture", "start": "2026-01-01", "end": "2026-03-31"}
        ],
    )
    assert summary["status"] == "ok"
    assert summary["mode"] == "ztrade_csv"
    assert summary["universe_by_window"]["rw_fixture"]
    assert (tmp_path / "csv_research" / "candidate_volume_110" / "rw_fixture" / "run_card.json").exists()


def _write_csv(path, *, offset: float) -> None:
    dates = pd.bdate_range("2025-12-01", periods=100)
    close = pd.Series([20 + offset + i * 0.08 for i in range(100)], index=dates)
    close.iloc[35:39] -= [1.2, 1.0, 0.5, 0.0]
    frame = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close.shift(1).fillna(close.iloc[0]) * 0.997,
            "close": close,
            "high": close * 1.015,
            "low": close * 0.985,
            "volume": 1_000_000 + offset * 10_000,
        }
    )
    frame.to_csv(path, index=False)
