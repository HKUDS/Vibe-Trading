"""Deterministic pt-v2.0 order-plan tests: IDs, lots, cash and weight gaps."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.tools.paper_trade.portfolio.ledger import (
    BucketLedger,
    LedgerPosition,
    PortfolioLedger,
)
from src.tools.paper_trade.portfolio.models import (
    Currency,
    PortfolioBucket,
    PortfolioOrder,
)
from src.tools.paper_trade.portfolio.numeric import (
    EffectiveFeeModel,
    parse_effective_fee_model,
)
from src.tools.paper_trade.portfolio.order_plan import (
    ORDER_PLAN_VERSION,
    OrderPlan,
    build_explicit_order_plan,
    build_target_weight_order_plan,
    order_plan_to_json,
)
from src.tools.paper_trade.portfolio.planner import (
    TargetWeight,
    plan_target_weights,
)
from src.tools.paper_trade.portfolio.schema import PortfolioRequestError
from tests.test_paper_trade_portfolio_planner import (
    PLANNING_AT,
    TRADE_DATE,
    _fx,
    _ledger,
    _mark,
    _marks,
    _plan,
)

AGENT_ROOT = Path(__file__).resolve().parents[1]


def _fee_models(*specs: tuple[str, str, Currency]) -> tuple[EffectiveFeeModel, ...]:
    selected = specs or (
        ("cn", "cn_a", "CNY"),
        ("hk", "hk", "HKD"),
        ("us", "us", "USD"),
    )
    return tuple(
        parse_effective_fee_model(
            PortfolioBucket(
                bucket_id=bucket_id,
                market=market,
                currency=currency,
                cash="0.00",
                positions=(),
            )
        )
        for bucket_id, market, currency in selected
    )


def _fixture_plan() -> OrderPlan:
    return build_target_weight_order_plan(_plan(), fee_models=_fee_models())


def _target_plan(
    allocation=None, *, hk_lot_sizes: dict[str, int] | None = None
) -> OrderPlan:
    return build_target_weight_order_plan(
        _plan() if allocation is None else allocation,
        fee_models=_fee_models(),
        hk_lot_sizes=hk_lot_sizes,
    )


def _order(
    order_id: str,
    bucket_id: str,
    symbol: str,
    currency: Currency,
    side: str,
    qty: int,
) -> PortfolioOrder:
    return PortfolioOrder(
        order_id=order_id,
        bucket_id=bucket_id,
        symbol=symbol,
        currency=currency,
        side=side,
        qty=qty,
    )


def _explicit(
    orders: Any,
    *,
    ledger: PortfolioLedger | None = None,
    marks=None,
    fx=None,
    fee_models: tuple[EffectiveFeeModel, ...] | None = None,
) -> OrderPlan:
    selected_ledger = _ledger() if ledger is None else ledger
    return build_explicit_order_plan(
        orders,
        ledger=selected_ledger,
        trade_date=TRADE_DATE,
        planning_at=PLANNING_AT,
        base_currency="USD",
        marks=_marks() if marks is None else marks,
        fx_snapshots=_fx() if fx is None else fx,
        fee_models=_fee_models() if fee_models is None else fee_models,
    )


def _assert_reason(exc: pytest.ExceptionInfo[PortfolioRequestError], reason: str) -> None:
    assert exc.value.code == "INVALID_REQUEST"
    assert exc.value.reason == reason


def _bucket(plan: OrderPlan, bucket_id: str):
    return next(row for row in plan.buckets if row.bucket_id == bucket_id)


def _weight(plan: OrderPlan, symbol: str):
    return next(row for row in plan.weights if row.symbol == symbol)


def test_three_currency_target_plan_has_stable_ids_sell_first_and_exact_cash() -> None:
    # Given the confirmed task-8 three-currency target-weight allocation.
    # When the order-plan layer floors quantities to market lots.
    plan = _fixture_plan()

    # Then the canonical sequence puts sells before buys and IDs are content based.
    assert plan.plan_version == ORDER_PLAN_VERSION
    assert plan.mode == "target_weights"
    assert tuple(order.plan_order_id for order in plan.orders) == (
        "pt2-20261113-hk-buy-00700.HK",
        "pt2-20261113-us-sell-AAPL.US",
        "pt2-20261113-us-buy-MSFT.US",
    )
    assert tuple((order.side, order.symbol, order.qty) for order in plan.orders) == (
        ("buy", "00700.HK", 100),
        ("sell", "AAPL.US", 7),
        ("buy", "MSFT.US", 32),
    )

    # Then each bucket keeps exact local cash and lot residue; nothing is pooled.
    cn = _bucket(plan, "cn")
    assert (cn.opening_cash, cn.planned_cash) == (
        Decimal("100000.00"),
        Decimal("100000.00"),
    )
    assert cn.lot_residual_cash == Decimal("44950.00")
    assert cn.lot_residual_cash_base == Decimal("6293.00")
    hk = _bucket(plan, "hk")
    assert hk.buy_costs == Decimal("32042.56")
    assert hk.planned_cash == Decimal("17957.44")
    assert hk.lot_residual_cash == Decimal("5120.00")
    us = _bucket(plan, "us")
    assert us.sell_proceeds == Decimal("1329.01")
    assert us.buy_costs == Decimal("13120.99")
    assert us.planned_cash == Decimal("13208.02")
    assert plan.total_planned_cash_base == Decimal("29506.57")
    assert plan.total_lot_residual_cash_base == Decimal("6948.36")

    # Then the CN target is unorderable as a whole lot and is explicitly skipped.
    assert tuple(
        (line.bucket_id, line.symbol, line.reason, line.residual_qty)
        for line in plan.skipped
    ) == (("cn", "600519.SH", "lot_floor_rounding", 31),)

    # Then planned weights are estimates at planning marks, never realized weights.
    assert plan.weight_basis == "planning_marks"
    assert plan.realized_weight_status == "pending_execution"
    hk_weight = _weight(plan, "00700.HK")
    assert hk_weight.target_weight == Decimal("0.100000000000")
    assert hk_weight.planned_weight == Decimal("0.092256407946")
    assert hk_weight.planned_gap == Decimal("-0.007743592054")
    aapl = _weight(plan, "AAPL.US")
    assert aapl.current_qty == 100
    assert aapl.planned_qty == 93
    assert aapl.planned_weight == Decimal("0.198995450246")
    assert aapl.target_gap == Decimal("-0.013973602415")
    assert aapl.planned_gap == Decimal("-0.001004549754")
    assert aapl.realized_weight is None
    assert aapl.realized_gap is None


def test_hk_board_lot_table_floors_target_quantity_and_keeps_residual_cash() -> None:
    # Given an HK board lot larger than the intended target increase.
    # When the caller supplies the board-lot table explicitly.
    plan = _target_plan(hk_lot_sizes={"00700.HK": 200})

    # Then the HK buy becomes an explicit lot-floor residual in its own bucket.
    assert "00700.HK" not in {order.symbol for order in plan.orders}
    assert (
        "hk",
        "00700.HK",
        "lot_floor_rounding",
        116,
        200,
    ) in {
        (
            line.bucket_id,
            line.symbol,
            line.reason,
            line.residual_qty,
            line.lot_size,
        )
        for line in plan.skipped
    }
    hk = _bucket(plan, "hk")
    assert hk.planned_cash == Decimal("50000.00")
    assert hk.lot_residual_cash == Decimal("37120.00")
    assert hk.lot_residual_cash_base == Decimal("4751.36")
    assert all("lot assumption" not in warning for warning in plan.warnings)


def test_rebalance_band_skips_the_line_and_reports_the_remaining_gap() -> None:
    # Given the same allocation with a two-percent rebalance band.
    # When the order plan suppresses weights already inside the band.
    plan = _target_plan(_plan(rebalance_band="0.02"))

    # Then AAPL is not sold and its post-plan weight still differs from target.
    assert "AAPL.US" not in {order.symbol for order in plan.orders}
    assert (
        "us",
        "AAPL.US",
        "within_rebalance_band",
        7,
    ) in {
        (line.bucket_id, line.symbol, line.reason, line.residual_qty)
        for line in plan.skipped
    }
    aapl = _weight(plan, "AAPL.US")
    assert aapl.planned_qty == 100
    assert aapl.planned_weight == Decimal("0.213973602415")
    assert aapl.planned_gap == Decimal("0.013973602415")
    assert _bucket(plan, "us").sell_proceeds == Decimal("0.00")
    assert _bucket(plan, "us").planned_cash == Decimal("11879.01")


def test_sells_precede_buys_within_one_bucket() -> None:
    # Given one CN bucket holding two instruments, one to reduce and one to add.
    ledger = PortfolioLedger(
        buckets=(
            BucketLedger(
                bucket_id="cn",
                market="cn_a",
                currency="CNY",
                cash=Decimal("500000.00"),
                positions=(
                    LedgerPosition(
                        symbol="600519.SH",
                        qty=200,
                        avg_cost=Decimal("1400.00"),
                        market="cn_a",
                        currency="CNY",
                    ),
                    LedgerPosition(
                        symbol="000001.SZ",
                        qty=1000,
                        avg_cost=Decimal("11.00"),
                        market="cn_a",
                        currency="CNY",
                    ),
                ),
            ),
        )
    )
    allocation = plan_target_weights(
        ledger,
        trade_date=TRADE_DATE,
        planning_at=PLANNING_AT,
        base_currency="USD",
        marks=(
            _mark("600519.SH", "1450.00"),
            _mark("000001.SZ", "12.00"),
        ),
        fx_snapshots=(
            # Reuse the planner fixture's CNY-to-USD snapshot without importing FX types.
            _fx()[0],
        ),
        target_weights=(
            TargetWeight(
                bucket_id="cn",
                symbol="600519.SH",
                currency="CNY",
                weight="0.10",
            ),
            TargetWeight(
                bucket_id="cn",
                symbol="000001.SZ",
                currency="CNY",
                weight="0.40",
            ),
        ),
        rebalance_band="0",
    )

    # When the plan is built for that single bucket.
    plan = build_target_weight_order_plan(
        allocation,
        fee_models=_fee_models(("cn", "cn_a", "CNY")),
    )

    # Then the sell is emitted first even though the symbol sorts after the buy.
    assert tuple((order.side, order.symbol, order.qty) for order in plan.orders) == (
        ("sell", "600519.SH", 100),
        ("buy", "000001.SZ", 25700),
    )
    assert tuple(order.plan_order_id for order in plan.orders) == (
        "pt2-20261113-cn-sell-600519.SH",
        "pt2-20261113-cn-buy-000001.SZ",
    )
    assert _bucket(plan, "cn").sell_proceeds == Decimal("144889.80")
    assert _bucket(plan, "cn").buy_costs == Decimal("308480.18")
    assert _bucket(plan, "cn").planned_cash == Decimal("336409.62")
    assert _bucket(plan, "cn").lot_residual_cash == Decimal("396.00")
    assert _bucket(plan, "cn").lot_residual_position_value == Decimal("65250.00")


def test_explicit_orders_keep_caller_ids_and_normalize_sell_first() -> None:
    # Given caller orders submitted in a deliberately non-canonical sequence.
    orders = (
        _order("us-buy-msft", "us", "MSFT.US", "USD", "buy", 10),
        _order("us-sell-aapl", "us", "AAPL.US", "USD", "sell", 20),
        _order("hk-buy", "hk", "00700.HK", "HKD", "buy", 100),
        _order("cn-sell", "cn", "600519.SH", "CNY", "sell", 100),
    )

    # When explicit orders are normalized by canonical bucket and sell-first order.
    plan = _explicit(orders)

    # Then caller IDs survive but submission order never decides priority.
    assert plan.mode == "explicit_orders"
    assert tuple(order.plan_order_id for order in plan.orders) == (
        "cn-sell",
        "hk-buy",
        "us-sell-aapl",
        "us-buy-msft",
    )
    assert tuple((order.side, order.symbol) for order in plan.orders) == (
        ("sell", "600519.SH"),
        ("buy", "00700.HK"),
        ("sell", "AAPL.US"),
        ("buy", "MSFT.US"),
    )
    assert _bucket(plan, "cn").planned_cash == Decimal("244889.80")
    assert _bucket(plan, "hk").planned_cash == Decimal("17957.44")
    assert _bucket(plan, "us").sell_proceeds == Decimal("3799.01")
    assert _bucket(plan, "us").buy_costs == Decimal("4100.99")
    assert _bucket(plan, "us").planned_cash == Decimal("24698.02")
    assert plan.total_planned_cash_base == Decimal("61281.14")
    assert _weight(plan, "MSFT.US").target_weight is None
    assert _weight(plan, "MSFT.US").planned_weight == Decimal("0.046173251047")
    assert _weight(plan, "MSFT.US").target_gap is None


def test_target_plan_is_identical_across_hash_seeds_and_processes() -> None:
    # Given one fixture plan serialized twice in fresh interpreters.
    script = (
        "import json\n"
        "from tests.test_paper_trade_portfolio_order_plan import _fixture_plan, order_plan_to_json\n"
        'print(json.dumps(order_plan_to_json(_fixture_plan()), sort_keys=True, separators=(",", ":")))\n'
    )
    outputs: list[str] = []
    for seed in ("0", "104729"):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=AGENT_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout.strip())

    # Then hash randomization cannot change IDs, residuals or weight-gap rows.
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0]) == order_plan_to_json(_fixture_plan())
    assert '"plan_order_id":"pt2-20261113-us-sell-AAPL.US"' in outputs[0]


def test_duplicate_target_instrument_is_rejected_before_planning() -> None:
    # Given an allocation that names the same instrument twice.
    allocation = _plan()
    duplicated = replace(
        allocation,
        lines=allocation.lines + (allocation.lines[0],),
    )

    # When / Then the plan fails closed before producing any order.
    with pytest.raises(PortfolioRequestError) as caught:
        _target_plan(duplicated)

    _assert_reason(caught, "duplicate_plan_instrument")
    assert caught.value.bucket_id == "cn"


def test_duplicate_explicit_order_id_is_rejected() -> None:
    # Given two different orders sharing one caller ID.
    orders = (
        _order("dup", "us", "AAPL.US", "USD", "sell", 10),
        _order("dup", "us", "MSFT.US", "USD", "buy", 10),
    )

    # When / Then ID uniqueness is part of the input contract.
    with pytest.raises(PortfolioRequestError) as caught:
        _explicit(orders)

    _assert_reason(caught, "duplicate_order_id")


def test_duplicate_explicit_instrument_is_rejected() -> None:
    # Given two orders for the same bucket/instrument pair.
    orders = (
        _order("sell-1", "us", "AAPL.US", "USD", "sell", 10),
        _order("sell-2", "us", "AAPL.US", "USD", "sell", 5),
    )

    # When / Then the plan keeps one deterministic order per instrument.
    with pytest.raises(PortfolioRequestError) as caught:
        _explicit(orders)

    _assert_reason(caught, "duplicate_order_instrument")


def test_cross_bucket_explicit_instrument_is_rejected() -> None:
    # Given AAPL, which the ledger owns in the US bucket, ordered through HK.
    orders = (_order("wrong-bucket", "hk", "AAPL.US", "HKD", "buy", 100),)

    # When / Then instrument ownership cannot move between buckets.
    with pytest.raises(PortfolioRequestError) as caught:
        _explicit(orders)

    _assert_reason(caught, "instrument_bucket_mismatch")
    assert caught.value.bucket_id == "hk"


def test_invalid_lot_quantity_is_rejected() -> None:
    # Given a CN order of 50 shares against a 100-share board lot.
    orders = (_order("bad-lot", "cn", "600519.SH", "CNY", "buy", 50),)

    # When / Then explicit quantities are validated, never silently rounded.
    with pytest.raises(PortfolioRequestError) as caught:
        _explicit(orders)

    _assert_reason(caught, "invalid_lot_quantity")
    assert caught.value.bucket_id == "cn"


def test_nonpositive_sell_proceeds_are_rejected() -> None:
    # Given a one-cent US holding whose minimum commission exceeds the notional.
    ledger = PortfolioLedger(
        buckets=(
            BucketLedger(
                bucket_id="us",
                market="us",
                currency="USD",
                cash=Decimal("1000.00"),
                positions=(
                    LedgerPosition(
                        symbol="PENNY.US",
                        qty=1,
                        avg_cost=Decimal("0.01"),
                        market="us",
                        currency="USD",
                    ),
                ),
            ),
        )
    )
    orders = (_order("penny-sell", "us", "PENNY.US", "USD", "sell", 1),)

    # When / Then a sale that would consume cash is never planned.
    with pytest.raises(PortfolioRequestError) as caught:
        _explicit(
            orders,
            ledger=ledger,
            marks=(_mark("PENNY.US", "0.01"),),
            fx=(),
            fee_models=_fee_models(("us", "us", "USD")),
        )

    _assert_reason(caught, "nonpositive_sale_proceeds")
    assert caught.value.bucket_id == "us"


def test_cash_infeasible_plan_is_rejected_before_matching() -> None:
    # Given a US buy that costs far more than the bucket's cash.
    orders = (_order("too-big", "us", "AAPL.US", "USD", "buy", 1000),)

    # When / Then the planning cash gate rejects the whole plan.
    with pytest.raises(PortfolioRequestError) as caught:
        _explicit(orders)

    _assert_reason(caught, "insufficient_planning_cash")
    assert caught.value.bucket_id == "us"


def test_malformed_order_missing_and_stale_marks_are_typed_errors() -> None:
    # Given a non-typed order row.
    with pytest.raises(PortfolioRequestError) as malformed:
        _explicit(({},))

    _assert_reason(malformed, "invalid_portfolio_order")

    # Given an ordered instrument without its planning mark.
    with pytest.raises(PortfolioRequestError) as missing:
        _explicit(
            (_order("no-mark", "us", "MSFT.US", "USD", "buy", 10),),
            marks=tuple(mark for mark in _marks() if mark.symbol != "MSFT.US"),
        )

    _assert_reason(missing, "missing_planning_mark")
    assert missing.value.path == "planning_marks.MSFT.US"

    # Given a mark dated on trade_date rather than strictly before it.
    stale_marks = tuple(
        replace(mark, price_date=TRADE_DATE) if mark.symbol == "AAPL.US" else mark
        for mark in _marks()
    )
    with pytest.raises(PortfolioRequestError) as stale:
        _explicit(
            (_order("stale", "us", "AAPL.US", "USD", "sell", 10),),
            marks=stale_marks,
        )

    _assert_reason(stale, "stale_planning_mark")


def test_plan_json_is_float_free_and_realized_weights_stay_pending() -> None:
    # Given a successful target-weight plan.
    payload = order_plan_to_json(_fixture_plan())

    # Then the JSON-safe projection contains no float and no claimed realization.
    def walk(value: Any) -> None:
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    encoded = json.dumps(payload, sort_keys=True)
    assert '"realized_weight": null' in encoded
    assert '"realized_gap": null' in encoded
    assert payload["weight_basis"] == "planning_marks"
    assert payload["realized_weight_status"] == "pending_execution"
    assert payload["trade_date"] == date(2026, 11, 13).isoformat()
    assert isinstance(payload["orders"], list)
    assert isinstance(payload["weights"], list)


def test_split_facade_reexports_moved_private_symbols() -> None:
    # Given the order-plan implementation split into focused sibling modules.
    from src.tools.paper_trade.portfolio import (
        order_plan_builders,
        order_plan_explicit,
        order_plan_json,
        order_plan_models,
        order_plan_primitives,
        order_plan_target,
    )

    # When moved private symbols are imported through the historic facade path.
    from src.tools.paper_trade.portfolio.order_plan import (
        _BucketSpec,
        _exact_product,
        _make_order,
        _money_text,
        _reject,
        _validate_marks,
        build_target_weight_order_plan,
    )

    # Then every binding is the owning module's object, so patch seams survive.
    assert _reject is order_plan_primitives._reject
    assert _exact_product is order_plan_primitives._exact_product
    assert _BucketSpec is order_plan_models._BucketSpec
    assert _make_order is order_plan_target._make_order
    assert _validate_marks is order_plan_explicit._validate_marks
    assert _money_text is order_plan_json._money_text
    assert build_target_weight_order_plan is order_plan_builders.build_target_weight_order_plan
