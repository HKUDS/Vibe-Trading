"""Pure comparison of Binance USD-M observations with local risk state.

This module is deliberately offline.  It owns no connector, credential, file,
or network path, and an exchange observation never becomes an accounting input.
The comparison covers reported account and position fields only; it does not
validate Binance liquidation sequencing.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

import pandas as pd

from backtest.perpetual_risk import AccountState, PositionRisk, PositionState, RiskSnapshot


SnapshotStatus = Literal["complete", "incomplete", "unsupported"]
ComparisonStatus = Literal["comparison_complete"]
_CANONICAL_USDM_SYMBOL = re.compile(r"^[A-Z0-9]+-USDT-PERP$")


def _require_finite(name: str, value: float, *, non_negative: bool = False) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_utc_timestamp(value: pd.Timestamp, name: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware pandas Timestamp")
    return value.tz_convert("UTC")


@dataclass(frozen=True)
class BinancePositionSnapshot:
    """One normalized USD-M position reported by the exchange read layer."""

    symbol: str
    quantity: float
    entry_price: float
    leverage: float
    margin_mode: Literal["isolated", "cross"]
    isolated_margin: float | None
    unrealized_pnl: float
    initial_margin: float
    maintenance_margin: float

    def __post_init__(self) -> None:
        if not _CANONICAL_USDM_SYMBOL.fullmatch(self.symbol):
            raise ValueError("symbol must use canonical *-USDT-PERP form")
        _require_finite("quantity", self.quantity)
        if self.quantity == 0:
            raise ValueError("quantity must be non-zero")
        _require_finite("entry_price", self.entry_price)
        if self.entry_price <= 0:
            raise ValueError("entry_price must be positive")
        _require_finite("leverage", self.leverage)
        if self.leverage <= 0:
            raise ValueError("leverage must be positive")
        if self.margin_mode not in {"isolated", "cross"}:
            raise ValueError("margin_mode must be 'isolated' or 'cross'")
        if self.margin_mode == "isolated":
            if self.isolated_margin is None:
                raise ValueError("isolated positions require isolated_margin")
            _require_finite("isolated_margin", self.isolated_margin)
            if self.isolated_margin <= 0:
                raise ValueError("isolated_margin must be positive")
        elif self.isolated_margin is not None:
            raise ValueError("cross positions must not have isolated_margin")
        _require_finite("unrealized_pnl", self.unrealized_pnl)
        _require_finite("initial_margin", self.initial_margin, non_negative=True)
        _require_finite("maintenance_margin", self.maintenance_margin, non_negative=True)


@dataclass(frozen=True)
class BinanceAccountSnapshot:
    """Immutable, normalized evidence from a Binance USD-M account read."""

    schema_version: str
    observed_at: pd.Timestamp
    source: str
    source_profile: str
    configuration_hash: str
    data_status: SnapshotStatus
    wallet_balance: float
    margin_balance: float
    available_balance: float
    total_unrealized_pnl: float
    total_initial_margin: float
    total_maintenance_margin: float
    positions: tuple[BinancePositionSnapshot, ...]
    fidelity_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("schema_version must not be empty")
        _require_utc_timestamp(self.observed_at, "observed_at")
        if self.source != "binance-usdm":
            raise ValueError("source must be 'binance-usdm'")
        if not self.source_profile:
            raise ValueError("source_profile must not be empty")
        if not self.configuration_hash:
            raise ValueError("configuration_hash must not be empty")
        if self.data_status not in {"complete", "incomplete", "unsupported"}:
            raise ValueError("unsupported data_status")
        for name in (
            "wallet_balance",
            "margin_balance",
            "available_balance",
            "total_unrealized_pnl",
        ):
            _require_finite(name, getattr(self, name))
        _require_finite("total_initial_margin", self.total_initial_margin, non_negative=True)
        _require_finite(
            "total_maintenance_margin",
            self.total_maintenance_margin,
            non_negative=True,
        )
        symbols = tuple(position.symbol for position in self.positions)
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate position symbol")
        if any(not flag for flag in self.fidelity_flags):
            raise ValueError("fidelity flags must not be empty")
        if len(self.fidelity_flags) != len(set(self.fidelity_flags)):
            raise ValueError("fidelity flags must be unique")


@dataclass(frozen=True)
class ReconciliationTolerance:
    """Versioned numeric and timestamp tolerances for one comparison."""

    absolute: float = 1e-8
    relative: float = 1e-8
    max_timestamp_skew_seconds: float = 0.0
    version: str = "reconciliation-tolerance-v1"

    def __post_init__(self) -> None:
        for name in ("absolute", "relative", "max_timestamp_skew_seconds"):
            _require_finite(name, getattr(self, name), non_negative=True)
        if not self.version:
            raise ValueError("tolerance version must not be empty")


@dataclass(frozen=True)
class NumericComparison:
    """One deterministic local-versus-exchange numeric comparison."""

    field: str
    local_value: float
    exchange_value: float
    absolute_delta: float
    allowed_delta: float
    within_tolerance: bool
    symbol: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    """Comparison evidence; never an exchange-engine validation verdict."""

    status: ComparisonStatus
    has_drift: bool
    observed_at: pd.Timestamp
    source: str
    source_profile: str
    snapshot_schema_version: str
    snapshot_configuration_hash: str
    tolerance_version: str
    comparisons: tuple[NumericComparison, ...]
    missing_on_exchange: tuple[str, ...]
    unexpected_on_exchange: tuple[str, ...]
    structural_differences: tuple[str, ...]
    fidelity_flags: tuple[str, ...]
    comparison_scope: Literal["account_snapshot_fields_only"] = "account_snapshot_fields_only"
    liquidation_engine_assessment: Literal["not_assessed"] = "not_assessed"


def _comparison(
    field: str,
    local_value: float,
    exchange_value: float,
    tolerance: ReconciliationTolerance,
    *,
    symbol: str | None = None,
) -> NumericComparison:
    absolute_delta = abs(local_value - exchange_value)
    allowed_delta = max(
        tolerance.absolute,
        tolerance.relative * max(abs(local_value), abs(exchange_value)),
    )
    return NumericComparison(
        field=field,
        local_value=local_value,
        exchange_value=exchange_value,
        absolute_delta=absolute_delta,
        allowed_delta=allowed_delta,
        within_tolerance=absolute_delta <= allowed_delta,
        symbol=symbol,
    )


def _position_maps(
    account: AccountState,
    risk: RiskSnapshot,
    exchange: BinanceAccountSnapshot,
) -> tuple[
    dict[str, PositionState],
    dict[str, PositionRisk],
    dict[str, BinancePositionSnapshot],
]:
    local_positions = {position.symbol: position for position in account.positions}
    local_risks = {position.symbol: position for position in risk.per_position}
    if set(local_positions) != set(local_risks):
        raise ValueError("local account and risk snapshot symbols must match")
    exchange_positions = {position.symbol: position for position in exchange.positions}
    return local_positions, local_risks, exchange_positions


def reconcile_binance_account(
    local_account: AccountState,
    local_risk: RiskSnapshot,
    exchange_snapshot: BinanceAccountSnapshot,
    *,
    expected_timestamp: pd.Timestamp,
    tolerance: ReconciliationTolerance = ReconciliationTolerance(),
) -> ReconciliationReport:
    """Compare immutable local state with one complete USD-M observation.

    Raises:
        ValueError: If the source is incomplete, timestamps are incoherent, or
            the local account and risk snapshot do not describe the same symbols.
    """
    if exchange_snapshot.data_status != "complete":
        raise ValueError("exchange snapshot data_status must be complete")
    expected = _require_utc_timestamp(expected_timestamp, "expected_timestamp")
    observed = _require_utc_timestamp(exchange_snapshot.observed_at, "observed_at")
    skew = abs((observed - expected).total_seconds())
    if skew > tolerance.max_timestamp_skew_seconds:
        raise ValueError("exchange snapshot timestamp skew exceeds tolerance")

    local_positions, local_risks, exchange_positions = _position_maps(local_account, local_risk, exchange_snapshot)
    local_symbols = set(local_positions)
    exchange_symbols = set(exchange_positions)
    missing = tuple(sorted(local_symbols - exchange_symbols))
    unexpected = tuple(sorted(exchange_symbols - local_symbols))
    shared = tuple(sorted(local_symbols & exchange_symbols))

    account_values = (
        ("wallet_balance", local_account.wallet_balance, exchange_snapshot.wallet_balance),
        ("margin_balance", local_risk.margin_balance, exchange_snapshot.margin_balance),
        ("available_balance", local_risk.available_balance, exchange_snapshot.available_balance),
        (
            "total_unrealized_pnl",
            sum(position.unrealized_pnl for position in local_risk.per_position),
            exchange_snapshot.total_unrealized_pnl,
        ),
        ("total_initial_margin", local_risk.initial_margin, exchange_snapshot.total_initial_margin),
        (
            "total_maintenance_margin",
            local_risk.maintenance_margin,
            exchange_snapshot.total_maintenance_margin,
        ),
    )
    comparisons = [_comparison(field, local, exchange, tolerance) for field, local, exchange in account_values]
    structural: list[str] = []
    for symbol in shared:
        local_position = local_positions[symbol]
        local_position_risk = local_risks[symbol]
        exchange_position = exchange_positions[symbol]
        if local_account.margin_mode != exchange_position.margin_mode:
            structural.append(
                f"{symbol}:margin_mode:local={local_account.margin_mode}:exchange={exchange_position.margin_mode}"
            )
        local_isolated = local_position.isolated_margin
        exchange_isolated = exchange_position.isolated_margin
        if (local_isolated is None) != (exchange_isolated is None):
            structural.append(f"{symbol}:isolated_margin_presence")
        elif local_isolated is not None and exchange_isolated is not None:
            comparisons.append(
                _comparison(
                    "isolated_margin",
                    local_isolated,
                    exchange_isolated,
                    tolerance,
                    symbol=symbol,
                )
            )
        position_values = (
            ("quantity", local_position.quantity, exchange_position.quantity),
            ("entry_price", local_position.entry_price, exchange_position.entry_price),
            ("leverage", local_position.leverage, exchange_position.leverage),
            ("unrealized_pnl", local_position_risk.unrealized_pnl, exchange_position.unrealized_pnl),
            ("initial_margin", local_position_risk.initial_margin, exchange_position.initial_margin),
            (
                "maintenance_margin",
                local_position_risk.maintenance_margin,
                exchange_position.maintenance_margin,
            ),
        )
        for field, local, exchange in position_values:
            comparisons.append(
                _comparison(
                    field,
                    float(local),
                    float(exchange),
                    tolerance,
                    symbol=symbol,
                )
            )

    ordered_comparisons = tuple(comparisons)
    structural_differences = tuple(structural)
    has_drift = bool(
        missing
        or unexpected
        or structural_differences
        or any(not item.within_tolerance for item in ordered_comparisons)
    )
    fidelity_flags = tuple(
        dict.fromkeys(
            (
                *local_risk.fidelity_flags,
                *exchange_snapshot.fidelity_flags,
                "account_snapshot_comparison_only",
            )
        )
    )
    return ReconciliationReport(
        status="comparison_complete",
        has_drift=has_drift,
        observed_at=observed,
        source=exchange_snapshot.source,
        source_profile=exchange_snapshot.source_profile,
        snapshot_schema_version=exchange_snapshot.schema_version,
        snapshot_configuration_hash=exchange_snapshot.configuration_hash,
        tolerance_version=tolerance.version,
        comparisons=ordered_comparisons,
        missing_on_exchange=missing,
        unexpected_on_exchange=unexpected,
        structural_differences=structural_differences,
        fidelity_flags=fidelity_flags,
    )
