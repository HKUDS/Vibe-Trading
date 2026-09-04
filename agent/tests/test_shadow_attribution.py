"""Attribution currency scoping (#14) and mutually exclusive buckets (#17).

A mixed HK+US journal used to have every roundtrip summed into real_pnl and
compared against a single-currency shadow pool, so HKD amounts leaked into a
USD delta. And the early/late conditions were subsets of not-within-rule, so
one trade landed in both noise and early/late and `explained` summed it
twice.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.shadow_account.backtester import _compute_attribution
from src.shadow_account.models import ShadowProfile, ShadowRule


def _profile() -> ShadowProfile:
    rule = ShadowRule(
        rule_id="R1",
        human_text="hold ~3d",
        entry_condition={"market": "us"},
        exit_condition={"holding_days": {"min": 2, "max": 5}},
        holding_days_range=(3, 3),
        support_count=10,
        coverage_rate=0.5,
        sample_trades=("AAPL@2026-01-10",),
    )
    return ShadowProfile(
        shadow_id="shadow_test",
        created_at="2026-01-01T00:00:00",
        journal_hash="test",
        source_market="us",
        profitable_roundtrips=10,
        total_roundtrips=20,
        date_range=("2025-01-01", "2026-01-01"),
        profile_text="test",
        rules=(rule,),
        preferred_markets=("us",),
        typical_holding_days=(3.0, 3.0),
    )


def _rt(symbol: str, pnl: float, hold_days: float) -> dict:
    return {
        "symbol": symbol,
        "buy_dt": pd.Timestamp("2026-01-01"),
        "sell_dt": pd.Timestamp("2026-01-01") + pd.Timedelta(days=hold_days),
        "qty": 10.0,
        "buy_price": 100.0,
        "sell_price": 100.0 + pnl / 10.0,
        "hold_days": hold_days,
        "pnl": pnl,
        "pnl_pct": pnl / 1000.0,
    }


def test_mixed_journal_excludes_other_currencies_from_real_pnl() -> None:
    roundtrips = [
        _rt("AAPL.US", 100.0, 3.0),
        _rt("0700.HK", 50.0, 3.0),
        _rt("9988.HK", -20.0, 3.0),
    ]
    breakdown, _, real_pnl = _compute_attribution(
        profile=_profile(), roundtrips=roundtrips, shadow_pnl=200.0, pool_currency="USD",
    )
    assert real_pnl == 100.0
    assert breakdown.excluded_currencies == {"HKD": 2}


def test_no_pool_currency_keeps_legacy_sum() -> None:
    roundtrips = [_rt("AAPL.US", 100.0, 3.0), _rt("0700.HK", 50.0, 3.0)]
    _, _, real_pnl = _compute_attribution(
        profile=_profile(), roundtrips=roundtrips, shadow_pnl=200.0,
    )
    assert real_pnl == 150.0


def test_short_winner_counts_once_in_early_not_noise() -> None:
    # hold 1d under the 3d rule with a win: early-exit only.
    breakdown, _, _ = _compute_attribution(
        profile=_profile(), roundtrips=[_rt("AAPL.US", 30.0, 1.0)], shadow_pnl=0.0,
    )
    assert breakdown.early_exit_pnl == pytest.approx(30.0 * (3 - 1) / 3)
    assert breakdown.noise_trades_pnl == 0.0


def test_long_loser_counts_once_in_late_not_noise() -> None:
    # hold 5d past the 3d rule with a loss: late-exit only.
    breakdown, _, _ = _compute_attribution(
        profile=_profile(), roundtrips=[_rt("AAPL.US", -30.0, 5.0)], shadow_pnl=0.0,
    )
    assert breakdown.late_exit_pnl == pytest.approx(30.0 * (5 - 3) / 3)
    assert breakdown.noise_trades_pnl == 0.0


def test_short_loser_is_noise_only() -> None:
    # hold 1d with a loss: not an early winner, so the whole -pnl is noise.
    breakdown, _, _ = _compute_attribution(
        profile=_profile(), roundtrips=[_rt("AAPL.US", -30.0, 1.0)], shadow_pnl=0.0,
    )
    assert breakdown.noise_trades_pnl == pytest.approx(30.0)
    assert breakdown.early_exit_pnl == 0.0
    assert breakdown.late_exit_pnl == 0.0
