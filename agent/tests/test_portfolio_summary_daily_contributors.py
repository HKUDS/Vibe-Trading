"""daily_contributors: precomputed contribution ranking over every position,
before any truncation, using exactly the same fields that feed daily_change.

No calc, no Yahoo, no extra PPI call, no AC/TWR/attribution involved — this
only reshapes data already present in PortfolioService.analysis_context().
"""
from __future__ import annotations

import json

from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.portfolio_tool import (
    PortfolioSummaryTool,
    _build_daily_contributors,
    _reorder_for_truncation_safety,
)


def _position(symbol, value, pct, status="ready"):
    return {
        "symbol": symbol,
        "market_value_native": value,
        "daily_change_pct": pct,
        "daily_change_status": status,
    }


def _context(positions, daily_change_pct=None):
    return {
        "as_of": "2026-09-15T13:00:00-03:00",
        "complete": True,
        "totals": {"usd": 0.0, "cny": 0.0, "native_by_currency": {"ARS": sum(p["market_value_native"] for p in positions)}},
        "account_allocation": [{"broker_alias": "account_1", "status": "ok"}],
        "holdings": [{"symbol": p["symbol"]} for p in positions],
        "holdings_native": {"ARS": positions},
        "daily_change": {
            "pct": daily_change_pct,
            "as_of": "2026-09-15",
            "status": "ready" if daily_change_pct is not None else "unavailable",
            "source": "live_ppi_vs_canonical_eod",
            "method": "live_price_vs_canonical_eod_weighted_by_market_value",
            "coverage_pct": 100.0,
        },
        "risk_xray_args": {"symbols": [p["symbol"] for p in positions], "weights": [0.1] * len(positions)},
        "warnings": [],
        "privacy": "No account numbers, credentials, order IDs, names, or local paths included.",
    }


def test_contribution_sum_matches_daily_change_pct_when_fully_covered():
    positions = [
        _position("YPFD", 60_000.0, 2.0),
        _position("GGAL", 40_000.0, -1.0),
    ]
    expected_pct = (60_000 * 2.0 + 40_000 * -1.0) / 100_000
    context = _context(positions, daily_change_pct=round(expected_pct, 2))

    result = _build_daily_contributors(context)

    by_symbol = {c["symbol"]: c["contribution_pp"] for c in result["top_positive_contributors"]}
    assert round(sum(by_symbol.values()), 2) == round(expected_pct, 2)


def test_contribution_renormalizes_over_covered_subset_only():
    # One position lacks daily_change (status not ready) -- must be excluded
    # from both the ranking AND the weight denominator, not treated as 0%.
    positions = [
        _position("YPFD", 60_000.0, 2.0),
        _position("GD30", 20_000.0, None, status="no_local_buy_history"),
        _position("GGAL", 20_000.0, -1.0),
    ]
    context = _context(positions, daily_change_pct=1.25)  # (60000*2 + 20000*-1) / 80000

    result = _build_daily_contributors(context)

    assert result["covered_position_count"] == 2
    symbols = {c["symbol"] for c in result["top_positive_contributors"]}
    assert "GD30" not in symbols
    by_symbol = {c["symbol"]: c["contribution_pp"] for c in result["top_positive_contributors"]}
    assert round(sum(by_symbol.values()), 2) == 1.25


def test_ranking_uses_all_positions_not_a_truncated_subset():
    # 40 large positions plus one small position with the single biggest move;
    # it must still appear in top_positive_contributors even though it would
    # never survive a naive first-N-by-size truncation.
    big_positions = [_position(f"BIG{i}", 1_000_000.0, 0.1) for i in range(40)]
    small_mover = _position("TINYMOVER", 10_000.0, 50.0)
    positions = big_positions + [small_mover]
    context = _context(positions, daily_change_pct=0.4)

    result = _build_daily_contributors(context)

    assert result["covered_position_count"] == 41
    top_symbols = {c["symbol"] for c in result["top_positive_contributors"]}
    assert "TINYMOVER" in top_symbols
    top_mover_symbols = {c["symbol"] for c in result["top_movers_up"]}
    assert top_mover_symbols == {"TINYMOVER"} or "TINYMOVER" in top_mover_symbols


def test_no_covered_positions_returns_none():
    positions = [_position("GD30", 20_000.0, None, status="no_local_buy_history")]
    context = _context(positions, daily_change_pct=None)
    assert _build_daily_contributors(context) is None


def test_daily_contributors_placed_before_holdings_native_and_survives_truncation():
    positions = [_position(f"SYM{i}", 1_000_000.0 - i * 1000, (i % 5) - 2.0) for i in range(40)]
    context = _context(positions, daily_change_pct=0.1)
    context["daily_contributors"] = _build_daily_contributors(context)
    reordered = _reorder_for_truncation_safety(context)

    payload = json.dumps({"status": "ok", "context": reordered}, ensure_ascii=False)
    idx_contrib = payload.find('"daily_contributors"')
    idx_holdings_native = payload.find('"holdings_native"')
    assert 0 < idx_contrib < idx_holdings_native
    assert idx_contrib < TOOL_RESULT_LIMIT


def test_tool_execute_includes_daily_contributors(monkeypatch):
    positions = [_position(f"SYM{i}", 1_000_000.0 - i * 1000, (i % 5) - 2.0) for i in range(40)]
    context = _context(positions, daily_change_pct=0.1)
    monkeypatch.setattr(
        "src.tools.portfolio_tool.PortfolioService",
        lambda: type("_S", (), {"analysis_context": staticmethod(lambda: context)})(),
    )
    result = json.loads(PortfolioSummaryTool().execute())
    assert result["status"] == "ok"
    dc = result["context"]["daily_contributors"]
    assert dc["covered_position_count"] == 40
    assert len(dc["top_positive_contributors"]) <= 8
    assert len(dc["top_negative_contributors"]) <= 8
    assert len(dc["top_movers_up"]) <= 5
    assert len(dc["top_movers_down"]) <= 5
