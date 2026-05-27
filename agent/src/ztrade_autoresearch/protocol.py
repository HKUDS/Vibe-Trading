"""Fixed ztrade autoresearch protocol.

The protocol is deliberately code-owned, not agent-owned. Candidate changes
are limited to strategy parameters rendered into ``code/signal_engine.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BASELINE_ID = "ztrade_v47_baseline"
STRATEGY_FAMILY = "ztrade_v47_weak_guard_62_70"


DEFAULT_V47_PARAMS: dict[str, Any] = {
    "s1_window": 7,
    "s1_volume_ratio_min": 1.2,
    "s1_max_age": 2,
    "early_failure_exit_enable": True,
    "early_failure_max_hold_days": 2,
    "early_failure_loss_pct": 1.0,
    "early_failure_market_below_ma_ratio_min": 0.55,
    "early_failure_market_down_ratio_min": 0.50,
    "early_failure_weak_breadth_below_ma_ratio_max": 0.62,
    "early_failure_weak_breadth_down_ratio_max": 0.70,
    "trend_line_tolerance_pct": 1.5,
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
        "rationale": "Loosen volume confirmation slightly to improve trade retention.",
    },
    {
        "id": "candidate_volume_135",
        "role": "candidate",
        "params": {"s1_volume_ratio_min": 1.35},
        "rationale": "Tighten volume confirmation to reduce low-quality reversals.",
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

ZTRADE_CSV_WINDOWS: list[dict[str, Any]] = [
    {"id": "rw_2025_07", "type": "rolling", "regime": "recent", "start": "2025-07-01", "end": "2025-07-31"},
    {"id": "rw_2025_08", "type": "rolling", "regime": "recent", "start": "2025-08-01", "end": "2025-08-29"},
    {"id": "rw_2025_09", "type": "rolling", "regime": "weak", "start": "2025-09-01", "end": "2025-09-30"},
    {"id": "rw_2025_10", "type": "rolling", "regime": "rebound", "start": "2025-10-09", "end": "2025-10-31"},
    {"id": "rw_2025_11", "type": "rolling", "regime": "chop", "start": "2025-11-03", "end": "2025-11-28"},
    {"id": "rw_2025_12", "type": "rolling", "regime": "chop", "start": "2025-12-01", "end": "2025-12-31"},
    {"id": "rw_2026_01", "type": "rolling", "regime": "weak", "start": "2026-01-05", "end": "2026-01-30"},
    {"id": "rw_2026_02", "type": "rolling", "regime": "rebound", "start": "2026-02-02", "end": "2026-02-27"},
    {"id": "rw_2026_03", "type": "rolling", "regime": "mixed", "start": "2026-03-02", "end": "2026-03-31"},
    {"id": "rw_2026_04", "type": "rolling", "regime": "live_like", "start": "2026-04-01", "end": "2026-04-30"},
    {"id": "fw_2024_liquidity_selloff", "type": "fixed", "regime": "bear", "start": "2024-01-02", "end": "2024-02-08"},
    {"id": "fw_policy_rebound_2024", "type": "fixed", "regime": "chop", "start": "2024-09-24", "end": "2024-10-31"},
    {"id": "fw_recent_quarter_2026", "type": "fixed", "regime": "mixed", "start": "2026-01-05", "end": "2026-03-31"},
    {"id": "fw_april_2026_live_like", "type": "fixed", "regime": "live_like", "start": "2026-04-01", "end": "2026-04-30"},
]


@dataclass(frozen=True)
class GateConfig:
    return_delta_min_pct: float = 0.0
    average_max_drawdown_worsen_max_pct: float = 0.25
    loss_windows_max: int = 1
    trade_retention_min: float = 0.80
    concentration_max: float = 0.60
    min_trades: int = 2


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
            "candidate strategy parameters rendered into code/signal_engine.py",
            "helper functions only inside candidate_strategy.py",
        ],
        "immutable_surface": [
            "data windows",
            "search space",
            "evaluator gates",
            "backtest engine",
            "run card hashing",
        ],
        "dependency_policy": "standard library plus existing project dependencies only",
        "rolling_windows": ROLLING_WINDOWS,
        "ztrade_csv_windows": ZTRADE_CSV_WINDOWS,
        "gates": DEFAULT_GATES.__dict__,
        "search_space": SEARCH_SPACE,
    }
