"""Currency exclusions must be disclosed, not silently applied (#1310 follow-up).

`_compute_attribution` scopes real PnL to the shadow pool's settlement
currency, because there is no FX translation layer and summing across
currencies is meaningless. That is correct — but the report showed the
narrowed "your real PnL" with no indication that roundtrips had been dropped,
which is a quieter kind of wrong than the number it replaced.
"""

from __future__ import annotations

from pathlib import Path

from src.shadow_account.models import (
    AttributionBreakdown,
    ShadowBacktestResult,
    ShadowProfile,
    ShadowRule,
)
from src.shadow_account.reporter import render_shadow_report


def _profile() -> ShadowProfile:
    rule = ShadowRule(
        rule_id="R1",
        human_text="hold winners 3 days",
        entry_condition={"market": "us"},
        exit_condition={"holding_days": {"min": 2, "max": 5}},
        holding_days_range=(2, 5),
        support_count=10,
        coverage_rate=0.5,
        sample_trades=("AAPL@2026-01-10",),
    )
    return ShadowProfile(
        shadow_id="shadow_disclosure_test",
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


def _result(excluded: dict[str, int]) -> ShadowBacktestResult:
    return ShadowBacktestResult(
        shadow_id="shadow_disclosure_test",
        per_market={"us": {"final_value": 1_010_000.0}},
        combined={"final_value": 1_010_000.0},
        equity_curves={},
        attribution=AttributionBreakdown(
            missed_signals_pnl=100.0,
            noise_trades_pnl=-50.0,
            early_exit_pnl=20.0,
            late_exit_pnl=-10.0,
            overtrading_pnl=5.0,
            counterfactual_trades=(),
            excluded_currencies=excluded,
        ),
        shadow_total_pnl=10_000.0,
        real_total_pnl=9_000.0,
        delta_pnl=1_000.0,
    )


def _render(tmp_path: Path, excluded: dict[str, int]) -> str:
    out = render_shadow_report(
        _profile(), _result(excluded), output_dir=tmp_path
    )
    return Path(out["html_path"]).read_text(encoding="utf-8")


def test_excluded_currencies_are_disclosed(tmp_path: Path) -> None:
    html = _render(tmp_path, {"HKD": 2, "CNY": 1})
    assert "settlement currency only" in html
    assert "2 in HKD" in html
    assert "1 in CNY" in html


def test_no_disclosure_when_nothing_was_excluded(tmp_path: Path) -> None:
    """A single-currency journal must not carry a caveat that does not apply."""
    html = _render(tmp_path, {})
    assert "settlement currency only" not in html
