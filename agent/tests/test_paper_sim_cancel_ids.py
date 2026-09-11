"""A locally simulated paper cancel may only acknowledge orders the simulator issued.

Zerodha, Dhan, Shoonya and Upbit expose no sandbox, so their paper profiles
simulate orders locally — but their reads (``get_open_orders``,
``get_positions``) hit the real account. A real open order's id can therefore
reach the paper ``cancel_order``, which used to answer ``cancelled: True`` for
any id while never calling the broker: the agent was told a live order was
gone while it kept working. Both directions are pinned per connector, and the
accepted id is taken from ``place_order`` so the issuing and the checking side
cannot drift apart.
"""

from __future__ import annotations

import pytest

from src.trading.connectors.dhan import sdk as dhan_sdk
from src.trading.connectors.shoonya import sdk as shoonya_sdk
from src.trading.connectors.upbit import sdk as upbit_sdk
from src.trading.connectors.zerodha import sdk as zerodha_sdk

_CONNECTORS = [
    pytest.param(zerodha_sdk, zerodha_sdk.ZerodhaConfig, {"symbol": "RELIANCE"}, id="zerodha"),
    pytest.param(dhan_sdk, dhan_sdk.DhanConfig, {"symbol": "RELIANCE"}, id="dhan"),
    pytest.param(shoonya_sdk, shoonya_sdk.ShoonyaConfig, {"symbol": "RELIANCE"}, id="shoonya"),
    # quantity-based sizing needs no live quote, so Upbit's place_order takes
    # the same no-network path as the other three here; a notional-sized
    # order would call get_quote and needs a mocked one instead.
    pytest.param(upbit_sdk, upbit_sdk.UpbitConfig, {"symbol": "KRW-BTC"}, id="upbit"),
]


@pytest.mark.parametrize("mod, Config, order_kwargs", _CONNECTORS)
def test_the_id_place_order_issued_can_be_cancelled(mod, Config, order_kwargs) -> None:
    placed = mod.place_order(Config(profile="paper"), side="buy", quantity=1, **order_kwargs)
    assert placed["status"] == "ok"

    cancelled = mod.cancel_order(Config(profile="paper"), placed["order_id"])

    assert cancelled["status"] == "ok"
    assert cancelled["cancelled"] is True
    assert cancelled["order_id"] == placed["order_id"]


@pytest.mark.parametrize("mod, Config, order_kwargs", _CONNECTORS)
@pytest.mark.parametrize("foreign_id", ["250911000123456", "ORD1", "paper-RELIANCE-B-1", " 1234 "])
def test_an_id_the_simulator_never_issued_is_refused(mod, Config, order_kwargs, foreign_id) -> None:
    result = mod.cancel_order(Config(profile="paper"), foreign_id)

    assert result["status"] == "error"
    assert "cancelled" not in result
    assert "not issued by this paper simulator" in result["error"]
