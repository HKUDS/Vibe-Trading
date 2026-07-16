"""Focused accounting and metric regressions for the options engine."""

from __future__ import annotations

import pytest

from backtest.engines.options_portfolio import (
    OptionPosition,
    _close_positions_fifo,
)


def _position(qty: float, entry_price: float, entry_date: str) -> OptionPosition:
    return OptionPosition(
        option_type="call",
        strike=100.0,
        expiry="2025-03-21",
        qty=qty,
        entry_price=entry_price,
        entry_date=entry_date,
        underlying_code="SPY",
    )


def _close(positions: list[OptionPosition], qty: float, *, price: float = 15.0):
    return _close_positions_fifo(
        positions,
        underlying="SPY",
        option_type="call",
        strike=100.0,
        expiry="2025-03-21",
        requested_qty=qty,
        exit_price=price,
        contract_multiplier=100.0,
        commission=0.01,
        timestamp="2025-02-03",
    )


def test_partial_long_close_uses_fifo_and_leaves_residual_lot() -> None:
    first = _position(3, 10.0, "2025-01-02")
    second = _position(2, 12.0, "2025-01-03")
    positions = [first, second]

    cash_delta, records = _close(positions, 4)

    assert cash_delta == pytest.approx(15.0 * 4 * 100 * 0.99)
    assert [record["qty"] for record in records] == [3, 1]
    assert [record["entry_date"] for record in records] == ["2025-01-02", "2025-01-03"]
    assert sum(record["pnl"] for record in records) == pytest.approx(1800.0)
    assert positions == [second]
    assert second.qty == 1


def test_partial_short_close_uses_absolute_quantity_and_positive_records() -> None:
    first = _position(-2, 10.0, "2025-01-02")
    second = _position(-2, 12.0, "2025-01-03")
    positions = [first, second]

    cash_delta, records = _close(positions, -3, price=8.0)

    assert cash_delta == pytest.approx(-8.0 * 3 * 100 * 1.01)
    assert [record["qty"] for record in records] == [2, 1]
    assert sum(record["pnl"] for record in records) == pytest.approx(800.0)
    assert positions == [second]
    assert second.qty == -1


def test_split_closes_conserve_cash_fees_and_pnl() -> None:
    split_positions = [
        _position(3, 10.0, "2025-01-02"),
        _position(2, 12.0, "2025-01-03"),
    ]
    full_positions = [
        _position(3, 10.0, "2025-01-02"),
        _position(2, 12.0, "2025-01-03"),
    ]

    first_cash, first_records = _close(split_positions, 2)
    second_cash, second_records = _close(split_positions, 3)
    full_cash, full_records = _close(full_positions, 5)

    assert split_positions == []
    assert full_positions == []
    assert first_cash + second_cash == pytest.approx(full_cash)
    assert sum(
        record["pnl"] for record in first_records + second_records
    ) == pytest.approx(sum(record["pnl"] for record in full_records))


def test_over_close_rejects_without_mutating_positions() -> None:
    position = _position(2, 10.0, "2025-01-02")
    positions = [position]

    with pytest.raises(ValueError, match="only 2 available"):
        _close(positions, 3)

    assert positions == [position]
    assert position.qty == 2


@pytest.mark.parametrize("qty", [0, float("nan"), float("inf")])
def test_close_rejects_non_positive_or_non_finite_quantity(qty: float) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        _close([_position(2, 10.0, "2025-01-02")], qty)
