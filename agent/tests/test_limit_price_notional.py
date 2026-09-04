"""Buy-limit notional must be sized at the worse of quote and limit (#18).

A buy limit at 2x the market used to be priced at the quote alone, so it
passed a cap sized for the quote while being fillable at twice the
authorized amount. Sell limits do not create exposure, so the quote stands
there.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.live.sdk_order_gate as sdk_order_gate
from src.live.enforcement import OrderIntent
from src.live.mandate.model import AssetClass, InstrumentType


def _connector(last: float):
    return SimpleNamespace(get_quote=lambda symbol, config=None: {"quote": {"last": last}})


def _intent(limit_price: float | None, side: str = "buy") -> OrderIntent:
    return OrderIntent(
        symbol="AAPL",
        side=side,
        notional_usd=None,
        quantity=10.0,
        instrument_type=InstrumentType.EQUITY,
        asset_class=AssetClass.US_EQUITY,
        limit_price=limit_price,
    )


def test_buy_limit_above_quote_is_priced_at_the_limit() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=200.0), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(2000.0)


def test_buy_limit_below_quote_keeps_the_quote() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=80.0), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(1000.0)


def test_market_order_ignores_the_limit_path() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=None), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(1000.0)


def test_sell_limit_keeps_the_quote() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=200.0, side="sell"), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(1000.0)
