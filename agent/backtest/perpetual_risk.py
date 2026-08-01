"""Pure state and risk contracts for historical USD-M perpetual backtests.

The model is deliberately account-local and deterministic. It does not read
live exchange state, model open orders, or store mutable mark prices on
positions.

Maintenance-bracket data comes from the loader's already-validated artifact
contract (``backtest.loaders.ccxt_loader._validate_bracket_artifact``): a
symbol, a list of tiers, and a single content-hash version. This module does
not re-fetch, re-derive, or re-hash brackets — it only re-validates their
structural invariants (ordering, non-negativity) as a defense-in-depth check
on whatever the caller passes in.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Literal

import pandas as pd


MarginMode = Literal["isolated", "cross"]
TerminalStatus = Literal["active", "completed", "account_liquidation"]


def _require_finite(name: str, value: float, *, positive: bool = False) -> None:
    if not math.isfinite(value) or (positive and value <= 0):
        qualifier = "positive and finite" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")


def _timestamp(value: pd.Timestamp, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{name} must be a valid timestamp")
    return timestamp


@dataclass(frozen=True)
class MaintenanceBracket:
    """One symbol-specific maintenance-margin bracket.

    Field names and semantics match the loader's bracket-artifact tier
    records exactly (``bracket_tier``, ``notional_cap``, ``maintenance_rate``,
    ``cumulative_maintenance_amount``, optional ``notional_coefficient``).
    """

    bracket_tier: int
    notional_cap: float
    maintenance_rate: float
    cumulative_maintenance_amount: float
    notional_coefficient: float | None = None

    def __post_init__(self) -> None:
        if self.bracket_tier < 0:
            raise ValueError("bracket_tier must be non-negative")
        _require_finite("notional_cap", self.notional_cap, positive=True)
        _require_finite("maintenance_rate", self.maintenance_rate)
        _require_finite(
            "cumulative_maintenance_amount", self.cumulative_maintenance_amount
        )
        if self.maintenance_rate < 0:
            raise ValueError("maintenance_rate must be non-negative")
        if self.cumulative_maintenance_amount < 0:
            raise ValueError("cumulative_maintenance_amount must be non-negative")
        if self.notional_coefficient is not None:
            _require_finite("notional_coefficient", self.notional_coefficient)


@dataclass(frozen=True)
class MaintenanceSchedule:
    """A validated, versioned set of maintenance brackets for one symbol.

    ``version`` is an opaque identifier supplied by the caller — in practice
    the loader's ``maintenance_bracket_version`` content-hash column. This
    class does not compute its own hash: the artifact contract
    (``_validate_bracket_artifact``) is the single source of truth for
    content integrity, checked once, before this object is ever built.
    """

    symbol: str
    version: str
    brackets: tuple[MaintenanceBracket, ...]

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if not self.version:
            raise ValueError("version must not be empty")
        if not self.brackets:
            raise ValueError("brackets must not be empty")
        tiers = [bracket.bracket_tier for bracket in self.brackets]
        if tiers != sorted(tiers) or len(tiers) != len(set(tiers)):
            raise ValueError("bracket_tier values must be strictly increasing")
        caps = [bracket.notional_cap for bracket in self.brackets]
        if any(current <= previous for previous, current in zip(caps, caps[1:])):
            raise ValueError("notional caps must be strictly increasing")

    @classmethod
    def from_loader_columns(
        cls, symbol: str, maintenance_brackets: str, maintenance_bracket_version: str,
    ) -> MaintenanceSchedule:
        """Build a schedule from the loader's ``maintenance_brackets`` /
        ``maintenance_bracket_version`` DataFrame columns.

        The JSON payload is already-validated tier records (from
        ``_validate_bracket_artifact``) — this only parses and re-checks
        structural invariants, it never re-derives the version hash.
        """
        try:
            records = json.loads(maintenance_brackets)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("maintenance_brackets is not valid JSON") from exc
        if not isinstance(records, list) or not records:
            raise ValueError("maintenance_brackets must be a non-empty list")
        brackets = tuple(
            MaintenanceBracket(
                bracket_tier=record["bracket_tier"],
                notional_cap=record["notional_cap"],
                maintenance_rate=record["maintenance_rate"],
                cumulative_maintenance_amount=record["cumulative_maintenance_amount"],
                notional_coefficient=record.get("notional_coefficient"),
            )
            for record in records
        )
        return cls(symbol=symbol, version=maintenance_bracket_version, brackets=brackets)


@dataclass(frozen=True)
class PositionState:
    """Exchange-independent open-position accounting state."""

    symbol: str
    quantity: float
    entry_price: float
    leverage: float
    accumulated_entry_fee: float
    isolated_margin: float | None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        _require_finite("quantity", self.quantity)
        if self.quantity == 0:
            raise ValueError("quantity must be non-zero")
        _require_finite("entry_price", self.entry_price, positive=True)
        _require_finite("leverage", self.leverage, positive=True)
        _require_finite("accumulated_entry_fee", self.accumulated_entry_fee)
        if self.accumulated_entry_fee < 0:
            raise ValueError("accumulated_entry_fee must be non-negative")
        if self.isolated_margin is not None:
            _require_finite("isolated_margin", self.isolated_margin, positive=True)


@dataclass(frozen=True)
class PositionRisk:
    symbol: str
    mark_price: float
    notional: float
    unrealized_pnl: float
    initial_margin: float
    maintenance_margin: float
    margin_balance: float | None


@dataclass(frozen=True)
class RiskSnapshot:
    margin_balance: float
    initial_margin: float
    maintenance_margin: float
    available_balance: float
    per_position: tuple[PositionRisk, ...]
    status: Literal["healthy", "position_liquidation", "account_liquidation"]
    liquidation_targets: tuple[str, ...]
    fidelity_flags: tuple[str, ...]


def maintenance_margin(
    position: PositionState, mark_price: float, schedule: MaintenanceSchedule
) -> float:
    if position.symbol != schedule.symbol:
        raise ValueError("position and schedule symbols must match")
    _require_finite("mark_price", mark_price, positive=True)
    notional = abs(position.quantity) * mark_price
    for bracket in schedule.brackets:
        if notional <= bracket.notional_cap:
            return notional * bracket.maintenance_rate - bracket.cumulative_maintenance_amount
    raise ValueError("notional exceeds the final maintenance bracket cap")


@dataclass(frozen=True)
class AccountState:
    """Single-asset USDT account state without open-order margin."""

    wallet_balance: float
    positions: tuple[PositionState, ...]
    margin_mode: MarginMode
    terminal_status: TerminalStatus = "active"

    def __post_init__(self) -> None:
        _require_finite("wallet_balance", self.wallet_balance)
        if self.margin_mode not in {"isolated", "cross"}:
            raise ValueError("margin_mode must be 'isolated' or 'cross'")
        if self.terminal_status not in {"active", "completed", "account_liquidation"}:
            raise ValueError("unsupported terminal_status")
        symbols = [position.symbol for position in self.positions]
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate position symbol")


@dataclass(frozen=True)
class ExecutionFrame:
    """Normal market-fill input, separate from exchange mark prices."""

    timestamp: pd.Timestamp
    execution_open: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp, "timestamp"))
        _require_finite("execution_open", self.execution_open, positive=True)


@dataclass(frozen=True)
class MarketRiskFrame:
    """Immutable mark, funding, bracket, provenance, and fidelity input.

    ``schedule`` is optional: the loader only attaches bracket columns when
    a caller supplies a validated artifact (``require_brackets=True`` without
    one fails closed at the loader level, before data ever reaches here). A
    frame with ``schedule=None`` is valid for execution/mark/funding-only use.
    """

    timestamp: pd.Timestamp
    mark_open: float
    mark_high: float
    mark_low: float
    mark_close: float
    funding_rate: float | None
    funding_settlement_time: pd.Timestamp | None
    schedule: MaintenanceSchedule | None
    source: str
    fidelity_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        timestamp = _timestamp(self.timestamp, "timestamp")
        object.__setattr__(self, "timestamp", timestamp)
        for name in ("mark_open", "mark_high", "mark_low", "mark_close"):
            _require_finite(name, getattr(self, name), positive=True)
        if self.mark_high < max(self.mark_open, self.mark_low, self.mark_close):
            raise ValueError("mark_high must contain the mark OHLC range")
        if self.mark_low > min(self.mark_open, self.mark_high, self.mark_close):
            raise ValueError("mark_low must contain the mark OHLC range")
        has_rate = self.funding_rate is not None
        has_settlement = self.funding_settlement_time is not None
        if has_rate != has_settlement:
            raise ValueError("funding rate and settlement timestamp must be paired")
        if self.funding_rate is not None:
            _require_finite("funding_rate", self.funding_rate)
            settlement = _timestamp(
                self.funding_settlement_time, "funding_settlement_time"
            )
            if settlement != timestamp:
                raise ValueError("funding settlement timestamp must match frame timestamp")
            object.__setattr__(self, "funding_settlement_time", settlement)
        if not self.source:
            raise ValueError("source must not be empty")
        if len(self.fidelity_flags) != len(set(self.fidelity_flags)):
            raise ValueError("fidelity_flags must not contain duplicates")


def _mark_price(
    position: PositionState, frame: MarketRiskFrame, price_field: str
) -> float:
    if price_field == "adverse":
        return frame.mark_low if position.quantity > 0 else frame.mark_high
    if price_field not in {"mark_open", "mark_high", "mark_low", "mark_close"}:
        raise ValueError("unsupported price_field")
    return getattr(frame, price_field)


def _position_risks(
    account: AccountState,
    frames: dict[str, MarketRiskFrame],
    price_field: str,
    *,
    isolated: bool,
) -> tuple[tuple[PositionRisk, ...], tuple[str, ...]]:
    if price_field not in {"adverse", "mark_open", "mark_high", "mark_low", "mark_close"}:
        raise ValueError("unsupported price_field")

    risks: list[PositionRisk] = []
    timestamps: set[pd.Timestamp] = set()
    fidelity_flags: list[str] = []
    for position in account.positions:
        frame = frames.get(position.symbol)
        if frame is None:
            raise ValueError("missing market risk frame")
        if frame.schedule is None:
            raise ValueError("missing maintenance schedule")
        if frame.schedule.symbol != position.symbol:
            raise ValueError("position and schedule symbols must match")
        if isolated and position.isolated_margin is None:
            raise ValueError("isolated_margin is required")

        timestamps.add(frame.timestamp)
        fidelity_flags.extend(frame.fidelity_flags)
        mark_price = _mark_price(position, frame, price_field)
        unrealized_pnl = position.quantity * (mark_price - position.entry_price)
        initial_margin = abs(position.quantity) * mark_price / position.leverage
        margin_balance = (
            position.isolated_margin + unrealized_pnl if isolated else None
        )
        risks.append(
            PositionRisk(
                symbol=position.symbol,
                mark_price=mark_price,
                notional=abs(position.quantity) * mark_price,
                unrealized_pnl=unrealized_pnl,
                initial_margin=initial_margin,
                maintenance_margin=maintenance_margin(position, mark_price, frame.schedule),
                margin_balance=margin_balance,
            )
        )

    if len(timestamps) > 1:
        raise ValueError("position frame timestamps must match")
    if len(account.positions) > 1 and price_field == "adverse":
        fidelity_flags.append("conservative_intrabar_assumption")
    return tuple(risks), tuple(dict.fromkeys(fidelity_flags))


def _risk_snapshot(
    account: AccountState,
    risks: tuple[PositionRisk, ...],
    fidelity_flags: tuple[str, ...],
    status: Literal["healthy", "position_liquidation", "account_liquidation"],
    liquidation_targets: tuple[str, ...],
) -> RiskSnapshot:
    margin_balance = account.wallet_balance + sum(risk.unrealized_pnl for risk in risks)
    initial_margin = sum(risk.initial_margin for risk in risks)
    maintenance = sum(risk.maintenance_margin for risk in risks)
    return RiskSnapshot(
        margin_balance=margin_balance,
        initial_margin=initial_margin,
        maintenance_margin=maintenance,
        available_balance=margin_balance - initial_margin,
        per_position=risks,
        status=status,
        liquidation_targets=liquidation_targets,
        fidelity_flags=fidelity_flags,
    )


def evaluate_isolated(
    account: AccountState,
    frames: dict[str, MarketRiskFrame],
    price_field: str = "adverse",
) -> RiskSnapshot:
    if account.margin_mode != "isolated":
        raise ValueError("account margin_mode must be 'isolated'")
    risks, fidelity_flags = _position_risks(account, frames, price_field, isolated=True)
    liquidation_targets = tuple(
        risk.symbol
        for risk in risks
        if risk.margin_balance is not None
        and risk.margin_balance <= risk.maintenance_margin
    )
    return _risk_snapshot(
        account,
        risks,
        fidelity_flags,
        "position_liquidation" if liquidation_targets else "healthy",
        liquidation_targets,
    )


class CrossMarginRiskModel:
    def evaluate(
        self,
        account: AccountState,
        frames: dict[str, MarketRiskFrame],
        price_field: str = "adverse",
    ) -> RiskSnapshot:
        if account.margin_mode != "cross":
            raise ValueError("account margin_mode must be 'cross'")
        if any(position.isolated_margin is not None for position in account.positions):
            raise ValueError("cross positions must not have isolated_margin")
        risks, fidelity_flags = _position_risks(
            account, frames, price_field, isolated=False
        )
        margin_balance = account.wallet_balance + sum(
            risk.unrealized_pnl for risk in risks
        )
        maintenance = sum(risk.maintenance_margin for risk in risks)
        liquidation_targets = (
            tuple(position.symbol for position in account.positions)
            if risks and margin_balance <= maintenance
            else ()
        )
        return _risk_snapshot(
            account,
            risks,
            fidelity_flags,
            "account_liquidation" if liquidation_targets else "healthy",
            liquidation_targets,
        )
