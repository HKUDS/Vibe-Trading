"""Irregular dated cash flows: the non-bar half of the asset spine.

SIGN CONVENTION (stated once here, enforced in code, never left to callers)
--------------------------------------------------------------------------
Every amount is expressed **from the holder's point of view**:

    amount > 0  cash comes IN to the holder   (distribution, coupon, proceeds)
    amount < 0  cash goes OUT from the holder (capital call, purchase, fee)

This is the ordinary IRR/XIRR convention, so a ``CashFlowSeries`` can be fed
straight to a money-weighted return without a caller-side sign flip. Because
callers reliably get this backwards when reading a broker export, the canonical
kinds in ``KIND_DIRECTION`` are *enforced* at construction: a ``capital_call``
with a positive amount is rejected, not quietly accepted.

A movement that is genuinely two-directional (a recallable distribution, an
insurance claim whose direction depends on whether you are the insurer or the
policyholder) must be given its own ``kind``. Kinds absent from
``KIND_DIRECTION`` carry no sign constraint, so the escape hatch is to name the
flow honestly rather than to disable the check.

VALUATIONS ARE NOT CASH
-----------------------
A NAV mark is a valuation, not a settled movement. It is representable here
because terminal NAV is required to compute a fund's IRR or TVPI, but it is
tagged via ``CashFlow.is_valuation`` and excluded from ``CashFlowSeries.total()``
unless explicitly requested. Summing a NAV into realised cash would overstate
distributions, so the default is the conservative one.

CURRENCY IS REQUIRED
--------------------
Every flow carries a currency and a series refuses to mix them. The composite
backtest engine once summed five currencies into a single equity curve; that
was a shipped defect. A series of genuinely translated flows must say so
explicitly via ``pre_translated=True`` *and* name its reporting currency.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

from src.entities.models import normalize_currency, normalize_date

__all__ = [
    "CashFlow",
    "CashFlowSeries",
    "CurrencyMismatchError",
    "FxRate",
    "FxRateTable",
    "KIND_DIRECTION",
    "MissingExchangeRateError",
    "VALUATION_KINDS",
    "normalize_kind",
    "translate_cashflows",
]

#: Canonical kinds whose direction is definitional, mapped to the required sign
#: of ``amount`` (``-1`` outflow, ``+1`` inflow). A kind absent from this table
#: carries no sign constraint -- see the module docstring.
KIND_DIRECTION: Mapping[str, int] = MappingProxyType(
    {
        # Cash leaving the holder.
        "contribution": -1,
        "capital_call": -1,
        "purchase": -1,
        "subscription": -1,
        "fee": -1,
        "expense": -1,
        # Cash arriving at the holder.
        "distribution": 1,
        "dividend": 1,
        "coupon": 1,
        "interest": 1,
        "principal": 1,
        "redemption": 1,
        "proceeds": 1,
    }
)

#: Kinds that record a mark rather than a settled cash movement. Excluded from
#: ``CashFlowSeries.total()`` by default.
VALUATION_KINDS: frozenset[str] = frozenset({"nav", "residual_value", "valuation"})


class CurrencyMismatchError(ValueError):
    """Raised when a series would combine amounts in different currencies."""


def normalize_kind(value: str) -> str:
    """Normalize a cash-flow kind label to its canonical snake_case form.

    Real files spell the same concept as ``"Capital Call"``, ``"capital-call"``,
    or ``"CAPITAL_CALL"``. Normalizing means the sign check in ``KIND_DIRECTION``
    actually bites on those files instead of silently treating each spelling as
    an unconstrained custom kind.

    Args:
        value: Raw kind label from a caller or a file.

    Returns:
        Lower-cased label with spaces and hyphens collapsed to underscores.

    Raises:
        ValueError: If the label is not a string or is blank.
    """
    if not isinstance(value, str):
        raise ValueError(f"kind must be a string, got {type(value).__name__}")
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    if not cleaned:
        raise ValueError("kind is required and cannot be empty")
    return cleaned


@dataclass(frozen=True)
class CashFlow:
    """A single dated cash amount in one currency.

    Attributes:
        date: Settlement date. ``datetime`` and ISO-8601 strings are accepted
            and normalized to ``datetime.date``.
        amount: Signed amount, positive into the holder. See the module
            docstring for the convention and its enforcement.
        kind: Canonical kind label, e.g. ``"capital_call"`` or ``"coupon"``.
            Normalized via ``normalize_kind``.
        currency: Required currency code, normalized to uppercase.
        metadata: Free-form extra fields, exposed as a read-only mapping so the
            flow stays immutable. Ingestion puts unmapped file columns here
            rather than discarding them.
    """

    date: date
    amount: float
    kind: str
    currency: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize every field and enforce the sign convention.

        Raises:
            ValueError: If the date is unsupported, the amount is not finite,
                the currency or kind is blank, or the amount's sign contradicts
                a canonical kind in ``KIND_DIRECTION``.
        """
        object.__setattr__(self, "date", normalize_date(self.date))
        object.__setattr__(self, "kind", normalize_kind(self.kind))
        object.__setattr__(self, "currency", normalize_currency(self.currency))

        try:
            amount = float(self.amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"amount must be numeric, got {self.amount!r}"
            ) from exc
        if not math.isfinite(amount):
            raise ValueError(
                f"amount must be a finite number, got {self.amount!r}; a missing "
                "value must be fixed at the source, not carried as NaN"
            )
        object.__setattr__(self, "amount", amount)

        required_sign = KIND_DIRECTION.get(self.kind)
        if required_sign is not None and amount != 0.0:
            if (amount > 0) != (required_sign > 0):
                direction = "positive (cash in)" if required_sign > 0 else "negative (cash out)"
                raise ValueError(
                    f"kind={self.kind!r} must have a {direction} amount under the "
                    f"holder-perspective sign convention, got {amount!r}. Flip the "
                    "sign, or use a distinct kind if this flow is genuinely "
                    "two-directional (e.g. 'recallable_distribution')."
                )

        if not isinstance(self.metadata, Mapping):
            raise ValueError(
                f"metadata must be a mapping, got {type(self.metadata).__name__}"
            )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def is_valuation(self) -> bool:
        """Whether this record is a mark rather than a settled cash movement.

        Returns:
            True when ``kind`` is one of ``VALUATION_KINDS``.
        """
        return self.kind in VALUATION_KINDS


@dataclass(frozen=True)
class CashFlowSeries:
    """An ordered, immutable collection of ``CashFlow`` in one currency.

    Flows are sorted by date at construction with a stable sort, so several
    flows on the same date keep the order they were supplied in (a call and a
    distribution on the same day usually have a meaningful sequence).

    Attributes:
        flows: The ordered flows, as a tuple.
        currency: Reporting currency of the series. Inferred from the flows
            when they agree; required explicitly when ``pre_translated`` is set.
            ``None`` only for an empty series with no declared currency.
        pre_translated: Set to True to assert that mixed-currency inputs have
            already been converted into ``currency``. This is the *only* way to
            build a series from flows with differing currency codes.
    """

    flows: tuple[CashFlow, ...] = ()
    currency: str | None = None
    pre_translated: bool = False

    def __post_init__(self) -> None:
        """Validate membership and currency coherence, then order by date.

        Raises:
            ValueError: If a member is not a ``CashFlow``, or if
                ``pre_translated`` is set without naming a reporting currency.
            CurrencyMismatchError: If the flows span multiple currencies while
                ``pre_translated`` is False, or contradict a declared currency.
        """
        flows = tuple(self.flows)
        for item in flows:
            if not isinstance(item, CashFlow):
                raise ValueError(
                    f"CashFlowSeries members must be CashFlow, got "
                    f"{type(item).__name__}"
                )

        declared = (
            normalize_currency(self.currency) if self.currency is not None else None
        )
        present = {flow.currency for flow in flows}

        if self.pre_translated:
            if declared is None:
                raise ValueError(
                    "pre_translated=True asserts the flows were already converted, "
                    "so the reporting currency must be named explicitly via "
                    "currency=..."
                )
        else:
            if len(present) > 1:
                raise CurrencyMismatchError(
                    "cash flows span multiple currencies "
                    f"({', '.join(sorted(present))}); convert them first and pass "
                    "pre_translated=True with the reporting currency, rather than "
                    "summing across currencies"
                )
            if declared is None:
                declared = next(iter(present)) if present else None
            elif present and declared not in present:
                raise CurrencyMismatchError(
                    f"declared currency {declared!r} does not match the flows' "
                    f"currency {next(iter(present))!r}"
                )

        object.__setattr__(self, "currency", declared)
        object.__setattr__(self, "flows", tuple(sorted(flows, key=lambda f: f.date)))

    # ─── Access ───

    def __iter__(self) -> Iterator[CashFlow]:
        """Iterate the flows in date order.

        Returns:
            An iterator over ``CashFlow`` sorted by date.
        """
        return iter(self.flows)

    def __len__(self) -> int:
        """Return the number of flows.

        Returns:
            Count of flows, zero for an empty series.
        """
        return len(self.flows)

    def __getitem__(self, index: int) -> CashFlow:
        """Return the flow at ``index`` in date order.

        Args:
            index: Zero-based position.

        Returns:
            The ``CashFlow`` at that position.

        Raises:
            IndexError: If the position is out of range.
        """
        return self.flows[index]

    @property
    def is_empty(self) -> bool:
        """Whether the series holds no flows.

        Returns:
            True when there are zero flows.
        """
        return not self.flows

    def dates(self) -> tuple[date, ...]:
        """Return every flow date, in order.

        Returns:
            Tuple of dates, possibly with repeats; empty for an empty series.
        """
        return tuple(flow.date for flow in self.flows)

    def amounts(self) -> tuple[float, ...]:
        """Return every signed amount, in date order.

        Returns:
            Tuple of amounts aligned with ``dates()``; empty for an empty series.
        """
        return tuple(flow.amount for flow in self.flows)

    def kinds(self) -> tuple[str, ...]:
        """Return the distinct kinds present, sorted alphabetically.

        Returns:
            Tuple of canonical kind labels; empty for an empty series.
        """
        return tuple(sorted({flow.kind for flow in self.flows}))

    # ─── Derivation ───

    def _rebuild(self, flows: Iterable[CashFlow]) -> CashFlowSeries:
        """Build a derived series that keeps this series' currency contract.

        Args:
            flows: Subset of flows for the new series.

        Returns:
            A new ``CashFlowSeries`` carrying the same currency and
            ``pre_translated`` flag, so a filtered empty series still remembers
            what currency it reports in.
        """
        return CashFlowSeries(
            flows=tuple(flows),
            currency=self.currency,
            pre_translated=self.pre_translated,
        )

    def filter(self, kind: str | Iterable[str] | None = None) -> CashFlowSeries:
        """Select flows by kind.

        Args:
            kind: A single kind label or an iterable of labels. Labels are
                normalized, so ``"Capital Call"`` matches ``"capital_call"``.
                ``None`` returns an equivalent series.

        Returns:
            A new ``CashFlowSeries`` holding only the matching flows.

        Raises:
            ValueError: If a supplied label is blank or not a string.
        """
        if kind is None:
            return self._rebuild(self.flows)
        if isinstance(kind, str):
            wanted = {normalize_kind(kind)}
        else:
            wanted = {normalize_kind(item) for item in kind}
        return self._rebuild(flow for flow in self.flows if flow.kind in wanted)

    def between(
        self,
        start: date | datetime | str | None = None,
        end: date | datetime | str | None = None,
    ) -> CashFlowSeries:
        """Select flows within an inclusive date window.

        Args:
            start: Earliest date to keep, inclusive. ``None`` leaves the window
                open on the left.
            end: Latest date to keep, inclusive. ``None`` leaves it open on the
                right.

        Returns:
            A new ``CashFlowSeries`` holding only flows inside the window.

        Raises:
            ValueError: If a bound is not a supported date value, or if
                ``start`` is later than ``end``.
        """
        lower = normalize_date(start, field_name="start") if start is not None else None
        upper = normalize_date(end, field_name="end") if end is not None else None
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"start {lower} is after end {upper}")
        return self._rebuild(
            flow
            for flow in self.flows
            if (lower is None or flow.date >= lower)
            and (upper is None or flow.date <= upper)
        )

    def total(self, *, include_valuations: bool = False) -> float:
        """Sum the signed amounts.

        Valuation marks such as NAV are excluded by default: adding a mark to
        settled cash would overstate what was actually received.

        Args:
            include_valuations: Set True to include ``VALUATION_KINDS`` records,
                as required when computing a fund's IRR against terminal NAV.

        Returns:
            The signed total, ``0.0`` for an empty series.
        """
        return float(
            sum(
                flow.amount
                for flow in self.flows
                if include_valuations or not flow.is_valuation
            )
        )


# ─────────────────────────────────────────────────────────────────────────
# FX translation: turn several single-currency flows into one pre_translated
# series, using each flow's OWN settlement-date rate (never a period-end
# rate -- see ``translate_cashflows``).
# ─────────────────────────────────────────────────────────────────────────


class MissingExchangeRateError(ValueError):
    """Raised when a cash flow's settlement date has no usable exchange rate.

    Forward-filling silently across a rate gap is exactly the failure mode
    this module refuses by default: a large flow that happens to land inside
    the gap would be translated with the wrong rate, and nothing downstream
    could tell. The explicit, opt-in alternative is
    ``FxRateTable.get_rate(..., allow_stale=True)``.
    """


@dataclass(frozen=True)
class FxRate:
    """One exchange-rate quote, in the standard FX BASE/QUOTE convention.

    Naming both currencies explicitly -- instead of accepting a bare
    ``rate`` float and a docstring nobody reads -- is the defense against the
    single most common bug in FX-translation code: silently applying the
    reciprocal rate. ``EURUSD = 1.08`` means ``base_currency="EUR"``,
    ``quote_currency="USD"``, ``rate=1.08``: 1 EUR converts to 1.08 USD,
    never the other way around.

    Attributes:
        base_currency: The currency being priced -- in a translation, the
            cash flow's own currency. Normalized to uppercase.
        quote_currency: The currency the rate is expressed in -- in a
            translation, the reporting currency. Normalized to uppercase.
        date: The date this quote applies to.
        rate: Units of ``quote_currency`` per 1 unit of ``base_currency``, so
            ``amount_in_quote = amount_in_base * rate``. Must be finite and
            strictly positive: a zero or negative rate would silently zero
            out, or flip the sign of, every flow translated with it.
    """

    base_currency: str
    quote_currency: str
    date: date
    rate: float

    def __post_init__(self) -> None:
        """Normalize the currencies and date, and validate the rate.

        Raises:
            ValueError: If either currency code is invalid, the date is
                unsupported, or the rate is not finite and strictly positive.
        """
        object.__setattr__(
            self,
            "base_currency",
            normalize_currency(self.base_currency, field_name="base_currency"),
        )
        object.__setattr__(
            self,
            "quote_currency",
            normalize_currency(self.quote_currency, field_name="quote_currency"),
        )
        object.__setattr__(self, "date", normalize_date(self.date))
        try:
            rate = float(self.rate)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"rate must be numeric, got {self.rate!r}") from exc
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError(
                f"rate must be finite and strictly positive -- it is "
                f"quote-per-base units -- got {rate!r}; a zero or negative "
                "rate would silently zero out or flip the sign of every flow "
                "translated with it"
            )
        object.__setattr__(self, "rate", rate)


@dataclass(frozen=True)
class FxRateTable:
    """A lookup of FX rates, every entry quoted against one fixed currency.

    All entries must share the same ``quote_currency``: a table that mixed
    quote currencies would make "translate to X" ambiguous, so that is
    rejected at construction rather than left to whichever rate happens to be
    looked up first.

    Attributes:
        quote_currency: The single reporting currency every rate quotes
            against. Normalized to uppercase.
        rates: Mapping of ``(base_currency, date) -> FxRate``, keyed by the
            already-normalized currency code and date.
    """

    quote_currency: str
    rates: Mapping[tuple[str, date], FxRate] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the quote currency and every entry's consistency.

        Raises:
            ValueError: If ``quote_currency`` is invalid, a value is not an
                ``FxRate``, an entry quotes against a different currency than
                the table's, or an entry is stored under a key that does not
                match its own ``(base_currency, date)``.
        """
        quote = normalize_currency(self.quote_currency, field_name="quote_currency")
        rates = dict(self.rates)
        for key, entry in rates.items():
            if not isinstance(entry, FxRate):
                raise ValueError(
                    f"FxRateTable entries must be FxRate, got {type(entry).__name__}"
                )
            if entry.quote_currency != quote:
                raise ValueError(
                    f"FxRate {entry.base_currency}/{entry.quote_currency}@"
                    f"{entry.date} does not quote against this table's "
                    f"currency {quote!r}; a table may only hold rates quoted "
                    "against one reporting currency"
                )
            expected_key = (entry.base_currency, entry.date)
            if key != expected_key:
                raise ValueError(
                    f"FxRate stored under key {key!r} does not match its own "
                    f"(base_currency, date) = {expected_key!r}"
                )
        object.__setattr__(self, "quote_currency", quote)
        object.__setattr__(self, "rates", MappingProxyType(rates))

    @classmethod
    def from_rates(cls, rates: Iterable[FxRate], *, quote_currency: str) -> "FxRateTable":
        """Build a table from a sequence of individual quotes.

        Args:
            rates: The quotes, all against ``quote_currency``.
            quote_currency: The reporting currency of the table.

        Returns:
            A new ``FxRateTable`` keyed by ``(base_currency, date)``.

        Raises:
            ValueError: If a member is not an ``FxRate``, two quotes collide
                on the same ``(base_currency, date)`` with different rates,
                or a quote's ``quote_currency`` disagrees with the table's.
        """
        indexed: dict[tuple[str, date], FxRate] = {}
        for entry in rates:
            if not isinstance(entry, FxRate):
                raise ValueError(f"rates must contain FxRate, got {type(entry).__name__}")
            key = (entry.base_currency, entry.date)
            if key in indexed and indexed[key].rate != entry.rate:
                raise ValueError(
                    f"conflicting rates for {key}: {indexed[key].rate!r} vs "
                    f"{entry.rate!r}"
                )
            indexed[key] = entry
        return cls(quote_currency=quote_currency, rates=indexed)

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[tuple[str, "date | datetime | str"], float],
        *,
        quote_currency: str,
    ) -> "FxRateTable":
        """Build a table from ``{(base_currency, date): rate}`` pairs.

        Args:
            mapping: Each value is units of ``quote_currency`` per 1 unit of
                the key's currency, exactly as ``FxRate.rate`` defines it.
            quote_currency: The reporting currency of the table.

        Returns:
            A new ``FxRateTable``.

        Raises:
            ValueError: If a currency code or date in a key is invalid, or a
                rate is not finite and strictly positive.
        """
        rows = [
            FxRate(base_currency=base, quote_currency=quote_currency, date=day, rate=rate)
            for (base, day), rate in mapping.items()
        ]
        return cls.from_rates(rows, quote_currency=quote_currency)

    def get_rate(
        self,
        base_currency: str,
        on_date: date,
        *,
        allow_stale: bool = False,
        max_staleness_days: int | None = None,
    ) -> tuple[FxRate, bool]:
        """Look up the rate to translate ``base_currency`` on ``on_date``.

        Only a same-day or an earlier quote is ever used: translating a flow
        with a rate quoted *after* it settled would leak future information
        into the past, which is worse than an outright missing rate.

        Args:
            base_currency: Currency being priced.
            on_date: The flow's own settlement date -- never a series end
                date. Applying one period-end rate to every flow is the
                classic mistake this table exists to prevent.
            allow_stale: When ``on_date`` has no exact quote, search backward
                for the most recent earlier one instead of raising. Off by
                default: reusing a stale rate without being asked is the
                silent forward-fill-through-a-gap failure mode this module
                refuses by default.
            max_staleness_days: With ``allow_stale=True``, how many days
                before ``on_date`` a reused quote may be. ``None`` means an
                unbounded backward search.

        Returns:
            A tuple of the ``FxRate`` used and whether it was stale (its
            ``date`` is earlier than ``on_date``).

        Raises:
            MissingExchangeRateError: If there is no exact same-day quote and
                either ``allow_stale`` is False, or no earlier quote exists
                (within ``max_staleness_days`` when given).
        """
        base = normalize_currency(base_currency, field_name="base_currency")
        day = normalize_date(on_date)

        exact = self.rates.get((base, day))
        if exact is not None:
            return exact, False

        if not allow_stale:
            raise MissingExchangeRateError(
                f"no {base}/{self.quote_currency} rate for {day}; pass "
                "allow_stale=True to reuse the most recent earlier rate "
                "instead -- stale reuse is flagged on the translated flow, "
                "never applied silently"
            )

        candidates = [
            entry
            for (entry_base, entry_date), entry in self.rates.items()
            if entry_base == base and entry_date <= day
        ]
        if max_staleness_days is not None:
            candidates = [
                entry
                for entry in candidates
                if (day - entry.date).days <= max_staleness_days
            ]
        if not candidates:
            bound = (
                f" within {max_staleness_days} days" if max_staleness_days is not None else ""
            )
            raise MissingExchangeRateError(
                f"no {base}/{self.quote_currency} rate on or before {day}{bound}"
            )
        best = max(candidates, key=lambda entry: entry.date)
        return best, True


def translate_cashflows(
    flows: CashFlowSeries | Iterable[CashFlow],
    rate_table: FxRateTable,
    *,
    allow_stale_rates: bool = False,
    max_staleness_days: int | None = None,
) -> CashFlowSeries:
    """Convert flows in one or more currencies into ``rate_table``'s currency.

    Each flow is converted using the FX rate quoted on **that flow's own
    settlement date** -- never a single series-level or period-end rate.
    Applying one end-of-period rate to every flow is the most common
    real-world FX-translation bug: it looks correct on the aggregate total
    while silently mispricing every individual flow that did not happen to
    settle on that date.

    Translation is a lossy operation -- once flows are summed, the
    original-currency detail cannot be recovered from the total alone -- so
    every translated flow keeps its original amount, currency, and the exact
    rate and rate date used, recorded in
    ``metadata["fx_original_amount"]``, ``metadata["fx_original_currency"]``,
    ``metadata["fx_rate"]``, ``metadata["fx_rate_date"]``, and
    ``metadata["fx_rate_is_stale"]``.

    Args:
        flows: The source flows, in any mix of currencies.
        rate_table: Rates to translate with; see ``FxRateTable``. Its
            ``quote_currency`` becomes the returned series' currency.
        allow_stale_rates: Forwarded to ``FxRateTable.get_rate``. Off by
            default, so a settlement date with no exact quote raises rather
            than silently reusing an older one.
        max_staleness_days: Forwarded to ``FxRateTable.get_rate``.

    Returns:
        A ``CashFlowSeries`` with ``pre_translated=True`` and
        ``currency=rate_table.quote_currency``.

    Raises:
        MissingExchangeRateError: If a flow's currency has no usable rate for
            its settlement date; see ``allow_stale_rates``.
        ValueError: If ``flows`` contains a member that is not a ``CashFlow``.
    """
    translated: list[CashFlow] = []
    for flow in flows:
        if not isinstance(flow, CashFlow):
            raise ValueError(f"flows must contain CashFlow, got {type(flow).__name__}")

        if flow.currency == rate_table.quote_currency:
            converted_amount = flow.amount
            rate_used = 1.0
            rate_date = flow.date
            is_stale = False
        else:
            fx_rate, is_stale = rate_table.get_rate(
                flow.currency,
                flow.date,
                allow_stale=allow_stale_rates,
                max_staleness_days=max_staleness_days,
            )
            converted_amount = flow.amount * fx_rate.rate
            rate_used = fx_rate.rate
            rate_date = fx_rate.date

        metadata = dict(flow.metadata)
        metadata["fx_original_amount"] = flow.amount
        metadata["fx_original_currency"] = flow.currency
        metadata["fx_rate"] = rate_used
        metadata["fx_rate_date"] = rate_date
        metadata["fx_rate_is_stale"] = is_stale

        translated.append(
            CashFlow(
                date=flow.date,
                amount=converted_amount,
                kind=flow.kind,
                currency=rate_table.quote_currency,
                metadata=metadata,
            )
        )

    return CashFlowSeries(
        flows=tuple(translated),
        currency=rate_table.quote_currency,
        pre_translated=True,
    )
