"""Maintainer regression cases for cn_a 5m volume-share matching.

The synthetic harness lives with the partial-fill contract tests; this module
keeps the sell-fee and zero-cap review regressions at the same public seams.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd

from src.tools.paper_trade.schema import (
    CANCELED_REASON_CODE,
    load_contract_schema,
    validate_payload,
)
from src.tools.paper_trade.tool import run_paper_trade_step
from tests.test_paper_trade_5m_partial_fills import (
    _DAY,
    _FEE_MODEL,
    _HIGH_MINIMUM_FEE_MODEL,
    _SYM,
    _VOLUME_CAP_REASON,
    _FakeCalendarClient,
    _FakeChClient,
    _FakeLoader,
    _assert_single_volume_cap_cancel,
    _buy,
    _cancels,
    _fills,
    _intraday,
    _observed,
    _outcome,
    _partial_market_day,
    _sell,
    _sell_bars,
)


def test_volume_share_market_sell_rejects_fee_overdraft_before_mutation() -> None:
    """The maintainer case rejects all 300 shares, not the 100-share cap fill."""
    outcome = _outcome(
        orders=[_sell(qty=300)],
        five={_SYM: _partial_market_day()},
        cash=0.0,
        positions=({"symbol": _SYM, "qty": 300, "avg_cost": 10.0},),
        ratio=0.1,
        fee_model=_HIGH_MINIMUM_FEE_MODEL,
    )

    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert (
        outcome.fills == ()
    ), f"the unaffordable fill must not book: {_observed(outcome)}"
    rejections = outcome.rejected_orders
    assert [(r.symbol, r.side, r.qty, r.reason_code) for r in rejections] == [
        (_SYM, "sell", 300.0, "insufficient_cash")
    ], _observed(outcome)
    assert rejections[0].detail.startswith("sell "), rejections[0].detail
    assert "buy cost" not in rejections[0].detail
    assert "-1000.00" in rejections[0].detail
    assert _cancels(outcome) == [("sell", 300.0, CANCELED_REASON_CODE)], (
        "a rejected market order gets only the existing rejection cancel, never "
        f"a volume-cap cancel: {_observed(outcome)}"
    )
    assert [cancel.detail for cancel in outcome.canceled_orders] == [
        "rejected: insufficient_cash"
    ]
    assert outcome.events == (), _observed(outcome)
    assert outcome.end_state.cash == 0.0, _observed(outcome)
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [
        (_SYM, 300.0, 10.0)
    ], _observed(outcome)
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (
        state.status,
        state.request.qty,
        state.filled_qty,
        state.avg_fill_price,
        state.rejected_reason,
        state.cancel_reason,
    ) == ("rejected", Decimal("300"), Decimal("0"), None, "insufficient_cash", None)
    assert state.fills == []


def test_volume_share_sell_allows_zero_then_rejects_residual_atomically() -> None:
    """Cash 1_000 funds exactly one net-zero fill; bar two rejects residual 200."""
    outcome = _outcome(
        orders=[_sell(limit=10.00, qty=300)],
        five={_SYM: _intraday(_DAY, _sell_bars(3))},
        cash=1000.0,
        positions=({"symbol": _SYM, "qty": 300, "avg_cost": 10.0},),
        ratio=1.0,
        fee_model=_HIGH_MINIMUM_FEE_MODEL,
    )

    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert _fills(outcome) == [("sell", 100.0, 10.00, 2000.0)], (
        "projected cash exactly zero must allow the first actual 100-share fill; "
        f"later bars must not fill: {_observed(outcome)}"
    )
    rejections = outcome.rejected_orders
    assert [(r.symbol, r.side, r.qty, r.reason_code) for r in rejections] == [
        (_SYM, "sell", 200.0, "insufficient_cash")
    ], _observed(outcome)
    assert rejections[0].detail.startswith("sell "), rejections[0].detail
    assert "buy cost" not in rejections[0].detail
    assert "-1000.00" in rejections[0].detail
    assert _cancels(outcome) == [("sell", 200.0, CANCELED_REASON_CODE)], _observed(
        outcome
    )
    assert [cancel.detail for cancel in outcome.canceled_orders] == [
        "rejected: insufficient_cash"
    ]
    assert outcome.events == (), _observed(outcome)
    assert outcome.end_state.cash == 0.0, _observed(outcome)
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [
        (_SYM, 200.0, 10.0)
    ], _observed(outcome)
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (
        state.status,
        state.request.qty,
        state.filled_qty,
        state.avg_fill_price,
        state.rejected_reason,
        state.cancel_reason,
    ) == (
        "rejected",
        Decimal("300"),
        Decimal("100"),
        Decimal("10"),
        "insufficient_cash",
        None,
    )
    assert [(fill.qty, fill.price) for fill in state.fills] == [
        (Decimal("100"), Decimal("10"))
    ]


def test_all_or_none_high_minimum_sell_keeps_legacy_overdraft_behavior() -> None:
    """The new insufficient_cash gate is explicitly volume-share-only."""
    outcome = _outcome(
        orders=[_sell(qty=100)],
        five={_SYM: _partial_market_day()},
        cash=0.0,
        positions=({"symbol": _SYM, "qty": 300, "avg_cost": 10.0},),
        fill_model="all_or_none",
        fee_model=_HIGH_MINIMUM_FEE_MODEL,
    )

    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert _fills(outcome) == [("sell", 100.0, 10.00, 2000.0)], _observed(outcome)
    assert outcome.rejected_orders == (), _observed(outcome)
    assert outcome.canceled_orders == (), _observed(outcome)
    assert outcome.events == (), _observed(outcome)
    assert outcome.end_state.cash == -1000.0, _observed(outcome)
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [
        (_SYM, 200.0, 10.0)
    ], _observed(outcome)
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (
        state.status,
        state.filled_qty,
        state.avg_fill_price,
        state.rejected_reason,
    ) == (
        "held",
        Decimal("100"),
        Decimal("10"),
        None,
    )


# ── zero-cap orders: price bands first, no financial gate for zero quantity ──


def _zero_cap_limit_up_day() -> pd.DataFrame:
    """A 100-share session whose first live reference is the 11.00 upper band."""
    return _intraday(
        _DAY,
        (
            (11.00, 11.00, 11.00, 11.00, 50.0),
            (10.20, 10.20, 10.20, 10.20, 50.0),
        ),
    )


def test_zero_cap_market_buy_preserves_limit_up_cancellation() -> None:
    # Given: buy 100 at ratio 0.25 of a 100-share session, hence cap zero.
    # Cash zero would reject a positive fill, but the first live price is limit-up.
    outcome = _outcome(
        orders=[_buy(qty=100)],
        five={_SYM: _zero_cap_limit_up_day()},
        cash=0.0,
        ratio=0.25,
    )

    # When/Then: the live-bar band gate wins over both the volume and cash outcomes.
    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert outcome.fills == outcome.rejected_orders == (), _observed(outcome)
    assert [
        (event.symbol, event.event_type, event.detail) for event in outcome.events
    ] == [
        (_SYM, "price_limit", "price 11.00 at or above up limit 11.00; buy blocked")
    ], _observed(
        outcome
    )
    assert len(outcome.canceled_orders) == 1, _observed(outcome)
    cancel = outcome.canceled_orders[0]
    assert (cancel.symbol, cancel.side, cancel.qty, cancel.reason_code) == (
        _SYM,
        "buy",
        100.0,
        CANCELED_REASON_CODE,
    )
    assert cancel.detail == (
        "market order canceled: limit_up; price 11.00 at or above up limit 11.00; buy blocked"
    )
    assert _VOLUME_CAP_REASON not in cancel.detail
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (state.status, state.filled_qty, state.avg_fill_price, state.fills) == (
        "canceled",
        Decimal("0"),
        None,
        [],
    )
    assert outcome.end_state.cash == 0.0
    assert outcome.end_state.positions == ()


def test_zero_cap_market_buy_cancels_on_first_live_bar_without_cash_gate() -> None:
    # Given: a limit-up zero-volume bar cannot match; the first live bar is unblocked.
    bars = _intraday(
        _DAY,
        (
            (11.00, 11.00, 11.00, 11.00, 0.0),
            (10.00, 10.00, 10.00, 10.00, 100.0),
        ),
    )

    # When: a zero-cap market buy with cash zero reaches the first positive-volume bar.
    outcome = _outcome(orders=[_buy(qty=100)], five={_SYM: bars}, cash=0.0, ratio=0.25)

    # Then: no commission/cash rejection or price-band event precedes the volume cancel.
    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert outcome.fills == outcome.rejected_orders == outcome.events == (), _observed(
        outcome
    )
    _assert_single_volume_cap_cancel(
        outcome, side="buy", qty=100.0, case="zero-cap buy"
    )
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (state.status, state.filled_qty, state.avg_fill_price, state.fills) == (
        "canceled",
        Decimal("0"),
        None,
        [],
    )
    assert outcome.end_state.cash == 0.0
    assert outcome.end_state.positions == ()


def test_zero_cap_market_sell_bypasses_minimum_commission_cash_gate() -> None:
    # Given: a zero-cap sell has 100 held shares, cash zero and a 2_000 minimum fee.
    outcome = _outcome(
        orders=[_sell(qty=100)],
        five={_SYM: _intraday(_DAY, ((10.00, 10.00, 10.00, 10.00, 100.0),))},
        cash=0.0,
        positions=({"symbol": _SYM, "qty": 100, "avg_cost": 10.0},),
        ratio=0.25,
        fee_model=_HIGH_MINIMUM_FEE_MODEL,
    )

    # When/Then: zero quantity bypasses sell cash accounting without mutating the ledger.
    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert outcome.fills == outcome.rejected_orders == outcome.events == (), _observed(
        outcome
    )
    _assert_single_volume_cap_cancel(
        outcome, side="sell", qty=100.0, case="zero-cap sell"
    )
    assert outcome.end_state.cash == 0.0
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [
        (_SYM, 100.0, 10.0)
    ]
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (state.status, state.filled_qty, state.avg_fill_price, state.fills) == (
        "canceled",
        Decimal("0"),
        None,
        [],
    )


def test_zero_cap_limit_waits_for_a_thicker_bar() -> None:
    # Given: ratio 0.25 caps the 100-volume bar to zero and the 400-volume bar to 100.
    bars = _intraday(
        _DAY,
        (
            (10.10, 10.20, 9.90, 10.10, 100.0),
            (10.10, 10.20, 9.90, 10.10, 400.0),
        ),
    )

    # When: a limit buy remains resting through the thin bar.
    outcome = _outcome(
        orders=[_buy(limit=10.00, qty=100)], five={_SYM: bars}, ratio=0.25
    )

    # Then: only the thicker bar fills; there is no zero-qty fill or duplicate cancel.
    assert _fills(outcome) == [("buy", 100.0, 10.00, 5.00)], _observed(outcome)
    assert (
        outcome.rejected_orders == outcome.canceled_orders == outcome.events == ()
    ), _observed(outcome)
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (state.status, state.filled_qty, state.avg_fill_price) == (
        "held",
        Decimal("100"),
        Decimal("10"),
    )


def test_zero_cap_limit_expires_once_when_no_bar_is_thick_enough() -> None:
    # Given/When: every crossing bar has a zero whole-lot cap for this limit buy.
    outcome = _outcome(
        orders=[_buy(limit=10.00, qty=100)],
        five={_SYM: _intraday(_DAY, ((10.10, 10.20, 9.90, 10.10, 100.0),))},
        ratio=0.25,
    )

    # Then: it never fills and only the established day-end cancel terminates it.
    assert outcome.fills == outcome.rejected_orders == outcome.events == (), _observed(
        outcome
    )
    assert _cancels(outcome) == [("buy", 100.0, CANCELED_REASON_CODE)], _observed(
        outcome
    )
    assert [cancel.detail for cancel in outcome.canceled_orders] == [
        "unfilled day order canceled at session end"
    ]
    assert len(outcome.order_states) == 1
    state = outcome.order_states[0]
    assert (state.status, state.filled_qty, state.avg_fill_price, state.fills) == (
        "canceled",
        Decimal("0"),
        None,
        [],
    )


def test_zero_cap_limit_up_v13_document_replays_and_validates() -> None:
    # Given: the maintainer scenario driven through the public raw-JSON tool seam.
    payload = {
        "account_id": "pa_5m_zero_cap_limit_up",
        "market": "cn_a",
        "account_state": {"cash": 0.0, "positions": []},
        "orders": [_buy(qty=100)],
        "from_date": _DAY,
        "to_date": _DAY,
        "fee_model": dict(_FEE_MODEL),
        "interval": "5m",
        "fill_model": "volume_share",
        "order_volume_ratio": 0.25,
    }

    # When: two independent calls replay the same request.
    def _raw() -> str:
        return run_paper_trade_step(
            payload,
            loader=_FakeLoader({_SYM: _zero_cap_limit_up_day()}),
            ch_client=_FakeChClient(),
            calendar_client=_FakeCalendarClient(frozenset({_DAY})),
            limits_client=None,
        )

    first = _raw()
    second = _raw()
    document = json.loads(first)
    replay = json.loads(second)

    # Then: bytes, schema and fingerprints are stable, with the price-band terminal contract.
    assert first == second
    assert document["schema_version"] == "pt-v1.3"
    assert (
        validate_payload(document, load_contract_schema("result", version="pt-v1.3"))
        == []
    )
    assert document["engine_fingerprint"] == replay["engine_fingerprint"]
    assert document["fills"] == document["rejected_orders"] == []
    assert [event["event_type"] for event in document["events"]] == ["price_limit"]
    assert "up limit 11.00" in document["events"][0]["detail"]
    assert len(document["canceled_orders"]) == 1
    cancel = document["canceled_orders"][0]
    assert (cancel["qty"], cancel["reason_code"]) == (100.0, CANCELED_REASON_CODE)
    assert "limit_up" in cancel["detail"]
    assert _VOLUME_CAP_REASON not in cancel["detail"]
    assert document["order_states"] == [
        {
            "order_id": "pt-0",
            "status": "canceled",
            "add_time": f"{_DAY}T09:30:00+08:00",
            "amount": 100.0,
            "filled": 0.0,
            "price": 0.0,
            "side": "buy",
        }
    ]
    assert document["end_state"] == payload["account_state"]
