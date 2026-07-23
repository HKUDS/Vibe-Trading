from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from backtest.perpetual_risk import (
    AccountState,
    ExecutionFrame,
    MaintenanceBracket,
    MaintenanceSchedule,
    MarketRiskFrame,
    PositionState,
)


def _brackets() -> tuple[MaintenanceBracket, ...]:
    return (
        MaintenanceBracket(1, 50_000.0, 0.004, 0.0),
        MaintenanceBracket(2, 250_000.0, 0.005, 50.0),
    )


def _schedule(symbol: str = "BTC-USDT-PERP", version: str = "abc123") -> MaintenanceSchedule:
    return MaintenanceSchedule(symbol, version, _brackets())


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
