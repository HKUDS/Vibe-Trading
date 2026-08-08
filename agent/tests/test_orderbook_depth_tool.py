"""Tests for orderbook_depth_tool: validation, spread/imbalance/impact math, edge cases.

No test ever reaches a live exchange. The tool isolates the network call in
its own module-level function, ``_fetch_raw_book`` — see the tool's module
docstring — and every test here monkeypatches exactly that name on the
``orderbook_depth_tool`` module, mirroring the pattern already used in
``tests/test_prediction_market_tool.py`` (monkeypatch ``throttled_get_json``
on its own tool module rather than mocking ``requests`` globally).

Fixture books use small integer prices/quantities specifically so the impact
walk's expected outputs can be hand-computed with exact arithmetic (verified
independently with ``decimal.Decimal`` outside the test, then hardcoded as
literals below) and asserted to 1e-9 rather than merely "looks plausible".
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.tools import orderbook_depth_tool
from src.tools.orderbook_depth_tool import OrderBookDepthTool


def _raw_book(
    bids: list[list[float]],
    asks: list[list[float]],
    *,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """Build a ccxt-shaped OrderBook dict, as ``fetch_order_book`` returns it."""
    return {
        "symbol": "BTC/USDT",
        "bids": bids,
        "asks": asks,
        "timestamp": timestamp,
        "datetime": None,
        "nonce": None,
    }


def _install(monkeypatch: pytest.MonkeyPatch, book: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Monkeypatch ``_fetch_raw_book`` to return ``book`` and record call args."""
    calls: list[tuple[str, str, int]] = []

    def fake_fetch(exchange_id: str, ccxt_symbol: str, limit: int) -> dict[str, Any]:
        calls.append((exchange_id, ccxt_symbol, limit))
        return book

    monkeypatch.setattr(orderbook_depth_tool, "_fetch_raw_book", fake_fetch)
    return calls


def _run(**kwargs: Any) -> dict[str, Any]:
    return json.loads(OrderBookDepthTool().execute(**kwargs))


# ---------------------------------------------------------------------------
# The four-level book used for the impact-cost hand-calc tests.
#
# asks (ascending): 100@1, 101@1, 102@1, 103@1  -> total ask depth = 4 base
# bids (descending): 99@1, 98@1, 97@1, 96@1     -> total bid depth = 4 base
# mid = (100 + 99) / 2 = 99.5
#
# Every expected number below was computed independently with
# decimal.Decimal (not by calling the tool) and is asserted to 1e-9:
#
#   Case A (notional=199 -> base_qty_target=199/99.5=2.0 exactly, a clean
#           2-level fill on both sides):
#     BUY:  take 1@100 + 1@101 = 201 quote for 2.0 base -> avg=100.5
#           slippage_bps = (100.5-99.5)/99.5*10000 = 100.502512562814070...
#     SELL: take 1@99 + 1@98 = 197 quote for 2.0 base -> avg=98.5
#           slippage_bps = (99.5-98.5)/99.5*10000 = 100.502512562814070...
#
#   Case B (base_qty_target=2.5 -> notional=248.75, a partial 3rd-level fill):
#     BUY:  1@100 + 1@101 + 0.5@102 = 100+101+51 = 252 quote for 2.5 base
#           avg=100.8, slippage_bps=(100.8-99.5)/99.5*10000=130.653266331658...
#
#   Case C (base_qty_target=10, exceeds the entire 4-base ask ladder):
#     BUY:  all 4 asks = 100+101+102+103=406 quote for 4.0 base, avg=101.5
#           fully_filled=False, unfilled_base_qty=6.0
#           slippage_bps=(101.5-99.5)/99.5*10000=201.005025125628140...
# ---------------------------------------------------------------------------
_ASKS = [[100, 1], [101, 1], [102, 1], [103, 1]]
_BIDS = [[99, 1], [98, 1], [97, 1], [96, 1]]


def test_impact_cost_exact_two_level_fill_buy_and_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case A: notional lands exactly on a level boundary on both sides."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", notional_quote=199, levels=4)

    assert result["ok"] is True
    impact = result["data"]["impact_cost"]
    assert impact["base_qty_target"] == pytest.approx(2.0, abs=1e-9)

    buy = impact["buy"]
    assert buy["fully_filled"] is True
    assert buy["filled_base_qty"] == pytest.approx(2.0, abs=1e-9)
    assert buy["filled_notional_quote"] == pytest.approx(201.0, abs=1e-9)
    assert buy["avg_price"] == pytest.approx(100.5, abs=1e-9)
    assert buy["slippage_bps"] == pytest.approx(100.502512562814070, abs=1e-9)
    assert buy["levels_used"] == 2
    assert "note" not in buy

    sell = impact["sell"]
    assert sell["fully_filled"] is True
    assert sell["filled_base_qty"] == pytest.approx(2.0, abs=1e-9)
    assert sell["filled_notional_quote"] == pytest.approx(197.0, abs=1e-9)
    assert sell["avg_price"] == pytest.approx(98.5, abs=1e-9)
    assert sell["slippage_bps"] == pytest.approx(100.502512562814070, abs=1e-9)
    assert sell["levels_used"] == 2
    assert "note" not in sell


def test_impact_cost_partial_level_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case B: the target lands mid-level, exercising fractional level consumption."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", notional_quote=248.75, levels=4)

    buy = result["data"]["impact_cost"]["buy"]
    assert buy["fully_filled"] is True
    assert buy["filled_base_qty"] == pytest.approx(2.5, abs=1e-9)
    assert buy["filled_notional_quote"] == pytest.approx(252.0, abs=1e-9)
    assert buy["avg_price"] == pytest.approx(100.8, abs=1e-9)
    assert buy["slippage_bps"] == pytest.approx(130.653266331658291, abs=1e-9)
    assert buy["levels_used"] == 3


def test_impact_cost_exceeds_full_book_depth_reports_partial_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case C: requested notional cannot be filled by the whole fetched ladder.

    This is the "does not fabricate a full fill" requirement: filled_notional
    must reflect only what the book actually had, fully_filled must be False,
    and a note must explain why.
    """
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    # base_qty_target = notional/mid = 995/99.5 = 10.0, but total ask depth is 4.
    result = _run(symbol="BTC-USDT", notional_quote=995, levels=4)

    impact = result["data"]["impact_cost"]
    assert impact["base_qty_target"] == pytest.approx(10.0, abs=1e-9)

    buy = impact["buy"]
    assert buy["fully_filled"] is False
    assert buy["filled_base_qty"] == pytest.approx(4.0, abs=1e-9)
    assert buy["filled_notional_quote"] == pytest.approx(406.0, abs=1e-9)
    assert buy["avg_price"] == pytest.approx(101.5, abs=1e-9)
    assert buy["unfilled_base_qty"] == pytest.approx(6.0, abs=1e-9)
    assert buy["slippage_bps"] == pytest.approx(201.005025125628140, abs=1e-9)
    assert buy["levels_used"] == 4
    assert "note" in buy
    assert "995" in buy["note"]

    # filled_notional_quote (406) must never be conflated with the requested
    # notional_quote_requested (995) — a caller reading only one field must
    # still be able to tell the order was not fully filled.
    assert buy["notional_quote_requested"] == pytest.approx(995.0, abs=1e-9)
    assert buy["filled_notional_quote"] < buy["notional_quote_requested"]


def test_spread_and_mid_price(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT")

    data = result["data"]
    assert data["mid_price"] == pytest.approx(99.5, abs=1e-9)
    assert data["best_bid"] == {"price": 99, "amount_base": 1}
    assert data["best_ask"] == {"price": 100, "amount_base": 1}
    assert data["spread"]["absolute_quote"] == pytest.approx(1.0, abs=1e-9)
    # 1 / 99.5 * 10000
    assert data["spread"]["relative_bps"] == pytest.approx(100.502512562814070, abs=1e-9)


# ---------------------------------------------------------------------------
# Depth imbalance: double-sided guard (balanced -> ~0, thick one side -> big
# and correctly signed), plus a mutation-style check that swapping which side
# is thick flips the sign.
# ---------------------------------------------------------------------------


def test_imbalance_balanced_book_is_near_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """99*101 == 101*99, so bid and ask notional are exactly equal -> imbalance == 0."""
    _install(monkeypatch, _raw_book([[99, 101]], [[101, 99]]))
    result = _run(symbol="BTC-USDT", levels=1)

    imbalance = result["data"]["imbalance"]
    assert imbalance["bid_notional_quote"] == pytest.approx(9999.0, abs=1e-9)
    assert imbalance["ask_notional_quote"] == pytest.approx(9999.0, abs=1e-9)
    assert imbalance["normalized_imbalance"] == pytest.approx(0.0, abs=1e-9)
    assert imbalance["ratio_bid_over_ask"] == pytest.approx(1.0, abs=1e-9)


def test_imbalance_bid_heavy_book_is_large_and_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        _raw_book([[99, 1000], [98, 1000]], [[101, 1], [102, 1]]),
    )
    result = _run(symbol="BTC-USDT", levels=2)

    imbalance = result["data"]["imbalance"]
    # bid_notional = 99*1000+98*1000 = 197000; ask_notional = 101+102 = 203
    assert imbalance["bid_notional_quote"] == pytest.approx(197_000.0, abs=1e-9)
    assert imbalance["ask_notional_quote"] == pytest.approx(203.0, abs=1e-9)
    assert imbalance["normalized_imbalance"] > 0.99
    assert imbalance["normalized_imbalance"] <= 1.0


def test_imbalance_ask_heavy_book_is_large_and_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation of the bid-heavy case: swap which side is thick and the sign must flip."""
    _install(
        monkeypatch,
        _raw_book([[99, 1], [98, 1]], [[101, 1000], [102, 1000]]),
    )
    result = _run(symbol="BTC-USDT", levels=2)

    imbalance = result["data"]["imbalance"]
    assert imbalance["normalized_imbalance"] < -0.99
    assert imbalance["normalized_imbalance"] >= -1.0


# ---------------------------------------------------------------------------
# Timestamp handling: exchange-supplied vs. local-fallback.
# ---------------------------------------------------------------------------


def test_timestamp_from_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book(_BIDS, _ASKS, timestamp=1_700_000_000_000))
    result = _run(symbol="BTC-USDT")

    data = result["data"]
    assert data["timestamp"] == "2023-11-14T22:13:20Z"
    assert data["timestamp_source"] == "exchange"


def test_timestamp_falls_back_to_local_fetch_time_when_venue_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binance spot depth carries no server timestamp field (see tool docstring)."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS, timestamp=None))
    result = _run(symbol="BTC-USDT")

    data = result["data"]
    assert data["timestamp_source"] == "local_fetch_time"
    assert data["timestamp"].endswith("Z")


def test_exchange_and_symbol_are_always_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="btc-usdt", exchange="binance")

    data = result["data"]
    assert data["exchange"] == "binance"
    assert data["symbol"] == "BTC-USDT"
    assert data["ccxt_symbol"] == "BTC/USDT"


# ---------------------------------------------------------------------------
# Boundary / error handling — every case must be an explicit `ok: false`
# error, never a plausible-looking number.
# ---------------------------------------------------------------------------


def test_empty_book_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book([], []))
    result = _run(symbol="BTC-USDT")

    assert result["ok"] is False
    assert "empty" in result["error"].lower()


def test_one_sided_book_no_bids_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book([], _ASKS))
    result = _run(symbol="BTC-USDT")

    assert result["ok"] is False
    assert "no bids" in result["error"].lower()


def test_one_sided_book_no_asks_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book(_BIDS, []))
    result = _run(symbol="BTC-USDT")

    assert result["ok"] is False
    assert "no asks" in result["error"].lower()


def test_crossed_book_is_rejected_not_computed_as_negative_spread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """best_bid (101) >= best_ask (100): a data error, must refuse outright."""
    _install(monkeypatch, _raw_book([[101, 1]], [[100, 1]]))
    result = _run(symbol="BTC-USDT")

    assert result["ok"] is False
    assert "crossed" in result["error"].lower()


def test_crossed_book_equal_prices_is_also_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """best_bid == best_ask is degenerate (zero/negative spread), not a valid quote."""
    _install(monkeypatch, _raw_book([[100, 1]], [[100, 1]]))
    result = _run(symbol="BTC-USDT")

    assert result["ok"] is False
    assert "crossed" in result["error"].lower()


def test_notional_exceeding_full_depth_on_both_sides_reports_partial_both_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symmetric to the buy-side depth-exceeded case, but exercised on sell too."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", notional_quote=995)  # base_qty_target = 10 on both sides

    sell = result["data"]["impact_cost"]["sell"]
    assert sell["fully_filled"] is False
    assert sell["filled_base_qty"] == pytest.approx(4.0, abs=1e-9)
    assert sell["unfilled_base_qty"] == pytest.approx(6.0, abs=1e-9)
    assert "note" in sell


@pytest.mark.parametrize("levels", [51, 1000, -1, 0])
def test_levels_out_of_bounds_is_rejected(monkeypatch: pytest.MonkeyPatch, levels: int) -> None:
    """N over the cap (or below 1) must be an explicit error, never a silent clamp."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", levels=levels)

    assert result["ok"] is False
    assert "levels" in result["error"].lower()


def test_levels_at_the_cap_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """50 is the documented maximum and must not be rejected."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", levels=50)

    assert result["ok"] is True
    assert result["data"]["depth"]["levels"] == 50
    # Only 4 levels actually exist on each side; the response must not
    # fabricate padding rows to reach the requested count.
    assert len(result["data"]["depth"]["bids"]) == 4
    assert len(result["data"]["depth"]["asks"]) == 4


@pytest.mark.parametrize("notional", [0, -100, "not-a-number", None])
def test_invalid_notional_is_rejected(monkeypatch: pytest.MonkeyPatch, notional: Any) -> None:
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", notional_quote=notional)

    assert result["ok"] is False
    assert "notional" in result["error"].lower()


def test_invalid_exchange_is_rejected_even_bypassing_the_schema_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The JSON-schema enum constrains a well-behaved LLM caller; execute()
    must not trust that and re-validates at runtime."""
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT", exchange="kraken")

    assert result["ok"] is False
    assert "exchange" in result["error"].lower()


@pytest.mark.parametrize("symbol", ["BTCUSDT", "BTC-", "-USDT", "BTC-USDT-PERP", "", None, 123])
def test_malformed_symbol_is_rejected(monkeypatch: pytest.MonkeyPatch, symbol: Any) -> None:
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol=symbol)

    assert result["ok"] is False
    assert "symbol" in result["error"].lower()


def test_fetch_failure_is_surfaced_as_error_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    def raising_fetch(exchange_id: str, ccxt_symbol: str, limit: int) -> dict[str, Any]:
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(orderbook_depth_tool, "_fetch_raw_book", raising_fetch)
    result = _run(symbol="BTC-USDT")

    assert result["ok"] is False
    assert "simulated network failure" in result["error"]


def test_network_is_never_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against a future edit silently reintroducing a real network path."""
    calls = _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    _run(symbol="BTC-USDT", exchange="okx", levels=5, notional_quote=1234)

    assert calls == [("okx", "BTC/USDT", orderbook_depth_tool._BOOK_FETCH_LIMIT)]


def test_units_block_distinguishes_base_and_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raw_book(_BIDS, _ASKS))
    result = _run(symbol="BTC-USDT")

    units = result["units"]
    assert "amount_base" in units
    assert "notional_quote / *_notional_quote / filled_notional_quote" in units


def test_tool_metadata_is_readonly_and_repeatable() -> None:
    tool = OrderBookDepthTool()
    assert tool.name == "orderbook_depth"
    assert tool.is_readonly is True
    assert tool.repeatable is True
