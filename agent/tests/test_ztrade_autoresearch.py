from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from src.tools import build_registry
from src.ztrade_autoresearch.candidate_strategy import (
    ZTradeV47SignalEngine,
    _PendingSell,
    _Position,
    _qlib_cntd5,
    _qlib_cntd10,
    _qlib_cntd20,
    _qlib_cord10,
    _qlib_kup,
    _qlib_mom20,
    _qlib_roc10,
    _qlib_rsv10,
    _qlib_std10,
    _qlib_vma10,
    _with_indicators,
)
from backtest.engines.china_a import ChinaAEngine
from src.ztrade_autoresearch.evaluator import MetricRow, evaluate_candidate
from src.ztrade_autoresearch.protocol import BASELINE_ID, DEFAULT_V47_PARAMS, ZTRADE_CSV_WINDOWS
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
        "alpha_qlib_roc10_filter_enable": False,
        "alpha_qlib_roc10_min": -1.0,
        "alpha_qlib_roc10_max": 10.0,
        "alpha_qlib_rsv10_filter_enable": False,
        "alpha_qlib_rsv10_min": 0.0,
        "alpha_qlib_rsv10_max": 1.0,
        "entry_day_gain_max_pct": None,
        "regime_entry_day_gain_max_pct_bear": None,
        "alpha_qlib_roc10_score_weight": 0.0,
        "alpha_qlib_mom20_score_weight": 0.0,
        "alpha_qlib_cntd5_score_weight": 0.0,
        "alpha_qlib_cntd10_score_weight": 0.0,
        "alpha_qlib_cntd20_score_weight": 0.0,
        "alpha_qlib_vma10_score_weight": 0.0,
        "alpha_qlib_rsv10_score_weight": 0.0,
        "alpha_qlib_std10_score_weight": 0.0,
        "alpha_qlib_kup_score_weight": 0.0,
        "alpha_qlib_cord10_score_weight": 0.0,
        "alpha_qlib_max_positions": 4,
        "bull_continuation_fallback_enable": False,
        "bull_continuation_roc10_min": 0.02,
        "bull_continuation_roc10_max": 0.20,
        "bull_continuation_mom20_min": 0.03,
        "bull_continuation_rsv10_min": 0.55,
        "bull_continuation_rsv10_max": 0.95,
        "bull_continuation_entry_gain_max_pct": 5.0,
        "bull_continuation_volume_ratio_min": 0.8,
        "bull_continuation_market_min_coverage": 0,
        "bull_continuation_below_ma_ratio_max": 1.0,
        "bull_continuation_down_ratio_max": 1.0,
        "bull_continuation_max_hold_days": 0,
        "regime_position_sizing_enable": False,
        "bull_position_weight": 1.0,
        "bear_position_weight": 1.0,
        "allow_leverage": False,
    }


def test_ztrade_csv_windows_follow_frozen_bull_bear_protocol() -> None:
    expected_windows = [
        ("bull", "2023-12-28", "2024-01-17"),
        ("bear", "2024-01-18", "2024-02-05"),
        ("bull", "2024-02-06", "2024-03-25"),
        ("bear", "2024-03-26", "2024-04-16"),
        ("bull", "2024-04-17", "2024-05-15"),
        ("bear", "2024-05-16", "2024-07-08"),
        ("bull", "2024-07-09", "2024-07-23"),
        ("bear", "2024-07-24", "2024-07-30"),
        ("bull", "2024-07-31", "2024-08-12"),
        ("bear", "2024-08-13", "2024-08-29"),
        ("bull", "2024-08-30", "2024-11-14"),
        ("bear", "2024-11-15", "2025-01-13"),
        ("bull", "2025-01-14", "2025-01-27"),
        ("bear", "2025-01-28", "2025-02-05"),
        ("bull", "2025-02-06", "2025-02-28"),
        ("bear", "2025-03-01", "2025-04-07"),
        ("bull", "2025-04-08", "2025-04-16"),
        ("bear", "2025-04-17", "2025-06-24"),
        ("bull", "2025-06-25", "2025-09-04"),
        ("bear", "2025-09-05", "2026-01-04"),
        ("bull", "2026-01-05", "2026-02-02"),
        ("bear", "2026-02-03", "2026-04-07"),
        ("bull", "2026-04-08", "2026-05-27"),
    ]
    actual_windows = [(item["regime"], item["start"], item["end"]) for item in ZTRADE_CSV_WINDOWS]

    assert actual_windows == expected_windows
    assert all(item["type"] == "frozen" for item in ZTRADE_CSV_WINDOWS)
    assert all(item["gate_role"] in {"qualification", "veto"} for item in ZTRADE_CSV_WINDOWS)
    assert all(item["veto_group"] in {"bull", "bear"} for item in ZTRADE_CSV_WINDOWS)
    assert [item["gate_role"] for item in ZTRADE_CSV_WINDOWS if item["start"] >= "2025-01-01"]
    assert all(item["gate_role"] == "veto" for item in ZTRADE_CSV_WINDOWS if item["start"] < "2025-01-01")
    assert all(item["id"] == f"{item['regime']}_{item['start'].replace('-', '')}_{item['end'].replace('-', '')}" for item in ZTRADE_CSV_WINDOWS)

    for previous, current in zip(ZTRADE_CSV_WINDOWS, ZTRADE_CSV_WINDOWS[1:]):
        previous_end = pd.Timestamp(previous["end"])
        current_start = pd.Timestamp(current["start"])
        assert current_start == previous_end + pd.Timedelta(days=1)


def test_evaluator_reports_runbook_veto_diagnostics() -> None:
    rows = [
        MetricRow(BASELINE_ID, "bear_a", "baseline", "2024-01-01", "2024-01-31", 1.0, 12.0, 2.0, 4, 0.5, "bear"),
        MetricRow("candidate", "bear_a", "candidate", "2024-01-01", "2024-01-31", 0.5, 8.0, 2.1, 4, 0.5, "bear"),
        MetricRow(BASELINE_ID, "bull_a", "baseline", "2025-01-01", "2025-01-31", 1.0, 12.0, 2.0, 6, 0.5, "bull"),
        MetricRow("candidate", "bull_a", "candidate", "2025-01-01", "2025-01-31", 2.0, 24.0, 2.1, 6, 0.6, "bull"),
    ]

    verdict = evaluate_candidate(rows, baseline_id=BASELINE_ID, candidate_id="candidate", expected_window_count=2)

    assert verdict.diagnostics["expected_windows"] == 2
    assert verdict.diagnostics["bear_windows"] == 1
    assert verdict.diagnostics["bear_return_delta"] == -0.5
    assert verdict.diagnostics["candidate_trade_weighted_win_rate"] == pytest.approx(0.56)
    assert verdict.gates["coverage"] is True
    assert verdict.gates["bear_return_delta"] is False


def test_evaluator_stop_target_uses_current_user_annual_return_threshold() -> None:
    rows = [
        MetricRow(BASELINE_ID, "bull_a", "baseline", "2025-01-01", "2025-01-31", 1.0, 12.0, 2.0, 10, 0.4, "bull"),
        MetricRow("candidate", "bull_a", "candidate", "2025-01-01", "2025-01-31", 2.0, 31.0, 2.0, 10, 0.6, "bull"),
    ]

    verdict = evaluate_candidate(rows, baseline_id=BASELINE_ID, candidate_id="candidate", expected_window_count=1)

    assert verdict.diagnostics["stop_target_met"] is True


def test_mutable_v47_params_reject_leverage_under_current_protocol(tmp_path) -> None:
    workspace_dir = tmp_path / "autoresearch"
    initialize_karpathy_workspace(workspace_dir, mode="synthetic_smoke")
    mutable_path = workspace_dir / "mutable" / "v47_params.json"
    payload = json.loads(mutable_path.read_text(encoding="utf-8"))
    payload["params"]["allow_leverage"] = True
    mutable_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="allow_leverage is disabled"):
        load_mutable_v47_params(workspace_dir)


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


def test_v47_exposes_project_qlib_roc10_indicator_filter() -> None:
    close = pd.Series([10.0 + i for i in range(12)])
    assert _qlib_roc10(close).iloc[-1] == pytest.approx(21.0 / 11.0 - 1.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    params = dict(DEFAULT_V47_PARAMS)
    params.update(alpha_qlib_roc10_filter_enable=True, alpha_qlib_roc10_min=99.0)
    engine = ZTradeV47SignalEngine(**params)

    passed, _ = engine._passes_filters(hist)

    assert passed is False


def test_v47_exposes_project_mom20_indicator_score() -> None:
    close = pd.Series([10.0 + i for i in range(25)])
    assert _qlib_mom20(close).iloc[-1] == pytest.approx(34.0 / 14.0 - 1.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_mom20" in factors


def test_v47_exposes_project_qlib_cntd10_indicator_score() -> None:
    close = pd.Series([10.0, 11.0, 10.5, 10.25, 10.1, 10.0, 9.8, 10.2, 10.3, 10.1, 10.0])
    assert _qlib_cntd10(close).iloc[-1] == pytest.approx(3.0 - 7.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_cntd10" in factors


def test_v47_exposes_project_qlib_cntd5_indicator_score() -> None:
    close = pd.Series([10.0, 11.0, 10.5, 10.25, 10.1, 10.0])
    assert _qlib_cntd5(close).iloc[-1] == pytest.approx(1.0 - 4.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_cntd5" in factors


def test_v47_exposes_project_qlib_cntd20_indicator_score() -> None:
    close = pd.Series([10.0, 11.0] * 10 + [10.5])
    assert _qlib_cntd20(close).iloc[-1] == pytest.approx(10.0 - 10.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_cntd20" in factors


def test_v47_exposes_project_qlib_vma10_indicator_score() -> None:
    volume = pd.Series([10.0] * 9 + [20.0])
    assert _qlib_vma10(volume).iloc[-1] == pytest.approx(11.0 / 20.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_vma10" in factors


def test_v47_exposes_project_qlib_rsv10_indicator_score() -> None:
    frame = pd.DataFrame(
        {
            "close": [float(i) for i in range(1, 11)],
            "high": [float(i) + 1.0 for i in range(1, 11)],
            "low": [float(i) - 1.0 for i in range(1, 11)],
        }
    )
    assert _qlib_rsv10(frame).iloc[-1] == pytest.approx((10.0 - 0.0) / (11.0 - 0.0))

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_rsv10" in factors


def test_v47_can_filter_project_qlib_rsv10_range() -> None:
    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    params = dict(DEFAULT_V47_PARAMS)
    params.update(alpha_qlib_rsv10_filter_enable=True, alpha_qlib_rsv10_min=1.1)
    engine = ZTradeV47SignalEngine(**params)

    passed, factors = engine._passes_filters(hist)

    assert passed is False
    assert factors is None


def test_v47_can_filter_entry_day_gain() -> None:
    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    params = dict(DEFAULT_V47_PARAMS)
    params.update(entry_day_gain_max_pct=-10.0)
    engine = ZTradeV47SignalEngine(**params)

    passed, factors = engine._passes_filters(hist)

    assert passed is False
    assert factors is None


def test_v47_exposes_project_qlib_std10_indicator_score() -> None:
    close = pd.Series([float(i) for i in range(1, 11)])
    assert _qlib_std10(close).iloc[-1] == pytest.approx(close.std() / 10.0)

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_std10" in factors


def test_v47_exposes_project_qlib_kup_indicator_score() -> None:
    frame = pd.DataFrame({"open": [10.0, 10.0], "high": [12.0, 11.0], "close": [11.0, 9.0]})
    assert _qlib_kup(frame).tolist() == pytest.approx([0.1, 0.1])

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_kup" in factors


def test_v47_exposes_project_qlib_cord10_indicator_score() -> None:
    frame = pd.DataFrame(
        {
            "close": [10.0, 10.2, 10.1, 10.4, 10.6, 10.5, 10.8, 11.0, 10.9, 11.3, 11.5],
            "volume": [100.0, 108.0, 103.0, 115.0, 121.0, 118.0, 130.0, 141.0, 136.0, 150.0, 162.0],
        }
    )
    close_ret = frame["close"] / frame["close"].shift(1)
    volume_log_ret = np.log((frame["volume"] + 1.0) / (frame["volume"].shift(1) + 1.0))
    expected = close_ret.rolling(window=10, min_periods=10).corr(volume_log_ret)
    assert _qlib_cord10(frame).iloc[-1] == pytest.approx(expected.iloc[-1])

    data = _synthetic_data_map(11, "2025-07-01", 160, "recovery")["000001.SZ"]
    hist = _with_indicators(data).loc[: "2025-11-03"].tail(200)
    engine = ZTradeV47SignalEngine(**DEFAULT_V47_PARAMS)

    passed, factors = engine._passes_filters(hist)

    assert passed is True
    assert factors
    assert "qlib_cord10" in factors


def test_v47_regime_position_sizing_can_leave_cash() -> None:
    params = dict(DEFAULT_V47_PARAMS)
    params.update(regime_position_sizing_enable=True, bull_position_weight=1.0, bear_position_weight=0.5)
    engine = ZTradeV47SignalEngine(**params, max_positions=4)

    assert engine._position_weight(_Position("000001.SZ", 0, 10.0, 1.0, entry_market_weak=False)) == 1.0
    assert engine._position_weight(_Position("000001.SZ", 0, 10.0, 1.0, entry_market_weak=True)) == 0.5


def test_v47_leverage_flag_controls_signal_clip() -> None:
    params = dict(DEFAULT_V47_PARAMS)
    params.update(regime_position_sizing_enable=True, bull_position_weight=8.0, allow_leverage=True)
    engine = ZTradeV47SignalEngine(**params, max_positions=4)
    leveraged = pd.Series([engine._position_weight(_Position("000001.SZ", 0, 10.0, 1.0)) / 4.0])

    assert leveraged.clip(lower=0.0, upper=None).iloc[0] == pytest.approx(2.0)


def test_v47_alpha_qlib_max_positions_overrides_selector_slots() -> None:
    params = dict(DEFAULT_V47_PARAMS)
    params.update(alpha_qlib_max_positions=8)

    engine = ZTradeV47SignalEngine(**params, max_positions=4)

    assert engine.max_positions == 8


def test_v47_bear_entry_gain_cap_overrides_default_cap() -> None:
    close = [10.0, 10.2, 10.1, 10.3, 10.4, 10.2, 10.5, 10.4, 10.6, 10.5, 10.7]
    close.extend([10.6, 10.8, 10.7, 10.9, 10.8, 11.0, 10.9, 11.1, 10.0, 10.3])
    hist = pd.DataFrame(
        {
            "close": close,
            "volume": [1_000.0] * len(close),
            "红柱": [False] * (len(close) - 1) + [True],
            "绿柱": [False] * (len(close) - 3) + [True, True, False],
        }
    )
    params = dict(DEFAULT_V47_PARAMS)
    params.update(entry_day_gain_max_pct=2.0, regime_entry_day_gain_max_pct_bear=4.0)
    engine = ZTradeV47SignalEngine(**params)

    assert engine._passes_backtest_prefilter(hist, market_weak=False) is False
    assert engine._passes_backtest_prefilter(hist, market_weak=True) is True


def test_v47_bull_continuation_fallback_projects_factor_surface() -> None:
    dates = pd.bdate_range("2026-01-01", periods=80)
    close = pd.Series([10 + i * 0.04 for i in range(80)], index=dates)
    close.iloc[-25:] += [i * 0.03 for i in range(25)]
    open_ = close.shift(1).fillna(close.iloc[0]) * 0.998
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.005
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.995
    volume = pd.Series(1_000_000.0, index=dates)
    volume.iloc[-1] = 1_200_000.0
    hist = _with_indicators(
        pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)
    )

    params = dict(DEFAULT_V47_PARAMS)
    params.update(bull_continuation_fallback_enable=True)
    engine = ZTradeV47SignalEngine(**params)

    factors = engine._passes_bull_continuation_filters(hist)

    assert factors is not None
    assert factors["qlib_roc10"] > params["bull_continuation_roc10_min"]
    assert factors["qlib_mom20"] > params["bull_continuation_mom20_min"]
    assert params["bull_continuation_rsv10_min"] < factors["qlib_rsv10"] < params["bull_continuation_rsv10_max"]


def test_v47_bull_continuation_market_gate_uses_breadth_state() -> None:
    params = dict(DEFAULT_V47_PARAMS)
    params.update(
        bull_continuation_market_min_coverage=100,
        bull_continuation_below_ma_ratio_max=0.40,
        bull_continuation_down_ratio_max=0.55,
    )
    engine = ZTradeV47SignalEngine(**params)

    assert engine._bull_continuation_market_ok({"covered": 120, "below_ma_ratio": 0.30, "down_ratio": 0.50})
    assert not engine._bull_continuation_market_ok({"covered": 80, "below_ma_ratio": 0.30, "down_ratio": 0.50})
    assert not engine._bull_continuation_market_ok({"covered": 120, "below_ma_ratio": 0.50, "down_ratio": 0.50})


def test_v47_bull_continuation_max_hold_applies_only_to_fallback_positions() -> None:
    idx = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    frame = pd.DataFrame(
        {
            "open": [10.0, 10.1, 10.2],
            "high": [10.2, 10.3, 10.4],
            "low": [9.9, 10.0, 10.1],
            "close": [10.0, 10.1, 10.2],
            "volume": [1_000_000] * 3,
            "红柱": [True, True, True],
            "绿柱": [False, False, False],
        },
        index=idx,
    )
    params = dict(DEFAULT_V47_PARAMS)
    params.update(bull_continuation_max_hold_days=1)
    engine = ZTradeV47SignalEngine(**params, max_hold_days=20)
    positions = {
        "s1": _Position("s1", buy_i=0, buy_price=10.0, entry_score=1.0, entry_source="s1"),
        "cont": _Position("cont", buy_i=0, buy_price=10.0, entry_score=1.0, entry_source="continuation"),
    }

    engine._detect_exits(idx[1], 1, {"s1": frame, "cont": frame}, pd.DataFrame(), positions, {})

    assert "s1" in positions
    assert "cont" not in positions


def test_china_a_engine_respects_explicit_leverage_config() -> None:
    engine = ChinaAEngine({"initial_cash": 1_000_000, "leverage": 3.0})

    assert engine.default_leverage == pytest.approx(3.0)


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
    engine._passes_filters = (  # type: ignore[method-assign]
        lambda hist, **_: (bool(hist["close"].iloc[-1] == 10.0), factors)
    )
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
    summary = run_synthetic_research(tmp_path / "research", candidate_iterations=2, workspace_dir=workspace_dir)

    assert summary["status"] == "ok"
    assert summary["baseline_id"] == BASELINE_ID
    assert len(summary["iterations"]) == 2
    assert (tmp_path / "research" / "summary.json").exists()
    assert (tmp_path / "research" / "metrics_rows.json").exists()
    assert (tmp_path / "research" / "run_status.json").exists()
    assert summary["run_status"]["completed"] == summary["run_status"]["total_jobs"]
    assert (workspace_dir / "program.md").exists()
    assert (workspace_dir / "evaluator_contract.md").exists()
    assert (workspace_dir / "results.tsv").exists()
    assert (workspace_dir / "results.template.tsv").exists()
    assert (workspace_dir / "latest_state.template.json").exists()
    assert (workspace_dir / "loop_config.json").exists()
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
        candidate_iterations=4,
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
    assert "Session Budget and Stop Contract" in program
    assert "Iteration Report Contract" in program
    assert "candidate_return_pct" in program
    assert "candidate_trade_weighted_win_rate" in program
    assert "annualized return is greater than `30%`" in program
    assert "allow_leverage=false" in program
    assert "Candidate Protocol Freeze" in program
    assert "Result Reuse and Force-Rerun Rules" in program
    assert "Promotion and Veto Gates" in program
    assert "Common Anti-Patterns" in program
    assert "candidate_iterations" in program
    assert "Context Packaging and Memory Recovery" in program
    assert "autoresearch/context/continuation_state.md" in program
    assert "context pressure" in program
    assert "are not stop conditions" in program
    assert "concrete next parameter experiment" in program
    assert "baseline value" in program
    assert "candidate value" in program
    assert "Do not write vague continuation language" in program
    assert "allowed parameter experiment" in program
    assert ("check" + "point") not in program.lower()

    evaluator_contract = (workspace_dir / "evaluator_contract.md").read_text(encoding="utf-8")
    assert "agent/src/ztrade_autoresearch/evaluator.py" in evaluator_contract
    assert "Alternate scoring paths are forbidden" in evaluator_contract
    assert "Do not hand-edit evaluator results" in evaluator_contract
    assert "autoresearch/results.template.tsv" in evaluator_contract
    assert "autoresearch/reports/iteration_<N>_<candidate_id>.md" in evaluator_contract
    assert "candidate_mean_annual_return_pct > 30.0" in evaluator_contract
    assert "Leverage is forbidden" in evaluator_contract
    assert "bear-window return delta" in evaluator_contract

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
    assert "bear_return_delta" in ledger.splitlines()[0]
    assert MUTABLE_CANDIDATE_ID in ledger
    assert (workspace_dir / "latest_state.json").exists()
    loop_config = json.loads((workspace_dir / "loop_config.json").read_text(encoding="utf-8"))
    assert loop_config["stop_conditions"]["candidate_trade_weighted_win_rate_min"] == 0.5
    assert loop_config["stop_conditions"]["candidate_mean_annual_return_pct_min"] == 30.0
    assert (
        loop_config["context_memory"]["continuation_state_path"]
        == "autoresearch/context/continuation_state.md"
    )
    assert loop_config["context_memory"]["recent_report_count"] == 5
    assert loop_config["context_memory"]["require_pack_before_context_boundary"] is True
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
        "rows": [{"win_rate": 0.5, "annual_return_pct": 0.0}],
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
        REPO_ROOT / "autoresearch" / "loop_config.json",
        REPO_ROOT / "autoresearch" / "mutable" / "v47_params.json",
        REPO_ROOT / "autoresearch" / "proposals" / "swarm_proposal_request.json",
    ]
    for path in required_json:
        assert path.exists(), path
        json.loads(path.read_text(encoding="utf-8"))
    assert (REPO_ROOT / "autoresearch" / "results.template.tsv").exists()
    program = (REPO_ROOT / "autoresearch" / "program.md").read_text(encoding="utf-8")
    assert "Context Packaging and Memory Recovery" in program
    assert "autoresearch/context/continuation_state.md" in program
    assert "concrete next parameter experiment" in program
    assert "Do not write vague continuation language" in program
    assert "allowed parameter experiment" in program
    assert ("check" + "point") not in program.lower()

    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "autoresearch/results.tsv",
            "autoresearch/latest_state.json",
            "autoresearch/context/continuation_state.md",
            "autoresearch/reports/iteration_0001_candidate.md",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "autoresearch/results.tsv" in ignored.stdout
    assert "autoresearch/latest_state.json" in ignored.stdout
    assert "autoresearch/context/continuation_state.md" in ignored.stdout
    assert "autoresearch/reports/iteration_0001_candidate.md" in ignored.stdout


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
                "candidate_iterations": 1,
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
        run_synthetic_research(tmp_path / "blocked", candidate_iterations=1)


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
        candidate_iterations=1,
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

    short_summary = run_ztrade_csv_research(
        tmp_path / "csv_short_window",
        data_dir=data_dir,
        candidate_iterations=0,
        max_symbols=2,
        workspace_dir=tmp_path / "autoresearch_short",
        windows=[
            {"id": "short_fixture", "type": "frozen", "regime": "bear", "start": "2026-01-05", "end": "2026-01-09"}
        ],
    )
    assert short_summary["universe_by_window"]["short_fixture"]


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
