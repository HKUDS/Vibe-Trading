"""T8 gate — the pure per-order volume-share policy (pt-v1.3).

Pins the arithmetic the 5m matcher (T11) consumes from
``src.tools.paper_trade.volume_policy``:

* a MARKET order is capped by its own share of the full continuous-session
  volume; a LIMIT order by its own share of the matched bar's volume;
* every cap floors to a whole board lot — a 250-share bar at 0.25 is 62.5
  shares, i.e. zero lots, never a rounded-up 100-share fill;
* the ratio defaults to the schema's ``1.0`` and is a finite non-bool number
  in ``(0, 1]`` normalized to 6 decimal places;
* two orders on one bar each receive their OWN cap (JoinQuant per-order
  semantics: no shared per-bar budget), so their combined fill may exceed the
  bar — the documented divergence;
* no float arithmetic: ``100 * 0.29`` is ``28.999999999999996`` in binary
  floating point, and a float floor would silently drop a whole share.

Offline: no network, no clock, no engine/session import.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from src.tools.paper_trade import schema, volume_policy

#: Below-one-lot: 250 * 0.25 = 62.5 shares < one cn_a lot (100).
_ONE_LOT = 100


def test_market_cap_floors_the_ratio_to_whole_lots():
    # floor(50_000 * 0.25 / 100) * 100 = floor(125) * 100 = 12_500
    assert volume_policy.market_cap(50_000, 0.25, _ONE_LOT) == 12_500


def test_a_20_000_order_fills_only_the_12_500_cap():
    cap = volume_policy.market_cap(50_000, 0.25, _ONE_LOT)
    assert volume_policy.executable_qty(20_000, cap) == 12_500


def test_a_250_share_bar_at_quarter_yields_zero():
    # 62.5 shares is zero whole lots: never round up to one lot.
    assert volume_policy.limit_bar_cap(250, 0.25, _ONE_LOT) == 0
    assert volume_policy.executable_qty(300, 0) == 0


def test_each_order_gets_its_own_cap_and_the_total_may_exceed_the_bar():
    bar_volume = 100
    # Two independent calls model two orders on the same bar: neither sees a
    # budget consumed by the other, so each fills the whole 100-share bar.
    first = volume_policy.limit_bar_cap(bar_volume, 1.0, _ONE_LOT)
    second = volume_policy.limit_bar_cap(bar_volume, 1.0, _ONE_LOT)
    fills = [
        volume_policy.executable_qty(100, first),
        volume_policy.executable_qty(100, second),
    ]
    assert fills == [100, 100]
    assert sum(fills) == 200
    assert sum(fills) > volume_policy.limit_bar_cap(bar_volume, 1.0, _ONE_LOT)


def test_default_ratio_is_the_schema_default_and_caps_at_the_volume():
    assert volume_policy.DEFAULT_ORDER_VOLUME_RATIO == schema.DEFAULT_ORDER_VOLUME_RATIO
    default = volume_policy.DEFAULT_ORDER_VOLUME_RATIO
    assert volume_policy.market_cap(50_000, default, _ONE_LOT) == 50_000
    assert volume_policy.limit_bar_cap(50_000, default, _ONE_LOT) == 50_000


@pytest.mark.parametrize("ratio", [0, -0.1, 1.1, float("nan"), True])
def test_invalid_ratio_is_rejected(ratio):
    with pytest.raises(ValueError):
        volume_policy.normalize_ratio(ratio)
    with pytest.raises(ValueError):
        volume_policy.market_cap(50_000, ratio, _ONE_LOT)


def test_normalize_ratio_returns_a_six_decimal_decimal():
    ratio = volume_policy.normalize_ratio(0.1234567)
    assert isinstance(ratio, Decimal)
    assert ratio == Decimal("0.123457")
    assert isinstance(volume_policy.normalize_ratio(0.25), Decimal)


def test_caps_use_decimal_str_not_binary_float_arithmetic():
    # 100 * 0.29 == 28.999999999999996 in binary float: a float floor yields
    # 28, Decimal("100") * Decimal("0.29") is exactly 29.
    assert volume_policy.market_cap(100, 0.29, 1) == 29
    assert volume_policy.limit_bar_cap(100, 0.29, 1) == 29


def test_lot_floor_never_rounds_up():
    assert volume_policy.lot_floor(12_599, _ONE_LOT) == 12_500
    assert volume_policy.lot_floor(12_500, _ONE_LOT) == 12_500
    assert volume_policy.lot_floor(99, _ONE_LOT) == 0


@pytest.mark.parametrize("lot", [0, -100])
def test_lot_floor_rejects_non_positive_lot(lot):
    with pytest.raises(ValueError):
        volume_policy.lot_floor(1_000, lot)


def test_executable_qty_is_min_with_a_zero_floor():
    assert volume_policy.executable_qty(20_000, 12_500) == 12_500
    assert volume_policy.executable_qty(100, 100) == 100
    assert volume_policy.executable_qty(0, 12_500) == 0
    assert volume_policy.executable_qty(-100, 12_500) == 0
    assert volume_policy.executable_qty(100, 0) == 0


def test_policy_module_has_no_engine_session_or_clock_import():
    tree = ast.parse(Path(volume_policy.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("engine", "session_5m", "datetime", "time", "random")
    assert not [name for name in imported if any(token in name for token in forbidden)]
