"""portfolio_summary must survive src.config.limits.truncate_tool_result.

That helper cuts any tool result at a flat 10,000-character offset with no
JSON awareness. A 40-position portfolio's holdings/holdings_native alone
exceed that on their own, so key order decides what a truncated caller
actually receives. These tests lock in that daily_change (and the other
small, portfolio-level aggregates) always sit before the large per-position
arrays, and that no field is dropped or mutated by the reordering.
"""
from __future__ import annotations

import json

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.tools.portfolio_tool import PortfolioSummaryTool, _reorder_for_truncation_safety


def _fake_context(n_positions: int = 40) -> dict:
    holdings_native = [
        {
            "symbol": f"SYM{i}",
            "source_instrument_id": f"accion:SYM{i}",
            "name": f"Company {i}",
            "asset_type": "ACCIONES",
            "market_value_native": 1000.0 * i,
            "native_currency": "ARS",
            "weight": 0.01,
            "exposure_currency": "ARS",
            "daily_change_pct": 0.5,
            "daily_change_as_of": "2026-09-15",
            "daily_change_source": "live_ppi_vs_canonical_eod",
            "daily_change_status": "ready",
        }
        for i in range(n_positions)
    ]
    return {
        "as_of": "2026-09-15T13:00:00-03:00",
        "complete": True,
        "totals": {"usd": 0.0, "cny": 0.0, "native_by_currency": {"ARS": 227_966_606.41}},
        "account_allocation": [{"broker_alias": "account_1", "status": "ok"}],
        "holdings": [{"symbol": f"SYM{i}"} for i in range(n_positions)],
        "holdings_native": {"ARS": holdings_native},
        "daily_change": {
            "pct": 0.4,
            "as_of": "2026-09-15",
            "status": "ready",
            "source": "live_ppi_vs_canonical_eod",
            "method": "live_price_vs_canonical_eod_weighted_by_market_value",
            "coverage_pct": 100.0,
        },
        "risk_xray_args": {"symbols": [f"SYM{i}" for i in range(n_positions)], "weights": [0.01] * n_positions},
        "warnings": [],
        "privacy": "No account numbers, credentials, order IDs, names, or local paths included.",
    }


def test_reorder_preserves_every_field_unchanged():
    context = _fake_context()
    reordered = _reorder_for_truncation_safety(context)
    assert reordered == context  # same keys/values, dict equality ignores order
    assert list(reordered.keys()) != list(context.keys())  # but order actually changed
    assert list(reordered.keys())[:4] == ["as_of", "complete", "totals", "daily_change"]


def test_reordered_daily_change_survives_real_truncation_limit():
    # Truncation slices mid-string (this is exactly the "no JSON awareness"
    # behavior being defended against), so the cut result need not re-parse
    # as JSON; what matters is that the daily_change object's own content is
    # fully present ahead of the cutoff, not sliced off.
    context = _fake_context(n_positions=40)
    reordered = _reorder_for_truncation_safety(context)
    payload = json.dumps({"status": "ok", "context": reordered}, ensure_ascii=False)
    assert len(payload) > TOOL_RESULT_LIMIT  # this scenario does truncate

    truncated = truncate_tool_result(payload, limit=TOOL_RESULT_LIMIT)
    daily_change_json = json.dumps(context["daily_change"], ensure_ascii=False)
    assert daily_change_json in truncated
    assert '"pct": 0.4' in truncated or '"pct":0.4' in truncated


def test_unreordered_result_would_have_lost_daily_change_before_the_fix():
    # Documents the bug this fix closes: the original key order (holdings/
    # holdings_native before daily_change) drops the aggregate once truncated.
    context = _fake_context(n_positions=40)
    payload = json.dumps({"status": "ok", "context": context}, ensure_ascii=False)
    assert len(payload) > TOOL_RESULT_LIMIT
    assert payload.find('"daily_change"') > TOOL_RESULT_LIMIT


def test_tool_execute_emits_daily_change_before_the_position_arrays(monkeypatch):
    context = _fake_context(n_positions=40)
    monkeypatch.setattr(
        "src.tools.portfolio_tool.PortfolioService",
        lambda: type("_S", (), {"analysis_context": staticmethod(lambda: context)})(),
    )
    result = PortfolioSummaryTool().execute()
    idx_daily = result.find('"daily_change"')
    idx_holdings_native = result.find('"holdings_native"')
    assert 0 < idx_daily < idx_holdings_native
    assert idx_daily < TOOL_RESULT_LIMIT

    parsed = json.loads(result)
    assert parsed["status"] == "ok"
    assert parsed["context"]["daily_change"]["pct"] == 0.4


def test_tool_execute_still_returns_empty_status_with_no_snapshot(monkeypatch):
    monkeypatch.setattr(
        "src.tools.portfolio_tool.PortfolioService",
        lambda: type("_S", (), {"analysis_context": staticmethod(lambda: None)})(),
    )
    result = json.loads(PortfolioSummaryTool().execute())
    assert result["status"] == "empty"
