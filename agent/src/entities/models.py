"""Typed entity and instrument models for the non-bar asset spine.

These models describe *what* is being analysed (a fund, a bond, an issuer),
never *how it traded on a given day*. Anything with a daily OHLCV bar is
already served by ``backtest/loaders`` and its engines; this module exists for
holdings whose economics are a stream of dated cash amounts instead of a price
series (see ``src.entities.cashflow``).

Every model is a frozen dataclass: once constructed, an instance is a fact, not
a mutable scratch buffer. Validation happens once at construction so downstream
code never has to re-check an ``Instrument`` it was handed.

Currency is required on every instrument. A currency-less instrument is the
first step toward summing five currencies into one number, which is exactly the
defect this spine is meant to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

__all__ = [
    "Bond",
    "Entity",
    "EntityType",
    "Fund",
    "FundStructure",
    "Instrument",
    "Security",
    "SecurityType",
    "normalize_currency",
    "normalize_date",
]


class EntityType(str, Enum):
    """Role a legal entity plays relative to an instrument."""

    ISSUER = "issuer"
    MANAGER = "manager"
    SPONSOR = "sponsor"
    COUNTERPARTY = "counterparty"
    SPV = "spv"
    OTHER = "other"


class SecurityType(str, Enum):
    """Broad class of a listed security."""

    EQUITY = "equity"
    PREFERRED = "preferred"
    ETF = "etf"
    ADR = "adr"
    WARRANT = "warrant"
    OTHER = "other"


class FundStructure(str, Enum):
    """Whether a fund's capital is drawn down or subscribed at NAV."""

    CLOSED_END = "closed_end"
    OPEN_END = "open_end"
    EVERGREEN = "evergreen"


def normalize_currency(value: str, *, field_name: str = "currency") -> str:
    """Normalize a currency code to its canonical uppercase form.

    Codes are upper-cased and stripped. Length is deliberately not constrained
    to three characters: this project also handles crypto quote assets such as
    ``USDT``, and rejecting them would push callers into faking a code.

    Args:
        value: Raw currency code, e.g. ``" usd "``.
        field_name: Name used in the error message, for caller context.

    Returns:
        The canonical code, e.g. ``"USD"``.

    Raises:
        ValueError: If the code is empty, not a string, or contains whitespace.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string, got {type(value).__name__}")
    cleaned = value.strip().upper()
    if not cleaned:
        raise ValueError(f"{field_name} is required and cannot be empty")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError(f"{field_name} cannot contain whitespace, got {value!r}")
    return cleaned


def normalize_date(value: date | datetime | str, *, field_name: str = "date") -> date:
    """Coerce a supported date input to a plain ``datetime.date``.

    ``datetime`` instances are truncated to their date, because a cash flow
    settles on a day, not at a timestamp; keeping the time component would make
    two flows on the same day compare unequal for no economic reason.

    Strings must be ISO-8601 (``YYYY-MM-DD``, optionally with a time part).
    Ambiguous regional formats such as ``03/04/2024`` are rejected rather than
    guessed, since guessing day-first vs month-first is a silent wrong answer.

    Args:
        value: A ``date``, a ``datetime``, or an ISO-8601 string.
        field_name: Name used in the error message, for caller context.

    Returns:
        The corresponding ``datetime.date``.

    Raises:
        ValueError: If the value is not a supported type or not ISO-8601.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} is required and cannot be empty")
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text).date()
        except ValueError as exc:
            raise ValueError(
                f"{field_name}={value!r} is not ISO-8601 (YYYY-MM-DD); pass an "
                "explicit date_format instead of relying on inference"
            ) from exc
    raise ValueError(
        f"{field_name} must be a date, datetime, or ISO-8601 string, "
        f"got {type(value).__name__}"
    )


@dataclass(frozen=True)
class Entity:
    """A legal entity that issues, manages, or faces an instrument.

    Attributes:
        entity_id: Stable identifier, e.g. an LEI, a CIK, or a local key.
        name: Human-readable legal name.
        entity_type: Role the entity plays; see ``EntityType``.
        domicile: Country or jurisdiction code, free-form and optional.
        parent_id: ``entity_id`` of the parent entity, when part of a group.
    """

    entity_id: str
    name: str = ""
    entity_type: EntityType = EntityType.ISSUER
    domicile: str = ""
    parent_id: str | None = None

    def __post_init__(self) -> None:
        """Validate identifiers and coerce ``entity_type`` to its enum member.

        Raises:
            ValueError: If ``entity_id`` is blank or ``entity_type`` is unknown.
        """
        cleaned = self.entity_id.strip() if isinstance(self.entity_id, str) else ""
        if not cleaned:
            raise ValueError("entity_id is required and cannot be empty")
        object.__setattr__(self, "entity_id", cleaned)
        object.__setattr__(self, "name", self.name.strip() if self.name else "")
        try:
            object.__setattr__(self, "entity_type", EntityType(self.entity_type))
        except ValueError as exc:
            valid = ", ".join(member.value for member in EntityType)
            raise ValueError(
                f"unknown entity_type {self.entity_type!r}; expected one of: {valid}"
            ) from exc
        if self.parent_id is not None and self.parent_id == self.entity_id:
            raise ValueError(f"entity {self.entity_id!r} cannot be its own parent")


@dataclass(frozen=True)
class Instrument:
    """Base class for anything that can be held and analysed.

    Subclasses add asset-class specifics; they may only add fields *with*
    defaults, because the base already declares defaulted fields.

    Attributes:
        instrument_id: Stable identifier, e.g. an ISIN, a ticker, or a local key.
        currency: Required ISO-style currency code of this instrument's cash
            flows. Normalized to uppercase.
        name: Human-readable name.
        issuer: The entity on the hook for the instrument's obligations.
        inception_date: First date the instrument existed, when known.
    """

    instrument_id: str
    currency: str
    name: str = ""
    issuer: Entity | None = None
    inception_date: date | None = None

    def __post_init__(self) -> None:
        """Validate the identifier and normalize currency and inception date.

        Raises:
            ValueError: If ``instrument_id`` is blank, the currency is invalid,
                or ``inception_date`` is not a supported date value.
        """
        cleaned = (
            self.instrument_id.strip() if isinstance(self.instrument_id, str) else ""
        )
        if not cleaned:
            raise ValueError("instrument_id is required and cannot be empty")
        object.__setattr__(self, "instrument_id", cleaned)
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(self, "name", self.name.strip() if self.name else "")
        if self.inception_date is not None:
            object.__setattr__(
                self,
                "inception_date",
                normalize_date(self.inception_date, field_name="inception_date"),
            )


@dataclass(frozen=True)
class Security(Instrument):
    """A listed security identified by a ticker on a venue.

    A ``Security`` here is the *reference* record only. Its price history still
    belongs to the bar-based loader path; this class exists so a corporate
    action or a dividend stream can be attached to a named instrument.

    Attributes:
        symbol: Exchange ticker, e.g. ``"AAPL"`` or ``"600519"``.
        exchange: Venue code, e.g. ``"XNAS"`` or ``"SSE"``.
        security_type: Broad class; see ``SecurityType``.
    """

    symbol: str = ""
    exchange: str = ""
    security_type: SecurityType = SecurityType.EQUITY

    def __post_init__(self) -> None:
        """Validate the base fields and coerce ``security_type``.

        Raises:
            ValueError: If ``security_type`` is not a known member.
        """
        super().__post_init__()
        object.__setattr__(self, "symbol", self.symbol.strip() if self.symbol else "")
        object.__setattr__(
            self, "exchange", self.exchange.strip() if self.exchange else ""
        )
        try:
            object.__setattr__(
                self, "security_type", SecurityType(self.security_type)
            )
        except ValueError as exc:
            valid = ", ".join(member.value for member in SecurityType)
            raise ValueError(
                f"unknown security_type {self.security_type!r}; "
                f"expected one of: {valid}"
            ) from exc


@dataclass(frozen=True)
class Fund(Instrument):
    """A pooled vehicle whose economics are calls, distributions, and NAV marks.

    This is the archetypal instrument that cannot be expressed as a daily bar:
    a closed-end fund has no price, only an irregular cash-flow stream and a
    periodic valuation.

    Attributes:
        vintage_year: Year the fund began investing, when known.
        structure: Capital structure; see ``FundStructure``.
        strategy: Free-form strategy label, e.g. ``"buyout"``.
        commitment: Total capital committed by the holder, in ``currency``.
            Non-negative; it is a size, not a signed cash flow.
        management_fee_rate: Annual management fee as a decimal fraction
            (``0.02`` means 2%), not a percentage.
    """

    vintage_year: int | None = None
    structure: FundStructure = FundStructure.CLOSED_END
    strategy: str = ""
    commitment: float | None = None
    management_fee_rate: float | None = None

    def __post_init__(self) -> None:
        """Validate the base fields plus fund-specific ranges.

        Raises:
            ValueError: If ``structure`` is unknown, ``commitment`` is
                negative, ``management_fee_rate`` is out of ``[0, 1]``, or
                ``vintage_year`` is implausible.
        """
        super().__post_init__()
        try:
            object.__setattr__(self, "structure", FundStructure(self.structure))
        except ValueError as exc:
            valid = ", ".join(member.value for member in FundStructure)
            raise ValueError(
                f"unknown structure {self.structure!r}; expected one of: {valid}"
            ) from exc
        if self.vintage_year is not None and not 1800 <= int(self.vintage_year) <= 2200:
            raise ValueError(
                f"vintage_year={self.vintage_year!r} is outside the plausible "
                "range 1800-2200"
            )
        if self.commitment is not None:
            if float(self.commitment) < 0:
                raise ValueError(
                    f"commitment must be non-negative (it is a size, not a signed "
                    f"cash flow), got {self.commitment!r}"
                )
            object.__setattr__(self, "commitment", float(self.commitment))
        if self.management_fee_rate is not None:
            rate = float(self.management_fee_rate)
            if not 0.0 <= rate <= 1.0:
                raise ValueError(
                    f"management_fee_rate must be a decimal fraction in [0, 1] "
                    f"(0.02 means 2%), got {self.management_fee_rate!r}"
                )
            object.__setattr__(self, "management_fee_rate", rate)


@dataclass(frozen=True)
class Bond(Instrument):
    """A debt instrument paying scheduled coupons and returning principal.

    Attributes:
        face_value: Redemption amount per unit, in ``currency``. Positive.
        coupon_rate: Annual coupon as a decimal fraction (``0.05`` means 5%),
            not a percentage. Zero marks a zero-coupon bond.
        coupon_frequency: Coupon payments per year. Zero is only valid for a
            zero-coupon bond.
        maturity_date: Redemption date, when known.
        day_count: Day-count convention label, e.g. ``"30/360"`` or
            ``"ACT/365"``. Free-form; consumers decide how to apply it.
    """

    face_value: float | None = None
    coupon_rate: float | None = None
    coupon_frequency: int = 2
    maturity_date: date | None = None
    day_count: str = "30/360"

    def __post_init__(self) -> None:
        """Validate the base fields plus bond-specific ranges and consistency.

        Raises:
            ValueError: If ``face_value`` is non-positive, ``coupon_rate`` is
                negative or expressed as a percentage, the coupon frequency
                contradicts the coupon rate, or maturity precedes inception.
        """
        super().__post_init__()
        if self.face_value is not None:
            face = float(self.face_value)
            if face <= 0:
                raise ValueError(f"face_value must be positive, got {self.face_value!r}")
            object.__setattr__(self, "face_value", face)
        if self.coupon_rate is not None:
            rate = float(self.coupon_rate)
            if rate < 0:
                raise ValueError(f"coupon_rate cannot be negative, got {rate!r}")
            if rate > 1.0:
                raise ValueError(
                    f"coupon_rate must be a decimal fraction (0.05 means 5%), "
                    f"got {rate!r}; a value above 1.0 is almost certainly a "
                    "percentage"
                )
            object.__setattr__(self, "coupon_rate", rate)
        frequency = int(self.coupon_frequency)
        if frequency < 0:
            raise ValueError(
                f"coupon_frequency cannot be negative, got {self.coupon_frequency!r}"
            )
        if self.coupon_rate and frequency == 0:
            raise ValueError(
                f"coupon_frequency=0 marks a zero-coupon bond, but coupon_rate="
                f"{self.coupon_rate!r} is non-zero"
            )
        object.__setattr__(self, "coupon_frequency", frequency)
        if self.maturity_date is not None:
            object.__setattr__(
                self,
                "maturity_date",
                normalize_date(self.maturity_date, field_name="maturity_date"),
            )
            if self.inception_date is not None and self.maturity_date < self.inception_date:
                raise ValueError(
                    f"maturity_date {self.maturity_date} precedes inception_date "
                    f"{self.inception_date}"
                )
