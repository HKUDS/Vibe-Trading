from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from backtest.perpetual_risk import (
    AccountState,
    CrossMarginRiskModel,
    ExecutionFrame,
    MaintenanceBracket,
    MaintenanceSchedule,
    MarketRiskFrame,
    PositionRisk,
    PositionState,
    RiskSnapshot,
    evaluate_isolated,
    maintenance_margin,
)


def _brackets(coefficient: float | None = None) -> tuple[MaintenanceBracket, ...]:
    return (
        MaintenanceBracket(1, 50_000.0, 0.004, 0.0, coefficient),
        MaintenanceBracket(2, 250_000.0, 0.005, 50.0, coefficient),
    )


def _schedule(symbol: str = "BTC-USDT-PERP", version: str = "abc123", coefficient: float | None = None) -> MaintenanceSchedule:
    return MaintenanceSchedule(symbol, version, _brackets(coefficient))


def _risk_frame(
    symbol: str = "BTC-USDT-PERP",
    *,
    timestamp: pd.Timestamp = pd.Timestamp("2026-07-26T00:00:00Z"),
    mark_open: float = 60_000.0,
    mark_high: float = 60_500.0,
    mark_low: float = 59_500.0,
    mark_close: float = 60_000.0,
    schedule: MaintenanceSchedule | None = None,
    fidelity_flags: tuple[str, ...] = (),
) -> MarketRiskFrame:
    return MarketRiskFrame(
        timestamp=timestamp,
        mark_open=mark_open,
        mark_high=mark_high,
        mark_low=mark_low,
        mark_close=mark_close,
        funding_rate=None,
        funding_settlement_time=None,
        schedule=_schedule(symbol) if schedule is None else schedule,
        source="ccxt:binanceusdm",
        fidelity_flags=fidelity_flags,
    )


def test_schedule_holds_the_given_version_without_recomputing_it() -> None:
    schedule = _schedule(version="deadbeefcafef00d")
    assert schedule.version == "deadbeefcafef00d"


@pytest.mark.parametrize(
    "values",
    [
        (1, 0.0, 0.004, 0.0),  # notional_cap must be positive
        (1, 50_000.0, -0.001, 0.0),  # maintenance_rate must be non-negative
        (1, 50_000.0, 0.004, -1.0),  # cumulative_maintenance_amount must be non-negative
        (-1, 50_000.0, 0.004, 0.0),  # bracket_tier must be non-negative
    ],
)
def test_invalid_bracket_values_are_rejected(values: tuple[int, float, float, float]) -> None:
    with pytest.raises(ValueError):
        MaintenanceBracket(*values)


def test_bracket_accepts_optional_notional_coefficient() -> None:
    bracket = MaintenanceBracket(1, 50_000.0, 0.004, 0.0, notional_coefficient=1.5)
    assert bracket.notional_coefficient == 1.5


def test_schedule_requires_strictly_increasing_notional_caps() -> None:
    with pytest.raises(ValueError, match="notional caps"):
        MaintenanceSchedule(
            "BTC-USDT-PERP",
            "v1",
            (
                MaintenanceBracket(1, 250_000.0, 0.005, 50.0),
                MaintenanceBracket(2, 50_000.0, 0.004, 0.0),
            ),
        )


def test_schedule_requires_strictly_increasing_bracket_tiers() -> None:
    with pytest.raises(ValueError, match="bracket_tier"):
        MaintenanceSchedule(
            "BTC-USDT-PERP",
            "v1",
            (
                MaintenanceBracket(2, 50_000.0, 0.004, 0.0),
                MaintenanceBracket(1, 250_000.0, 0.005, 50.0),
            ),
        )


def test_schedule_rejects_empty_symbol_version_or_brackets() -> None:
    with pytest.raises(ValueError, match="symbol"):
        MaintenanceSchedule("", "v1", _brackets())
    with pytest.raises(ValueError, match="version"):
        MaintenanceSchedule("BTC-USDT-PERP", "", _brackets())
    with pytest.raises(ValueError, match="brackets"):
        MaintenanceSchedule("BTC-USDT-PERP", "v1", ())


def test_schedule_from_loader_columns_parses_validated_json() -> None:
    records = [
        {
            "bracket_tier": 1, "notional_cap": 50_000.0,
            "maintenance_rate": 0.004, "cumulative_maintenance_amount": 0.0,
        },
        {
            "bracket_tier": 2, "notional_cap": 250_000.0,
            "maintenance_rate": 0.005, "cumulative_maintenance_amount": 50.0,
            "notional_coefficient": 1.2,
        },
    ]
    schedule = MaintenanceSchedule.from_loader_columns(
        "BTC/USDT:USDT", json.dumps(records), "abc123"
    )
    assert schedule.symbol == "BTC/USDT:USDT"
    assert schedule.version == "abc123"
    assert schedule.brackets[1].notional_coefficient == 1.2


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not-json", "not valid JSON"),
        ("{}", "non-empty list"),
        ("[]", "non-empty list"),
    ],
)
def test_schedule_from_loader_columns_rejects_bad_payloads(payload: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        MaintenanceSchedule.from_loader_columns("BTC/USDT:USDT", payload, "abc123")


def test_position_uses_signed_quantity_and_never_stores_mark_price() -> None:
    position = PositionState(
        symbol="BTC-USDT-PERP",
        quantity=-0.5,
        entry_price=60_000.0,
        leverage=10.0,
        accumulated_entry_fee=15.0,
        isolated_margin=None,
    )

    assert position.quantity == -0.5
    assert not hasattr(position, "mark_price")
    with pytest.raises(FrozenInstanceError):
        position.quantity = 1.0  # type: ignore[misc]


@pytest.mark.parametrize("quantity", [0.0, float("nan"), float("inf")])
def test_position_rejects_invalid_quantity(quantity: float) -> None:
    with pytest.raises(ValueError, match="quantity"):
        PositionState("BTC-USDT-PERP", quantity, 60_000.0, 10.0, 0.0, None)


def test_account_validates_margin_mode_terminal_status_and_unique_symbols() -> None:
    position = PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 3.0, 600.0)
    account = AccountState(10_000.0, (position,), "isolated", "active")
    assert account.positions == (position,)

    with pytest.raises(ValueError, match="margin_mode"):
        AccountState(10_000.0, (), "portfolio", "active")
    with pytest.raises(ValueError, match="terminal_status"):
        AccountState(10_000.0, (), "cross", "position_liquidation")
    with pytest.raises(ValueError, match="duplicate"):
        AccountState(10_000.0, (position, position), "isolated", "active")


def test_execution_and_market_frames_have_distinct_price_contracts() -> None:
    timestamp = pd.Timestamp("2026-01-01T08:00:00Z")
    execution = ExecutionFrame(timestamp, execution_open=60_010.0)
    risk = MarketRiskFrame(
        timestamp=timestamp,
        mark_open=60_000.0,
        mark_high=61_000.0,
        mark_low=59_000.0,
        mark_close=60_500.0,
        funding_rate=0.0001,
        funding_settlement_time=timestamp,
        schedule=_schedule(),
        source="ccxt:binanceusdm",
        fidelity_flags=(),
    )

    assert execution.execution_open == 60_010.0
    assert not hasattr(execution, "mark_open")
    assert risk.mark_low == 59_000.0
    assert not hasattr(risk, "execution_open")


def test_market_risk_frame_allows_no_bracket_schedule() -> None:
    """A -PERP fetch without a bracket artifact still yields a usable frame
    for execution/mark/funding-only consumers — schedule is optional."""
    timestamp = pd.Timestamp("2026-01-01T00:00:00Z")
    frame = MarketRiskFrame(
        timestamp=timestamp,
        mark_open=60_000.0,
        mark_high=61_000.0,
        mark_low=59_000.0,
        mark_close=60_500.0,
        funding_rate=None,
        funding_settlement_time=None,
        schedule=None,
        source="ccxt:binanceusdm",
    )
    assert frame.schedule is None


def test_frames_reject_invalid_prices_and_unpaired_funding_fields() -> None:
    timestamp = pd.Timestamp("2026-01-01T01:00:00Z")
    with pytest.raises(ValueError, match="execution_open"):
        ExecutionFrame(timestamp, execution_open=0.0)
    with pytest.raises(ValueError, match="funding"):
        MarketRiskFrame(
            timestamp=timestamp,
            mark_open=60_000.0,
            mark_high=61_000.0,
            mark_low=59_000.0,
            mark_close=60_500.0,
            funding_rate=0.0001,
            funding_settlement_time=None,
            schedule=_schedule(),
            source="ccxt:binanceusdm",
            fidelity_flags=(),
        )


@pytest.mark.parametrize("coefficient", [None, 1.5])
def test_maintenance_margin_uses_boundaries_without_reapplying_coefficient(
    coefficient: float | None,
) -> None:
    position = PositionState("BTC-USDT-PERP", 1.0, 40_000.0, 10.0, 0.0, 4_000.0)
    schedule = _schedule(coefficient=coefficient)
    assert maintenance_margin(position, 50_000.0, schedule) == pytest.approx(200.0)
    assert maintenance_margin(position, 50_001.0, schedule) == pytest.approx(
        50_001.0 * 0.005 - 50.0
    )


@pytest.mark.parametrize(
    ("mark_price", "match"),
    [(0.0, "positive and finite"), (-1.0, "positive and finite"), (float("nan"), "positive and finite")],
)
def test_maintenance_margin_rejects_invalid_mark_price(mark_price: float, match: str) -> None:
    position = PositionState("BTC-USDT-PERP", 1.0, 40_000.0, 10.0, 0.0, 4_000.0)
    with pytest.raises(ValueError, match=match):
        maintenance_margin(position, mark_price, _schedule())


def test_maintenance_margin_rejects_symbol_mismatch_and_notional_above_final_cap() -> None:
    position = PositionState("ETH-USDT-PERP", 1.0, 40_000.0, 10.0, 0.0, 4_000.0)
    with pytest.raises(ValueError, match="symbol"):
        maintenance_margin(position, 50_000.0, _schedule())

    position = PositionState("BTC-USDT-PERP", 6.0, 40_000.0, 10.0, 0.0, 4_000.0)
    with pytest.raises(ValueError, match="notional"):
        maintenance_margin(position, 50_000.0, _schedule())


def test_risk_outputs_are_frozen() -> None:
    risk = PositionRisk("BTC-USDT-PERP", 50_000.0, 50_000.0, 10_000.0, 5_000.0, 200.0, 4_000.0)
    snapshot = RiskSnapshot(4_000.0, 5_000.0, 200.0, -1_200.0, (risk,), "healthy", (), ())
    with pytest.raises(FrozenInstanceError):
        risk.mark_price = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.status = "account_liquidation"  # type: ignore[misc]


def test_isolated_liquidates_only_the_breached_position() -> None:
    account = AccountState(
        1_000.0,
        (
            PositionState("BTC-USDT-PERP", 1.0, 60_000.0, 10.0, 0.0, 600.0),
            PositionState("ETH-USDT-PERP", -1.0, 3_000.0, 10.0, 0.0, 500.0),
        ),
        "isolated",
    )
    frames = {
        "BTC-USDT-PERP": _risk_frame(fidelity_flags=("btc_mark",)),
        "ETH-USDT-PERP": _risk_frame(
            "ETH-USDT-PERP",
            mark_open=3_000.0,
            mark_high=3_010.0,
            mark_low=2_990.0,
            mark_close=3_000.0,
            fidelity_flags=("eth_mark",),
        ),
    }

    snapshot = evaluate_isolated(account, frames, "adverse")

    assert snapshot.status == "position_liquidation"
    assert snapshot.liquidation_targets == ("BTC-USDT-PERP",)
    assert snapshot.per_position[0].mark_price == 59_500.0
    assert snapshot.per_position[1].mark_price == 3_010.0
    assert [risk.initial_margin for risk in snapshot.per_position] == pytest.approx([5_950.0, 301.0])
    assert snapshot.margin_balance == pytest.approx(490.0)
    assert snapshot.initial_margin == pytest.approx(6_251.0)
    assert snapshot.maintenance_margin == pytest.approx(259.54)
    assert snapshot.available_balance == pytest.approx(-5_761.0)
    assert snapshot.fidelity_flags == (
        "btc_mark",
        "eth_mark",
        "conservative_intrabar_assumption",
    )


@pytest.mark.parametrize(
    ("account", "frames", "status", "targets"),
    [
        (
            AccountState(1_000.0, (PositionState("BTC-USDT-PERP", 1.0, 60_000.0, 10.0, 0.0, 747.5),), "isolated"),
            {"BTC-USDT-PERP": _risk_frame()},
            "position_liquidation",
            ("BTC-USDT-PERP",),
        ),
        (
            AccountState(759.5, (
                PositionState("BTC-USDT-PERP", 1.0, 60_000.0, 10.0, 0.0, None),
                PositionState("ETH-USDT-PERP", 1.0, 3_000.0, 10.0, 0.0, None),
            ), "cross"),
            {
                "BTC-USDT-PERP": _risk_frame(),
                "ETH-USDT-PERP": _risk_frame("ETH-USDT-PERP", mark_open=3_000.0,
                                               mark_high=3_000.0, mark_low=3_000.0, mark_close=3_000.0),
            },
            "account_liquidation",
            ("BTC-USDT-PERP", "ETH-USDT-PERP"),
        ),
    ],
)
def test_risk_models_liquidate_at_exact_maintenance_threshold(account: AccountState,
                                                               frames: dict[str, MarketRiskFrame], status: str,
                                                               targets: tuple[str, ...]) -> None:
    evaluate = evaluate_isolated if account.margin_mode == "isolated" else CrossMarginRiskModel().evaluate
    snapshot = evaluate(account, frames)
    if account.margin_mode == "isolated":
        risk = snapshot.per_position[0]
        assert risk.margin_balance == pytest.approx(risk.maintenance_margin)
    else:
        assert snapshot.margin_balance == pytest.approx(snapshot.maintenance_margin)
    assert snapshot.status == status
    assert snapshot.liquidation_targets == targets


@pytest.mark.parametrize("price_field", ["mark_open", "mark_high", "mark_low", "mark_close"])
def test_isolated_accepts_explicit_mark_price_fields(price_field: str) -> None:
    account = AccountState(1_000.0, (PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, 1_000.0),), "isolated")
    snapshot = evaluate_isolated(account, {"BTC-USDT-PERP": _risk_frame()}, price_field)
    assert snapshot.status == "healthy"
    assert snapshot.per_position[0].mark_price == getattr(_risk_frame(), price_field)


@pytest.mark.parametrize("margin_mode", ["isolated", "cross"])
def test_empty_accounts_are_healthy(margin_mode: str) -> None:
    account = AccountState(1_000.0, (), margin_mode)
    evaluate = evaluate_isolated if margin_mode == "isolated" else CrossMarginRiskModel().evaluate
    snapshot = evaluate(account, {})
    assert snapshot.status == "healthy"
    assert snapshot.liquidation_targets == ()
    assert snapshot.per_position == ()
    assert snapshot.margin_balance == pytest.approx(1_000.0)


@pytest.mark.parametrize(
    ("evaluate", "account", "match"),
    [
        (
            evaluate_isolated,
            AccountState(1_000.0, (PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, 1_000.0),), "cross"),
            "margin_mode",
        ),
        (
            evaluate_isolated,
            AccountState(1_000.0, (PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, None),), "isolated"),
            "isolated_margin",
        ),
        (
            CrossMarginRiskModel().evaluate,
            AccountState(1_000.0, (PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, None),), "isolated"),
            "margin_mode",
        ),
        (
            CrossMarginRiskModel().evaluate,
            AccountState(1_000.0, (PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, 1_000.0),), "cross"),
            "isolated_margin",
        ),
    ],
)
def test_risk_models_reject_wrong_modes_and_margin_assignments(
    evaluate: object, account: AccountState, match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        evaluate(account, {"BTC-USDT-PERP": _risk_frame()})  # type: ignore[operator]


def test_isolated_rejects_missing_or_invalid_market_risk_frames() -> None:
    position = PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, 1_000.0)
    account = AccountState(1_000.0, (position,), "isolated")
    missing_schedule = MarketRiskFrame(
        timestamp=pd.Timestamp("2026-07-26T00:00:00Z"),
        mark_open=60_000.0,
        mark_high=60_500.0,
        mark_low=59_500.0,
        mark_close=60_000.0,
        funding_rate=None,
        funding_settlement_time=None,
        schedule=None,
        source="ccxt:binanceusdm",
    )

    with pytest.raises(ValueError, match="frame"):
        evaluate_isolated(account, {})
    with pytest.raises(ValueError, match="schedule"):
        evaluate_isolated(account, {position.symbol: missing_schedule})
    with pytest.raises(ValueError, match="symbols"):
        evaluate_isolated(
            account,
            {position.symbol: _risk_frame(schedule=_schedule("ETH-USDT-PERP"))},
        )
    with pytest.raises(ValueError, match="price_field"):
        evaluate_isolated(account, {position.symbol: _risk_frame()}, "last")


def test_cross_offsets_profitable_and_losing_position_pnl() -> None:
    account = AccountState(
        1_000.0,
        (
            PositionState("BTC-USDT-PERP", 1.0, 60_000.0, 10.0, 0.0, None),
            PositionState("ETH-USDT-PERP", 10.0, 2_900.0, 10.0, 0.0, None),
        ),
        "cross",
    )
    frames = {
        "BTC-USDT-PERP": _risk_frame(fidelity_flags=("btc_mark",)),
        "ETH-USDT-PERP": _risk_frame(
            "ETH-USDT-PERP",
            mark_open=3_000.0,
            mark_high=3_010.0,
            mark_low=2_990.0,
            mark_close=3_000.0,
            fidelity_flags=("eth_mark",),
        ),
    }

    snapshot = CrossMarginRiskModel().evaluate(account, frames, "adverse")

    assert snapshot.per_position[0].unrealized_pnl == pytest.approx(-500.0)
    assert snapshot.per_position[1].unrealized_pnl == pytest.approx(900.0)
    assert snapshot.margin_balance == pytest.approx(1_400.0)
    assert snapshot.initial_margin == pytest.approx(8_940.0)
    assert snapshot.maintenance_margin == pytest.approx(367.1)
    assert snapshot.available_balance == pytest.approx(-7_540.0)
    assert snapshot.status == "healthy"
    assert snapshot.liquidation_targets == ()
    assert snapshot.fidelity_flags == (
        "btc_mark",
        "eth_mark",
        "conservative_intrabar_assumption",
    )


def test_cross_remains_healthy_just_above_maintenance_threshold() -> None:
    account = AccountState(
        747.5000000000005,
        (PositionState("BTC-USDT-PERP", 1.0, 60_000.0, 10.0, 0.0, None),),
        "cross",
    )

    snapshot = CrossMarginRiskModel().evaluate(
        account, {"BTC-USDT-PERP": _risk_frame()}
    )

    assert snapshot.margin_balance > snapshot.maintenance_margin
    assert snapshot.status == "healthy"
    assert snapshot.liquidation_targets == ()


@pytest.mark.parametrize("margin_mode", ["isolated", "cross"])
def test_risk_models_reject_unsynchronized_position_frames(margin_mode: str) -> None:
    margin = 1_000.0 if margin_mode == "isolated" else None
    account = AccountState(
        1_000.0,
        (
            PositionState("BTC-USDT-PERP", 0.1, 60_000.0, 10.0, 0.0, margin),
            PositionState("ETH-USDT-PERP", 1.0, 3_000.0, 10.0, 0.0, margin),
        ),
        margin_mode,
    )
    frames = {
        "BTC-USDT-PERP": _risk_frame(),
        "ETH-USDT-PERP": _risk_frame(
            "ETH-USDT-PERP",
            timestamp=pd.Timestamp("2026-07-26T00:01:00Z"),
            mark_open=3_000.0,
            mark_high=3_010.0,
            mark_low=2_990.0,
            mark_close=3_000.0,
        ),
    }

    with pytest.raises(ValueError, match="timestamps"):
        (evaluate_isolated if margin_mode == "isolated" else CrossMarginRiskModel().evaluate)(account, frames)
