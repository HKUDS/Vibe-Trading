"""Shadow result cache is keyed by window and journal hash, not shadow alone.

The report flow used to load `runs_dir(shadow_id)/shadow_result.json` with no
parameter check, so re-rendering a report with a different window silently
reused the previous run. The cache is now keyed by shadow + window + journal
hash; a different window deliberately misses.
"""

from __future__ import annotations

from src.shadow_account.backtester import _cache_key, _cache_result, load_cached_result
from src.shadow_account.models import (
    AttributionBreakdown,
    ShadowBacktestResult,
    ShadowProfile,
    ShadowRule,
)


def _profile() -> ShadowProfile:
    rule = ShadowRule(
        rule_id="R1",
        human_text="x",
        entry_condition={"market": "us"},
        exit_condition={"holding_days": {"min": 2, "max": 5}},
        holding_days_range=(3, 3),
        support_count=10,
        coverage_rate=0.5,
        sample_trades=("AAPL@2026-01-10",),
    )
    return ShadowProfile(
        shadow_id="shadow_cache_test",
        created_at="2026-01-01T00:00:00",
        journal_hash="hash-v1",
        source_market="us",
        profitable_roundtrips=10,
        total_roundtrips=20,
        date_range=("2025-01-01", "2026-01-01"),
        profile_text="test",
        rules=(rule,),
        preferred_markets=("us",),
        typical_holding_days=(3.0, 3.0),
    )


def _result() -> ShadowBacktestResult:
    return ShadowBacktestResult(
        shadow_id="shadow_cache_test",
        per_market={},
        combined={"final_value": 1_010_000.0},
        equity_curves={},
        attribution=AttributionBreakdown(
            missed_signals_pnl=0.0,
            noise_trades_pnl=0.0,
            early_exit_pnl=0.0,
            late_exit_pnl=0.0,
            overtrading_pnl=0.0,
            counterfactual_trades=(),
        ),
        shadow_total_pnl=10_000.0,
        real_total_pnl=9_000.0,
        delta_pnl=1_000.0,
    )


def test_cache_hits_only_on_exact_window_and_journal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    profile = _profile()
    from src.shadow_account.storage import runs_dir

    _cache_result(
        runs_dir(profile.shadow_id), _result(),
        profile=profile, window_start="2025-01-01", window_end="2026-01-01",
    )

    hit = load_cached_result(profile, window_start="2025-01-01", window_end="2026-01-01")
    assert hit is not None
    assert hit.shadow_total_pnl == 10_000.0

    # Different window must miss, not silently reuse the previous run.
    assert load_cached_result(profile, window_start="2025-06-01", window_end="2026-01-01") is None

    # A re-extracted journal (different hash) must miss too.
    other = ShadowProfile(**{**profile.__dict__, "journal_hash": "hash-v2"})
    assert load_cached_result(other, window_start="2025-01-01", window_end="2026-01-01") is None


def test_cache_key_changes_with_window_and_hash() -> None:
    profile = _profile()
    base = _cache_key(profile, "2025-01-01", "2026-01-01")
    assert base != _cache_key(profile, "2025-06-01", "2026-01-01")
    other = ShadowProfile(**{**profile.__dict__, "journal_hash": "hash-v2"})
    assert base != _cache_key(other, "2025-01-01", "2026-01-01")
    assert base == _cache_key(profile, "2025-01-01", "2026-01-01")
