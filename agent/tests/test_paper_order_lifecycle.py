"""Phase-1 tests for the bar-agnostic order lifecycle (#1938).

The state machine is deliberately unwired: these tests pin the contract —
stable replay ids, the JoinQuant status set, cancel semantics, day-order
settlement, partial fills under a volume cap — without any engine, calendar
or market data.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.tools.paper_trade.order_lifecycle import (
    STATUS_CANCELED,
    STATUS_FILLED,
    STATUS_HELD,
    STATUS_NEW,
    STATUS_OPEN,
    STATUS_PENDING_CANCEL,
    STATUS_REJECTED,
    OrderBook,
    OrderLifecycleError,
    OrderRequest,
    assign_ids,
    replay_snapshot,
)

D = Decimal


def _request(**overrides):
    kwargs = dict(symbol="600519.SH", side="buy", qty=D("100"))
    kwargs.update(overrides)
    return OrderRequest(**kwargs)


class TestRequestValidation:
    def test_side_must_be_buy_or_sell(self):
        with pytest.raises(OrderLifecycleError, match="side"):
            _request(side="hold")

    def test_qty_must_be_positive(self):
        with pytest.raises(OrderLifecycleError, match="positive"):
            _request(qty=D("0"))

    def test_limit_order_requires_a_price(self):
        with pytest.raises(OrderLifecycleError, match="limit_price"):
            _request(order_type="limit")

    def test_market_order_must_not_carry_a_price(self):
        with pytest.raises(OrderLifecycleError, match="market"):
            _request(limit_price=D("10"))


class TestStableReplayIds:
    def test_replayed_batches_reproduce_identical_ids(self):
        first = assign_ids([_request(), _request(side="sell")])
        second = assign_ids([_request(), _request(side="sell")])
        assert sorted(first) == sorted(second) == ["pt-0", "pt-1"]

    def test_explicit_ids_are_honoured_and_must_be_unique(self):
        states = assign_ids([_request(order_id="ord-7")])
        assert list(states) == ["ord-7"]
        with pytest.raises(OrderLifecycleError, match="duplicate"):
            assign_ids([_request(order_id="dup"), _request(order_id="dup")])


class TestLifecycleFlow:
    def test_new_order_activates_then_fills_fully(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        fill = book.fill("pt-0", D("100"), D("1700.00"))
        assert fill.qty == D("100")
        state = book.get("pt-0")
        assert state.status == STATUS_FILLED
        assert state.filled_qty == D("100")
        assert state.avg_fill_price == D("1700.00")

    def test_partial_fill_marks_held(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        book.fill("pt-0", D("40"), D("1700.00"))
        assert book.get("pt-0").status == STATUS_HELD

    def test_avg_price_weighted_across_fills(self):
        book = OrderBook(assign_ids([_request(qty=D("200"))]))
        book.activate("pt-0")
        book.fill("pt-0", D("100"), D("10.00"))
        book.fill("pt-0", D("50"), D("13.00"))
        # (100*10 + 50*13) / 150 = 11
        assert book.get("pt-0").avg_fill_price == D("11")

    def test_overfill_is_clipped_to_the_remaining_quantity(self):
        book = OrderBook(assign_ids([_request(qty=D("100"))]))
        book.activate("pt-0")
        book.fill("pt-0", D("60"), D("10"))
        fill = book.fill("pt-0", D("1000"), D("10"))
        assert fill.qty == D("40")
        assert book.get("pt-0").status == STATUS_FILLED

    def test_rejected_reason_is_recorded(self):
        book = OrderBook(assign_ids([_request()]))
        book.reject("pt-0", "insufficient_position")
        state = book.get("pt-0")
        assert state.status == STATUS_REJECTED
        assert state.rejected_reason == "insufficient_position"


class TestCancel:
    def test_cancel_by_id_moves_open_order_to_pending_cancel(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        book.request_cancel("pt-0")
        assert book.get("pt-0").status == STATUS_PENDING_CANCEL

    def test_cancel_is_idempotent_while_pending(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        book.request_cancel("pt-0")
        book.request_cancel("pt-0")
        assert book.get("pt-0").status == STATUS_PENDING_CANCEL

    def test_terminal_order_cannot_be_canceled(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        book.fill("pt-0", D("100"), D("1700"))
        with pytest.raises(OrderLifecycleError, match="cannot be canceled"):
            book.request_cancel("pt-0")

    def test_pending_cancel_order_stops_matching(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        book.request_cancel("pt-0")
        with pytest.raises(OrderLifecycleError, match="no longer matches"):
            book.fill("pt-0", D("10"), D("1700"))

    def test_unknown_id_fails_closed(self):
        book = OrderBook()
        with pytest.raises(OrderLifecycleError, match="unknown order id"):
            book.request_cancel("nope")


class TestDayOrderSettlement:
    def test_every_unfinished_order_is_canceled_at_session_end(self):
        book = OrderBook(assign_ids([_request(), _request(side="sell"), _request(symbol="000001.SZ")]))
        book.activate("pt-0")
        book.activate("pt-1")
        book.fill("pt-0", D("40"), D("1700"))
        settled = book.settle_day()
        assert sorted(s.order_id for s in settled) == ["pt-0", "pt-1", "pt-2"]
        assert all(s.status == STATUS_CANCELED for s in settled)
        # partially filled order keeps its fills after cancellation
        assert book.get("pt-0").filled_qty == D("40")

    def test_terminal_orders_are_left_alone(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        book.fill("pt-0", D("100"), D("1700"))
        assert book.settle_day() == []
        assert book.get("pt-0").status == STATUS_FILLED


class TestVolumeCap:
    def test_fill_is_capped_at_the_volume_cap(self):
        book = OrderBook(assign_ids([_request(qty=D("1000"))]))
        book.activate("pt-0")
        fill = book.fill("pt-0", D("1000"), D("10"), volume_cap=D("250"))
        assert fill.qty == D("250")
        assert book.get("pt-0").status == STATUS_HELD

    def test_non_positive_cap_fails_closed(self):
        book = OrderBook(assign_ids([_request()]))
        book.activate("pt-0")
        with pytest.raises(OrderLifecycleError, match="volume_cap"):
            book.fill("pt-0", D("10"), D("10"), volume_cap=D("0"))

    def test_cap_larger_than_request_fills_the_request(self):
        book = OrderBook(assign_ids([_request(qty=D("100"))]))
        book.activate("pt-0")
        fill = book.fill("pt-0", D("100"), D("10"), volume_cap=D("10000"))
        assert fill.qty == D("100")


class TestDeterminism:
    def test_identical_event_sequences_produce_identical_snapshots(self):
        def run() -> dict:
            book = OrderBook(assign_ids([_request(), _request(qty=D("500"), symbol="00700.HK")]))
            book.activate("pt-0")
            book.activate("pt-1")
            book.fill("pt-0", D("30"), D("1700.00"))
            book.fill("pt-1", D("250"), D("310.40"), volume_cap=D("250"))
            book.request_cancel("pt-0")
            book.settle_day()
            return replay_snapshot(book)

        assert run() == run()

    def test_snapshot_is_sorted_and_json_ready(self):
        book = OrderBook(assign_ids([_request(), _request(side="sell")]))
        book.activate("pt-1")
        snapshot = replay_snapshot(book)
        assert list(snapshot) == ["pt-0", "pt-1"]
        assert snapshot["pt-0"]["status"] == STATUS_NEW
        assert snapshot["pt-1"]["status"] == STATUS_OPEN
        assert all(isinstance(v["filled_qty"], str) for v in snapshot.values())


class TestOpenOrders:
    def test_open_orders_lists_only_active_ones(self):
        book = OrderBook(assign_ids([_request(), _request(side="sell"), _request(symbol="000001.SZ")]))
        book.activate("pt-0")
        book.activate("pt-1")
        book.fill("pt-1", D("100"), D("1700"))
        assert [s.order_id for s in book.open_orders()] == ["pt-0", "pt-2"]


class TestSubmit:
    def test_submit_rejects_a_reused_id_even_after_terminal(self):
        book = OrderBook()
        book.submit(_request(order_id="ord-1"))
        book.fill("ord-1", D("100"), D("1700"))
        with pytest.raises(OrderLifecycleError, match="duplicate"):
            book.submit(_request(order_id="ord-1", side="sell"))

    def test_modify_is_cancel_then_new_id(self):
        book = OrderBook()
        first = book.submit(_request(order_id="ord-1"))
        book.request_cancel("ord-1")
        book.settle_day()
        second = book.submit(_request(order_id="ord-2", qty=D("200")))
        assert first.status == STATUS_CANCELED
        assert second.status == STATUS_NEW
