"""Cancellation across missing bars and the existing terminal-state policies."""

from __future__ import annotations

from tests.test_paper_trade_cancellation import _cancel, _payload, _run
from tests.test_paper_trade_5m_partial_fills import _DAY, _SYM, _intraday


def test_cancel_is_processed_even_without_a_bar_at_its_timestamp():
    bars = _intraday(_DAY, ((10.2, 10.3, 9.8, 10.2, 1000.0),) * 3)
    bars = bars.drop(bars.index[1])
    document, _ = _run(_payload(cancel_schedule=[_cancel()]), five=bars)
    assert [row["qty"] for row in document["fills"]] == [100]
    assert document["cancel_results"][0]["reason"] == "cancel_requested"
    assert document["canceled_orders"][0]["qty"] == 200


def test_cancel_is_processed_on_a_zero_volume_bar():
    bars = _intraday(
        _DAY,
        (
            (10.2, 10.3, 9.8, 10.2, 1000.0),
            (10.2, 10.3, 9.8, 10.2, 0.0),
            (10.2, 10.3, 9.8, 10.2, 1000.0),
        ),
    )
    document, _ = _run(_payload(cancel_schedule=[_cancel()]), five=bars)
    assert [row["qty"] for row in document["fills"]] == [100]
    assert document["cancel_results"][0]["at"] == _cancel()["at"]


def test_caller_does_not_relabel_an_existing_price_limit_cancel():
    payload = _payload(cancel_schedule=[_cancel()])
    del payload["orders"][0]["limit"]
    bars = _intraday(
        _DAY,
        (
            (11.0, 11.0, 11.0, 11.0, 1000.0),
            (10.2, 10.3, 9.8, 10.2, 1000.0),
            (10.2, 10.3, 9.8, 10.2, 1000.0),
        ),
    )
    document, _ = _run(payload, five=bars)
    assert document["fills"] == []
    assert document["cancel_results"][0]["reason"] == "already_pending_cancel"
    assert len(document["canceled_orders"]) == 1
    assert (
        document["canceled_orders"][0]["reason_code"] == "canceled_after_failed_match"
    )
    assert "limit_up" in document["canceled_orders"][0]["detail"]


def test_volume_cap_cancel_is_terminal_and_keeps_its_original_reason():
    payload = _payload(cancel_schedule=[_cancel()])
    del payload["orders"][0]["limit"]
    bars = _intraday(
        _DAY,
        (
            (10.2, 10.3, 9.8, 10.2, 400.0),
            (10.2, 10.3, 9.8, 10.2, 400.0),
            (10.2, 10.3, 9.8, 10.2, 200.0),
        ),
    )
    document, _ = _run(payload, five=bars)
    assert [row["qty"] for row in document["fills"]] == [100]
    assert document["cancel_results"][0]["reason"] == "terminal_canceled"
    assert document["cancel_results"][0]["remaining"] == 200
    assert len(document["canceled_orders"]) == 1
    assert document["canceled_orders"][0]["reason_code"] == "canceled_after_volume_cap"


def test_rejected_order_refuses_cancel_without_mutating_the_ledger():
    document, _ = _run(
        _payload(
            account_state={"cash": 0.0, "positions": []},
            cancel_schedule=[_cancel()],
        )
    )
    assert document["fills"] == []
    assert document["cancel_results"][0]["reason"] == "terminal_rejected"
    assert document["rejected_orders"][0]["order_id"] == "alpha"
    assert document["rejected_orders"][0]["reason_code"] == "insufficient_cash"
    assert document["end_state"] == {"cash": 0.0, "positions": []}


def test_partial_sell_keeps_its_executed_quantity_and_single_fee():
    payload = _payload(
        account_state={
            "cash": 1000.0,
            "positions": [{"symbol": _SYM, "qty": 300, "avg_cost": 10.0}],
        },
        cancel_schedule=[_cancel()],
    )
    payload["orders"][0]["side"] = "sell"
    bars = _intraday(_DAY, ((9.8, 10.3, 9.7, 9.8, 1000.0),) * 3)
    document, _ = _run(payload, five=bars)
    assert [(row["qty"], row["price"], row["fee"]) for row in document["fills"]] == [
        (100, 10.0, 5.5)
    ]
    assert document["end_state"]["cash"] == 1994.5
    assert document["end_state"]["positions"][0]["qty"] == 200
    assert document["canceled_orders"][0]["qty"] == 200


def test_same_time_receipts_follow_schedule_order_not_order_submission_order():
    payload = _payload(
        cancel_schedule=[_cancel("09:35", "beta"), _cancel("09:35", "alpha")]
    )
    payload["orders"].append({**payload["orders"][0], "order_id": "beta"})
    document, _ = _run(payload)
    assert document["fills"] == []
    assert [row["order_id"] for row in document["cancel_results"]] == ["beta", "alpha"]
    assert [row["order_id"] for row in document["order_states"]] == ["alpha", "beta"]


def test_strategy_orders_keep_their_existing_positional_reason_argument():
    from src.tools.paper_trade.strategy_exec import StrategyOrder

    order = StrategyOrder(_SYM, "buy", 100.0, 10.0, "legacy strategy reason")
    assert order.reason == "legacy strategy reason"
    assert order.order_id is None
