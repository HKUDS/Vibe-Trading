"""Fixed ztrade autoresearch protocol.

The protocol is deliberately code-owned, not agent-owned. Candidate changes
are limited to strategy parameters rendered into ``code/signal_engine.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


BASELINE_ID = "ztrade_v47_baseline"
STRATEGY_FAMILY = "ztrade_v47_weak_guard_62_70"


DEFAULT_V47_PARAMS: dict[str, Any] = {
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
    # Proposal: v47 search-space expansion (commit f8ac736) — per-trade risk knobs
    "per_trade_stop_loss_pct": 5.0,
    "per_trade_take_profit_pct": None,
    "rr_min_filter": 0.0,
}


SEARCH_SPACE: list[dict[str, Any]] = [
    {
        "id": BASELINE_ID,
        "role": "baseline",
        "params": {},
        "rationale": "Current ztrade DEFAULT_V3_PROFILE: v47_weak_guard_62_70.",
    },
    {
        "id": "candidate_volume_110",
        "role": "candidate",
        "params": {"s1_volume_ratio_min": 1.10},
        "rationale": "Loosen S1 bear-volume exclusion slightly to improve trade retention.",
    },
    {
        "id": "candidate_volume_135",
        "role": "candidate",
        "params": {"s1_volume_ratio_min": 1.35},
        "rationale": "Tighten S1 bear-volume exclusion to reduce low-quality reversals.",
    },
    {
        "id": "candidate_window_10",
        "role": "candidate",
        "params": {"s1_window": 10},
        "rationale": "Allow a wider S1 setup lookback while keeping max signal age fixed.",
    },
    {
        "id": "candidate_early_loss_050",
        "role": "candidate",
        "params": {"early_failure_loss_pct": 0.50},
        "rationale": "Make the early-failure exit more protective in weak starts.",
    },
]


ROLLING_WINDOWS: list[dict[str, Any]] = [
    {"id": "rw_trend_recovery", "seed": 11, "regime": "recovery", "start": "2025-07-01", "periods": 90},
    {"id": "rw_chop", "seed": 23, "regime": "chop", "start": "2025-10-01", "periods": 90},
    {"id": "rw_drawdown", "seed": 37, "regime": "drawdown", "start": "2026-01-02", "periods": 90},
    {"id": "rw_live_like", "seed": 41, "regime": "live_like", "start": "2026-03-02", "periods": 60},
]

FROZEN_CSV_START = "2023-12-28"
FROZEN_CSV_END = "2026-05-27"

FROZEN_BULL_INTERVALS: list[dict[str, str]] = [
    {"start": "2026-04-08", "end": "2026-05-27"},
    {"start": "2026-01-05", "end": "2026-02-02"},
    {"start": "2025-06-25", "end": "2025-09-04"},
    {"start": "2025-04-08", "end": "2025-04-16"},
    {"start": "2025-02-06", "end": "2025-02-28"},
    {"start": "2025-01-14", "end": "2025-01-27"},
    {"start": "2024-08-30", "end": "2024-11-14"},
    {"start": "2024-04-26", "end": "2024-05-15"},
    {"start": "2024-07-09", "end": "2024-07-23"},
    {"start": "2024-07-31", "end": "2024-08-12"},
    {"start": "2024-04-17", "end": "2024-05-15"},
    {"start": "2024-02-06", "end": "2024-03-25"},
    {"start": "2023-12-28", "end": "2024-01-17"},
]

ZTRADE_CSV_WINDOWS: list[dict[str, Any]] = []


@dataclass(frozen=True)
class GateConfig:
    return_delta_min_pct: float = 0.0
    average_max_drawdown_worsen_max_pct: float = 0.25
    loss_windows_max: int = 1
    fixed_loss_window_ratio_max: float = 0.25
    bear_return_delta_min_pct: float = 0.0
    bear_loss_window_ratio_max: float = 0.40
    bear_average_max_drawdown_worsen_max_pct: float = 0.25
    trade_retention_min: float = 0.80
    concentration_max: float = 0.60
    min_trades: int = 2
    # Proposal: v47 search-space expansion (commit f8ac736) — anti-overfit gates
    # from the 趋势起爆点 framework:
    #   false_ignition_miss_rate_max = "假启动误收率" cap
    #   per_window_r2_min = bull-window R:R coverage floor
    false_ignition_miss_rate_max: float = 0.30
    per_window_r2_min: float = 0.50


DEFAULT_GATES = GateConfig()


def merged_params(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return baseline V47 parameters with candidate overrides applied."""
    params = dict(DEFAULT_V47_PARAMS)
    params.update(overrides or {})
    return params


def protocol_payload() -> dict[str, Any]:
    """Machine-readable protocol snapshot for run artifacts."""
    return {
        "strategy_family": STRATEGY_FAMILY,
        "baseline_id": BASELINE_ID,
        "baseline_profile": "v47_weak_guard_62_70",
        "mutable_surface": [
            "Karpathy-style autoresearch/mutable/v47_params.json",
            "candidate strategy parameters rendered into code/signal_engine.py",
            "candidate-only Alpha Zoo indicator composition inside candidate_strategy.py",
            "helper functions only inside candidate_strategy.py",
        ],
        "immutable_surface": [
            "data windows",
            "evaluator gates",
            "backtest engine",
            "run card hashing",
            "KEEP/DISCARD decisions",
            "Alpha Zoo and swarm proposal contexts",
        ],
        "proposal_layer": [
            "swarm agents may analyze and propose one next experiment",
            "Alpha Zoo metadata may ground factor ideas",
            "neither proposal source may decide KEEP/DISCARD or edit the evaluator",
        ],
        "dependency_policy": "standard library plus existing project dependencies only",
        "frozen_csv_start": FROZEN_CSV_START,
        "frozen_csv_end": FROZEN_CSV_END,
        "frozen_bull_intervals": FROZEN_BULL_INTERVALS,
        "rolling_windows": ROLLING_WINDOWS,
        "ztrade_csv_windows": ZTRADE_CSV_WINDOWS,
        "gates": DEFAULT_GATES.__dict__,
        "search_space": SEARCH_SPACE,
    }


def _build_bull_bear_windows() -> list[dict[str, Any]]:
    frozen_start = date.fromisoformat(FROZEN_CSV_START)
    frozen_end = date.fromisoformat(FROZEN_CSV_END)
    bull_ranges = _merge_ranges(
        (date.fromisoformat(item["start"]), date.fromisoformat(item["end"])) for item in FROZEN_BULL_INTERVALS
    )
    windows: list[dict[str, Any]] = []
    cursor = frozen_start
    for start, end in bull_ranges:
        if start < frozen_start or end > frozen_end:
            raise ValueError("frozen bull interval outside CSV evaluation range")
        if cursor < start:
            bear_end = start - timedelta(days=1)
            windows.append(_window("bear", cursor, bear_end))
        windows.append(_window("bull", start, end))
        cursor = end + timedelta(days=1)
    if cursor <= frozen_end:
        windows.append(_window("bear", cursor, frozen_end))
    return windows


def _merge_ranges(ranges: Any) -> list[tuple[date, date]]:
    sorted_ranges = sorted(ranges)
    merged: list[tuple[date, date]] = []
    for start, end in sorted_ranges:
        if start > end:
            raise ValueError("frozen bull interval start is after end")
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _window(regime: str, start: date, end: date) -> dict[str, Any]:
    return {
        "id": f"{regime}_{start:%Y%m%d}_{end:%Y%m%d}",
        "type": "frozen",
        "regime": regime,
        "gate_role": "qualification" if start >= date(2025, 1, 1) else "veto",
        "veto_group": "bear" if regime == "bear" else "bull",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


ZTRADE_CSV_WINDOWS = _build_bull_bear_windows()
