"""Argentina equity (BYMA) backtest engine: local shares and CEDEARs (``.BA``).

Market rules modelled:
  - Long only, no leverage. One ARS cash pool (USD ``D`` lines are rejected by
    the loaders' ARS contract).
  - Yahoo emits flat zero-volume bars on exchange holidays; a date on which no
    loaded instrument traded is dropped, and a zero-volume bar is never a fill.
  - Normal settlement ("contado normal") is T+2 for trades before 2024-05-27
    and T+1 from that date. It is counted in **observed trading sessions**: the
    bars of the run on which at least one loaded instrument traded. Days with
    no trades in the loaded data (holidays) never count. This approximates the
    official calendar; settlement dates are not official dates, and a
    settlement that falls after the last loaded bar is reported as
    ``beyond_loaded_data`` rather than guessed.
  - A sale funds a purchase settling on the same or a later session (a same-bar
    sale always does: BaseEngine's default netting); proceeds that settle
    later are not available, so money is never used twice.
  - Normal settlement is not a holding-period restriction: acquired shares
    may be resold before settlement. CEDEAR credit-date restrictions still
    bind both signal exits and terminal liquidation.
  - CEDEAR ratio changes are not adjusted by Yahoo (AAPL.BA halves on
    2024-01-24, ratio 10:1 -> 20:1, while the holder's position doubles). Each
    declared change inside the window is checked against the observed price
    step and earlier bars are restated in post-change units, exactly as a
    split adjustment would; an ambiguous step, or a large one-bar move with no
    declared change, fails closed; before the change one real certificate is ``new/old``
    units, which sets the lot and the tick. A position held through the
    ex-date is sold only by a trade whose earliest possible settlement (counted
    on weekdays) reaches the declared ``credit_date`` of the extra certificates.
  - Ticks: a declared Circular 3569 table version/panel, or a fixed tick
    (rounded against the trader). No panel membership or effective date is
    inferred. Lots:
    one share unless declared (an assumption; the circular sets no number).

Costs are simulation inputs, never official tariffs: ``ar_brokerage_rate``
(defaults to the generic ``commission``), ``ar_exchange_fee_rate``,
``ar_fixed_fee`` per order and ``ar_slippage`` (all default 0).

Config ``ar_instruments`` (optional) declares metadata per symbol::

    {"YPFD.BA": {"kind": "share"},
     "AAPL.BA": {"kind": "cedear", "underlying": "AAPL",
                 "ratio_history": [{"effective_date": "2010-06-24", "ratio": "10"},
                                   {"effective_date": "2024-01-24", "ratio": "20",
                                    "credit_date": "2024-01-26"}]}}

Declare ``ar_tick_table`` as ``2024-07-04``, ``2025-09-08-leader`` or
``2025-09-08-general`` (or an instrument-specific ``tick_table`` / ``tick_size``).
Select the table and panel applicable to the simulated window; split a window
when its rule changes. Local shares need no kind entry (Yahoo descriptor);
CEDEARs must be declared. Every resolved value is labelled in the
``ar_data_basis`` metric and ``artifacts/byma_preparation.json``.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import pandas as pd

from backtest.engines.base import BaseEngine

# ── price basis and instrument metadata ──

PRICE_COLUMNS = ("open", "high", "low", "close")

# One-bar moves larger than these, with no declared ratio change, are treated as
# unit discontinuities rather than market moves. Shares get a wider band: BYMA
# sessions have moved ~47% (2019-08-12) while an unadjusted 4:1 split moves 75%.
DEFAULT_MAX_CEDEAR_MOVE = 0.4
DEFAULT_MAX_SHARE_MOVE = 0.75
# How far an observed ratio step may sit from the expected factor.
DEFAULT_RATIO_TOLERANCE = 0.2

# BYMA Circular 3569, "Reglas de Negocio en el Segmento PPT Operaciones de
# Contado", annex version 2024-07-04: minimum price change for equities
# (CEDEARs included) by price band.
TICK_SOURCE = "BYMA Circular 3569 annex v2024-07-04"
_TICK_BANDS: Tuple[Tuple[Decimal, Decimal], ...] = (
    (Decimal("1"), Decimal("0.001")),
    (Decimal("5"), Decimal("0.005")),
    (Decimal("10"), Decimal("0.01")),
    (Decimal("50"), Decimal("0.05")),
    (Decimal("100"), Decimal("0.10")),
    (Decimal("250"), Decimal("0.25")),
    (Decimal("500"), Decimal("0.50")),
    (Decimal("1000"), Decimal("1.00")),
    (Decimal("5000"), Decimal("5.00")),
    (Decimal("10000"), Decimal("10.00")),
    (Decimal("50000"), Decimal("25.00")),
)
_TICK_ABOVE = Decimal("50.00")
_TICK_TABLES = {
    "2024-07-04": (_TICK_BANDS, _TICK_ABOVE),
    "2025-09-08-leader": (
        tuple(
            (Decimal(p), Decimal(t))
            for p, t in (
                ("1", ".001"),
                ("5", ".005"),
                ("50", ".01"),
                ("100", ".10"),
                ("500", ".25"),
                ("1000", ".50"),
                ("2500", "1"),
                ("5000", "2.5"),
                ("10000", "5"),
                ("25000", "10"),
                ("50000", "20"),
            )
        ),
        Decimal("25"),
    ),
    "2025-09-08-general": (
        tuple(
            (Decimal(p), Decimal(t))
            for p, t in (
                ("1", ".001"),
                ("5", ".005"),
                ("10", ".01"),
                ("25", ".05"),
                ("50", ".10"),
                ("100", ".20"),
                ("400", ".50"),
                ("800", "1"),
                ("1000", "2.5"),
                ("5000", "5"),
                ("10000", "10"),
                ("25000", "25"),
            )
        ),
        Decimal("50"),
    ),
}

# Yahoo truncates shortName at 31 characters, which can cut a "CEDEAR" marker.
_SHORT_NAME_LIMIT = 31
_CEDEAR_MARKER = re.compile(r"\bCEDEARS?\b", re.I)
_TRUNCATED_MARKER = re.compile(r"\bC(E(D(E(A(R)?)?)?)?)?$", re.I)


def equity_tick(price: Decimal, table: str = "2024-07-04") -> Decimal:
    """Minimum price change at *price* under an explicitly selected table."""
    bands, above = _TICK_TABLES[table]
    for upper, tick in bands:
        if price <= upper:
            return tick
    return above


def classify_short_name(short_name: Optional[str]) -> Tuple[Optional[str], str]:
    """``("share" | "cedear" | None, evidence)`` from Yahoo's shortName."""
    name = (short_name or "").strip()
    if not name:
        return None, "no Yahoo descriptor"
    if _CEDEAR_MARKER.search(name):
        return "cedear", f"Yahoo shortName {name!r} names a CEDEAR"
    if len(name) >= _SHORT_NAME_LIMIT or _TRUNCATED_MARKER.search(name):
        return None, f"Yahoo shortName {name!r} may be truncated"
    return "share", f"Yahoo shortName {name!r} has no CEDEAR marker"


def yahoo_short_name(symbol: str) -> Optional[str]:
    """Yahoo's shortName through the existing quote-summary client, or None."""
    from backtest.loaders import yahoo_client

    try:
        summary = yahoo_client.get_quote_summary(symbol, ["quoteType"])
    except Exception:  # noqa: BLE001 - an unreachable descriptor is "unknown"
        return None
    quote = summary.get("quoteType") if isinstance(summary, dict) else None
    name = quote.get("shortName") if isinstance(quote, dict) else None
    return name if isinstance(name, str) else None


def resolve_instrument(
    symbol: str,
    declared: Optional[Mapping[str, Any]],
    describe: Callable[[str], Optional[str]],
) -> Tuple[dict, Dict[str, str], List[str]]:
    """Complete one instrument: ``(metadata, provenance, problems)``.

    Declared fields win. A missing ``kind`` is taken from Yahoo only when it
    names a local share; a CEDEAR needs its declared ratio history.
    """
    info = dict(declared or {})
    provenance = {key: "declared" for key in info}
    problems: List[str] = []
    if "kind" not in info:
        kind, evidence = classify_short_name(describe(symbol))
        if kind == "share":
            info["kind"] = "share"
            provenance["kind"] = f"vendor ({evidence})"
        elif kind == "cedear":
            problems.append(
                f"{symbol}: {evidence}; declare ar_instruments.{symbol} with "
                "kind='cedear', underlying and ratio_history [{effective_date, ratio, "
                "credit_date for changes inside the backtest}]"
            )
        else:
            problems.append(
                f"{symbol}: {evidence}; declare ar_instruments.{symbol}.kind "
                "as 'share' or 'cedear'"
            )
    info.setdefault("lot_size", 1)
    provenance.setdefault("lot_size", "assumption (one share per order)")
    provenance.setdefault(
        "tick_size",
        (
            f"declared table {info.get('tick_table')}"
            if info.get("tick_size") is None
            else "declared"
        ),
    )
    provenance["currency"] = (
        "ARS (.BA pool, checked against the loader's declared currency)"
    )
    return info, provenance, problems


def validate_frame(frame: pd.DataFrame, symbol: str) -> None:
    """Require OHLCV columns and an ARS quote the loader declared."""
    missing = [c for c in (*PRICE_COLUMNS, "volume") if c not in frame.columns]
    if missing:
        raise ValueError(f"{symbol}: BYMA bars need columns {missing}")
    declared = frame.attrs.get("quote_currency")
    if declared != "ARS":
        raise ValueError(
            f"{symbol}: BYMA backtests book in ARS but the source declared "
            f"{declared or 'no quote currency'}"
        )
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise ValueError(f"{symbol}: BYMA bars need a unique DatetimeIndex")


def traded_dates(frames: Iterable[pd.DataFrame]) -> set:
    """Dates on which at least one loaded instrument traded (volume > 0)."""
    dates: set = set()
    for frame in frames:
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        dates.update(ts.normalize() for ts, v in volume.items() if v > 0)
    return dates


def _traded(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[pd.to_numeric(frame["volume"], errors="coerce") > 0]


def _near(observed: float, target: float, tolerance: float) -> bool:
    return abs(math.log(observed / target)) <= math.log1p(tolerance)


def reconcile_ratio_changes(
    frame: pd.DataFrame,
    symbol: str,
    ratio_history: Iterable[Mapping[str, Any]],
    *,
    tolerance: float = DEFAULT_RATIO_TOLERANCE,
) -> Tuple[pd.DataFrame, List[dict]]:
    """Put every in-window CEDEAR ratio change on one adjusted unit basis.

    A change from ``old`` to ``new`` CEDEARs per underlying share moves an
    unadjusted series by ``old/new`` across the effective date and an adjusted
    one by ~1. The close-to-close move between the last traded bar before and
    the first traded bar on/after the date must match exactly one of them
    (and the entry's optional ``price_series`` declaration). Unadjusted
    evidence rescales earlier OHLC by ``old/new`` and volume by the inverse.
    """
    entries = list(ratio_history)
    events: List[dict] = []
    if frame.empty or len(entries) < 2:
        return frame, events
    first, last = frame.index[0].date(), frame.index[-1].date()
    adjusted = frame.copy()
    traded = _traded(frame)
    for previous, entry in zip(entries, entries[1:]):
        effective = date.fromisoformat(str(entry["effective_date"]))
        if not first < effective <= last:
            continue
        old, new = float(previous["ratio"]), float(entry["ratio"])
        factor = old / new
        before = traded[traded.index.date < effective]
        after = traded[traded.index.date >= effective]
        if before.empty or after.empty:
            raise ValueError(
                f"{symbol}: ratio change on {effective} cannot be verified; "
                "no traded bar on both sides of it"
            )
        observed = float(after["close"].iloc[0]) / float(before["close"].iloc[-1])
        unadjusted, already = _near(observed, factor, tolerance), _near(
            observed, 1.0, tolerance
        )
        declared = entry.get("price_series")
        if declared == "unadjusted":
            ok = unadjusted and not already
        elif declared == "adjusted":
            ok = already and not unadjusted
        else:
            ok = unadjusted != already
        if not ok:
            raise ValueError(
                f"{symbol}: ratio change {old:g}->{new:g} on {effective} is not provable "
                f"from prices (observed move x{observed:.3f}; unadjusted would be "
                f"x{factor:.3f}, adjusted ~x1)"
            )
        if unadjusted:
            earlier = adjusted.index.date < effective
            for column in PRICE_COLUMNS:
                adjusted.loc[earlier, column] = adjusted.loc[earlier, column] * factor
            adjusted.loc[earlier, "volume"] = adjusted.loc[earlier, "volume"] / factor
        events.append(
            {
                "symbol": symbol,
                "effective_date": str(effective),
                "credit_date": (
                    str(entry["credit_date"]) if entry.get("credit_date") else None
                ),
                "old_ratio": old,
                "new_ratio": new,
                "observed_move": round(observed, 6),
                "rescaled_prior_bars": unadjusted,
            }
        )
    return adjusted, events


def discontinuities(frame: pd.DataFrame, max_move: float) -> List[str]:
    """Dates where consecutive traded closes move by more than *max_move*."""
    closes = _traded(frame)["close"].astype(float)
    if len(closes) < 2:
        return []
    moves = closes / closes.shift(1)
    limit = math.log(1.0 / (1.0 - max_move))
    return [
        str(ts.date())
        for ts, move in moves.iloc[1:].items()
        if abs(math.log(move)) > limit
    ]


# ── settlement ──

#: First trade date of T+1 normal settlement on BYMA (T+2 before).
T1_FROM = date(2024, 5, 27)
_OPENING = ("open", "increase")
_SALES = ("reduce", "close")


def normal_cash_lag(trade_date: date) -> int:
    """Settlement lag in sessions for a normal-cash trade on *trade_date*."""
    return 1 if trade_date >= T1_FROM else 2


def _day(value: Any) -> Optional[date]:
    if type(value) is date:
        return value
    if isinstance(value, (datetime, pd.Timestamp)) and not pd.isna(value):
        return value.date()
    return None


def _add_weekdays(day: date, count: int) -> date:
    while count > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def _settlement_bar(fill: Any) -> int:
    return int(fill.bar_idx) + normal_cash_lag(_day(fill.timestamp))


def _net_proceeds(fill: Any) -> float:
    return abs(float(fill.signed_quantity)) * float(fill.execution_price) - float(
        fill.fee
    )


class ArgentinaEquityEngine(BaseEngine):
    """BYMA cash-equity engine (shares and CEDEARs); see the module docstring."""

    def __init__(self, config: dict):
        if config.get("leverage", 1.0) != 1.0:
            raise ValueError("ArgentinaEquityEngine is cash-only; leverage must be 1")
        config = {**config, "leverage": 1.0}  # cash equity: no leverage
        super().__init__(config)
        if config.get("allow_short"):
            raise ValueError(
                "ArgentinaEquityEngine is long-only; remove 'allow_short'."
            )
        declared = config.get("ar_instruments") or {}
        if not isinstance(declared, dict):
            raise ValueError("ar_instruments must be an object keyed by .BA symbol")
        problems: List[str] = []
        self._declared: Dict[str, dict] = {}
        for symbol, info in declared.items():
            if not isinstance(info, dict):
                problems.append(f"{symbol}: metadata must be an object")
                continue
            problems.extend(_field_problems(symbol, info))
            self._declared[symbol.upper()] = dict(info)
        if problems:
            raise ValueError(_config_error(problems))
        self.instruments: Dict[str, dict] = {}
        self.provenance: Dict[str, dict] = {}
        self.tick_table = config.get("ar_tick_table")
        if self.tick_table is not None and self.tick_table not in _TICK_TABLES:
            raise ValueError(f"ar_tick_table must be one of {tuple(_TICK_TABLES)}")
        self.ratio_adjustments: List[dict] = []
        self.dropped_no_trade_dates: List[str] = []
        self.slippage_rate = _rate(config.get("ar_slippage", 0.0), "ar_slippage")
        if "ar_brokerage_rate" in config:
            self.brokerage_rate, source = (
                _rate(config["ar_brokerage_rate"], "ar_brokerage_rate"),
                "ar_brokerage_rate",
            )
        elif config.get("commission") is not None:
            self.brokerage_rate, source = (
                _rate(config["commission"], "commission"),
                "commission",
            )
        else:
            self.brokerage_rate, source = 0.0, "none configured"
        self.exchange_fee_rate = _rate(
            config.get("ar_exchange_fee_rate", 0.0), "ar_exchange_fee_rate"
        )
        self.fixed_fee = _rate(config.get("ar_fixed_fee", 0.0), "ar_fixed_fee")
        self.fee_basis = {
            "brokerage_rate": self.brokerage_rate,
            "brokerage_source": source,
            "exchange_fee_rate": self.exchange_fee_rate,
            "fixed_fee": self.fixed_fee,
            "slippage": self.slippage_rate,
            "note": "simulation inputs, not an official BYMA or broker tariff",
        }
        self.max_cedear_move = float(
            config.get("ar_max_cedear_move", DEFAULT_MAX_CEDEAR_MOVE)
        )
        self.max_share_move = float(
            config.get("ar_max_share_move", DEFAULT_MAX_SHARE_MOVE)
        )
        for name, value in (
            ("ar_max_cedear_move", self.max_cedear_move),
            ("ar_max_share_move", self.max_share_move),
        ):
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")

    # ── metadata and data ──

    @staticmethod
    def describe_instrument(symbol: str) -> Optional[str]:
        """Vendor descriptor used to tell a local share from a CEDEAR."""
        return yahoo_short_name(symbol)

    def _instrument(self, symbol: str) -> dict:
        try:
            return self.instruments[symbol.upper()]
        except KeyError:
            raise ValueError(f"{symbol}: unregistered BYMA instrument") from None

    def prepare_market_data(
        self, data_map: Dict[str, pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        """Resolve metadata, keep traded sessions, put CEDEAR prices on one unit basis."""
        problems: List[str] = []
        for symbol in data_map:
            if not symbol.upper().endswith(".BA"):
                problems.append(f"{symbol}: expected a .BA listing")
                continue
            info, provenance, gaps = resolve_instrument(
                symbol,
                {
                    **({"tick_table": self.tick_table} if self.tick_table else {}),
                    **self._declared.get(symbol.upper(), {}),
                },
                self.describe_instrument,
            )
            gaps = gaps or _field_problems(symbol, info, require=True)
            problems.extend(gaps)
            if not gaps:
                tick = info.get("tick_size")
                self.instruments[symbol.upper()] = {
                    **info,
                    "tick_size": None if tick is None else Decimal(str(tick)),
                }
                self.provenance[symbol.upper()] = provenance
        if problems:
            raise ValueError(_config_error(problems))
        for symbol, frame in data_map.items():
            validate_frame(frame, symbol)
        sessions = traded_dates(data_map.values())
        prepared: Dict[str, pd.DataFrame] = {}
        dropped: set = set()
        self.ratio_adjustments = []
        for symbol, frame in data_map.items():
            attrs = dict(frame.attrs)
            keep = frame.index.normalize().isin(sessions)
            dropped.update(str(ts.date()) for ts in frame.index[~keep])
            frame = frame[keep]
            info = self._instrument(symbol)
            if info["kind"] == "cedear":
                frame, events = reconcile_ratio_changes(
                    frame,
                    symbol,
                    info["ratio_history"],
                    tolerance=DEFAULT_RATIO_TOLERANCE,
                )
                missing = [e["effective_date"] for e in events if not e["credit_date"]]
                if missing:
                    raise ValueError(
                        f"{symbol}: ratio change(s) on {', '.join(missing)} need the depositary "
                        "credit_date of the additional certificates"
                    )
                self.ratio_adjustments.extend(events)
            limit = (
                self.max_cedear_move
                if info["kind"] == "cedear"
                else self.max_share_move
            )
            jumps = discontinuities(frame, limit)
            if jumps:
                raise ValueError(
                    f"{symbol}: unexplained price discontinuities on {', '.join(jumps[:5])}; "
                    + (
                        "declare the CEDEAR ratio change in ratio_history"
                        if info["kind"] == "cedear"
                        else "use a split-adjusted source"
                    )
                    + " or exclude the window"
                )
            frame.attrs.update(attrs)
            prepared[symbol] = frame
        self.dropped_no_trade_dates = sorted(dropped)
        return prepared

    # ── market rules ──

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        return argentina_can_execute(self, self, symbol, direction, bar)

    def available_cash(self, timestamp: pd.Timestamp) -> float:
        return argentina_available_cash(self, self, timestamp)

    def can_liquidate_at_end(self, symbol: str, timestamp: pd.Timestamp) -> bool:
        return argentina_sell_allowed(self, self, symbol, timestamp)

    def unit_scale(self, symbol: str, timestamp: Any) -> Decimal:
        """Adjusted units per real certificate on *timestamp* (``new/old`` before a change)."""
        today = _day(timestamp)
        scale = Decimal(1)
        if today is None:
            return scale
        for event in self.ratio_adjustments:
            if (
                event["symbol"].upper() == symbol.upper()
                and date.fromisoformat(event["effective_date"]) > today
            ):
                scale *= Decimal(str(event["new_ratio"])) / Decimal(
                    str(event["old_ratio"])
                )
        return scale

    def round_size(self, raw_size: float, price: float) -> float:
        """Whole real lots: before a ratio change one lot spans ``new/old`` units."""
        info = self._instrument(self._active_symbol)
        if not math.isfinite(raw_size) or raw_size <= 0:
            return 0.0
        lot = Decimal(info["lot_size"]) * self.unit_scale(
            self._active_symbol, self._bar_ts
        )
        return float(
            (Decimal(repr(raw_size)) / lot).to_integral_value(rounding=ROUND_FLOOR)
            * lot
        )

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool
    ) -> float:
        notional = size * price
        if not math.isfinite(notional) or notional <= 0:
            return 0.0
        return (
            notional * (self.brokerage_rate + self.exchange_fee_rate) + self.fixed_fee
        )

    def apply_slippage(self, price: float, direction: int) -> float:
        """Slip against the trader, then snap to the BYMA tick of the real price."""
        info = self._instrument(self._active_symbol)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("BYMA execution price must be positive and finite")
        side = 1 if direction == 1 else -1
        slipped = Decimal(str(price)) * (
            Decimal(1) + side * Decimal(str(self.slippage_rate))
        )
        scale = self.unit_scale(self._active_symbol, self._bar_ts)
        tick = (
            info["tick_size"] or equity_tick(slipped * scale, info["tick_table"])
        ) / scale
        rounding = ROUND_CEILING if side > 0 else ROUND_FLOOR
        return float((slipped / tick).to_integral_value(rounding=rounding) * tick)

    # ── reporting ──

    def _engine_diagnostics(self) -> Dict[str, Any]:
        return argentina_diagnostics(self, self)

    def _write_artifacts(self, run_dir, *args, **kwargs) -> None:
        super()._write_artifacts(run_dir, *args, **kwargs)
        write_byma_artifacts(run_dir, self, self)


# ── state/rules helpers (shared with CompositeEngine, like hose_can_execute) ──


def argentina_sell_allowed(
    state: BaseEngine, rules: ArgentinaEquityEngine, symbol: str, timestamp: Any
) -> bool:
    """Acquired shares may be resold; additional certificates must be credited."""
    today = _day(timestamp)
    if today is None or symbol not in state.positions:
        return False
    openings = []
    for fill in reversed(getattr(state, "fill_records", ()) or ()):
        if fill.symbol != symbol:
            continue
        if fill.action == "close":
            break
        if fill.action in _OPENING:
            openings.append(fill)
    if not openings:
        return False
    first_open = min(_day(f.timestamp) for f in openings)
    earliest = _add_weekdays(today, normal_cash_lag(today))
    for event in rules.ratio_adjustments:
        if event["symbol"].upper() != symbol.upper() or not event["credit_date"]:
            continue
        ex = date.fromisoformat(event["effective_date"])
        if first_open < ex <= today and earliest < date.fromisoformat(
            event["credit_date"]
        ):
            return False
    return True


def argentina_available_cash(
    state: BaseEngine, rules: ArgentinaEquityEngine, timestamp: Any
) -> float:
    """Cash for a purchase now: capital less sales settling after its session."""
    today = _day(timestamp)
    if today is None:
        raise ValueError("BYMA buying power requires a session timestamp")
    due = int(state._bar_idx) + normal_cash_lag(today)
    later = sum(
        _net_proceeds(f)
        for f in state.fill_records
        if f.action in _SALES and _settlement_bar(f) > due
    )
    return state.capital - later


def argentina_can_execute(
    state: BaseEngine,
    rules: ArgentinaEquityEngine,
    symbol: str,
    direction: int,
    bar: pd.Series,
) -> bool:
    """Long only, a traded bar, and CEDEAR credit protection for a sale."""
    rules._instrument(symbol)
    if direction not in (0, 1):
        return False
    try:
        price, volume = float(bar.get("close")), float(bar.get("volume"))
    except (TypeError, ValueError):
        return False
    if not (
        math.isfinite(price) and price > 0 and math.isfinite(volume) and volume > 0
    ):
        return False  # a zero-volume bar is a stale print, not an executable price
    return direction == 1 or argentina_sell_allowed(state, rules, symbol, bar.name)


def byma_cash_ledger(state: BaseEngine) -> List[dict]:
    """Per-fill cash reconciliation replayed from the engine's own fills."""
    dates = [snap.timestamp for snap in state.equity_snapshots]
    cash = float(state.initial_capital)
    rows: List[dict] = []
    for index, fill in enumerate(state.fill_records):
        qty = float(fill.signed_quantity)
        notional = abs(qty) * float(fill.execution_price)
        fee = float(fill.fee)
        due = _settlement_bar(fill)
        buying_power = None
        if qty > 0:
            later = sum(
                _net_proceeds(f)
                for f in state.fill_records[:index]
                if f.action in _SALES and _settlement_bar(f) > due
            )
            buying_power = cash - later
        cash += -(notional + fee) if qty > 0 else notional - fee
        unsettled = sum(
            _net_proceeds(f)
            for f in state.fill_records[: index + 1]
            if f.action in _SALES and _settlement_bar(f) > int(fill.bar_idx)
        )
        within = due < len(dates)
        rows.append(
            {
                "timestamp": str(_day(fill.timestamp)),
                "code": fill.symbol,
                "side": "buy" if qty > 0 else "sell",
                "qty": abs(qty),
                "notional": round(notional, 6),
                "fee": round(fee, 6),
                "total_cost": round(notional + fee, 6) if qty > 0 else "",
                "net_proceeds": round(notional - fee, 6) if qty < 0 else "",
                "cash_flow": round(-(notional + fee) if qty > 0 else notional - fee, 6),
                "cash_after": round(cash, 6),
                "settlement_date": str(_day(dates[due])) if within else "",
                "settlement_basis": (
                    "observed_sessions" if within else "beyond_loaded_data"
                ),
                "buying_power_before": (
                    "" if buying_power is None else round(buying_power, 6)
                ),
                "unsettled_sale_proceeds_after": round(unsettled, 6),
            }
        )
    return rows


def argentina_diagnostics(
    state: BaseEngine, rules: ArgentinaEquityEngine
) -> Dict[str, Any]:
    """Run facts: what the figures rest on and what terminal equity contains."""
    if not state.equity_snapshots:
        return {}
    last_bar = len(state.equity_snapshots) - 1
    fills = state.fill_records
    retained = state.unliquidated_positions
    parts = []
    for symbol, info in sorted(rules.instruments.items()):
        prov = rules.provenance.get(symbol, {})
        tick = (
            f"declared table {info['tick_table']}"
            if info["tick_size"] is None
            else str(info["tick_size"])
        )
        parts.append(
            f"{symbol}: kind={info['kind']} [{prov.get('kind', 'declared')}], "
            f"lot={info['lot_size']} [{prov.get('lot_size')}], tick={tick}"
        )
    parts.append(
        "settlement: T+2 (T+1 from 2024-05-27) counted in observed trading sessions "
        "[approximation, not an official calendar]"
    )
    fee = rules.fee_basis
    parts.append(
        f"costs: brokerage {fee['brokerage_rate']:.4%} ({fee['brokerage_source']}), "
        f"exchange {fee['exchange_fee_rate']:.4%}, fixed {fee['fixed_fee']:g}, "
        f"slippage {fee['slippage']:.4%} [assumptions]"
    )
    return {
        "settlement_currency": "ARS",
        "ar_data_basis": "; ".join(parts),
        "ar_net_pnl": round(
            state.equity_snapshots[-1].equity - state.initial_capital, 6
        ),
        "ar_total_fees": round(sum(float(f.fee) for f in fills), 6),
        "ar_buy_fees": round(
            sum(float(f.fee) for f in fills if f.signed_quantity > 0), 6
        ),
        "ar_sell_fees": round(
            sum(float(f.fee) for f in fills if f.signed_quantity < 0), 6
        ),
        "ar_unsettled_sale_receivable_at_end": round(
            sum(
                _net_proceeds(f)
                for f in fills
                if f.action in _SALES and _settlement_bar(f) > last_bar
            ),
            6,
        ),
        "ar_unliquidated_position_count": len(retained),
        "ar_terminal_equity_basis": (
            "credit-restricted positions marked net of estimated exit costs"
            if retained
            else "all positions liquidated at the last close"
        ),
        "ar_cedear_ratio_adjustments": list(rules.ratio_adjustments),
        "ar_metadata_provenance": dict(rules.provenance),
        "ar_fee_basis": dict(fee),
        "ar_dropped_no_trade_dates": len(rules.dropped_no_trade_dates),
    }


def write_byma_artifacts(
    run_dir: Any, state: BaseEngine, rules: ArgentinaEquityEngine
) -> None:
    """``artifacts/cash_ledger.csv`` and ``artifacts/byma_preparation.json``."""
    out = Path(run_dir) / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    columns = [
        "timestamp",
        "code",
        "side",
        "qty",
        "notional",
        "fee",
        "total_cost",
        "net_proceeds",
        "cash_flow",
        "cash_after",
        "settlement_date",
        "settlement_basis",
        "buying_power_before",
        "unsettled_sale_proceeds_after",
    ]
    pd.DataFrame(byma_cash_ledger(state), columns=columns).to_csv(
        out / "cash_ledger.csv", index=False
    )
    diagnostics = argentina_diagnostics(state, rules)
    diagnostics["ar_unliquidated_positions"] = list(state.unliquidated_positions)
    diagnostics["ar_dropped_no_trade_dates"] = list(rules.dropped_no_trade_dates)
    (out / "byma_preparation.json").write_text(
        json.dumps(diagnostics, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


# ── configuration ──


def _rate(value: Any, key: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a finite nonnegative number") from None
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{key} must be a finite nonnegative number")
    return parsed


def _config_error(problems: List[str]) -> str:
    lines = "\n".join(f"- {p}" for p in problems)
    return (
        f"BYMA backtest configuration incomplete:\n{lines}\n"
        'Example: "ar_instruments": {"YPFD.BA": {"kind": "share"}, "AAPL.BA": {"kind": '
        '"cedear", "underlying": "AAPL", "ratio_history": [{"effective_date": "YYYY-MM-DD", '
        '"ratio": "20", "credit_date": "YYYY-MM-DD"}]}}. Declare ar_tick_table or per-instrument tick_table/tick_size. Local shares need no kind entry; '
        'do not set "engine": .BA codes select the BYMA engine.'
    )


def _iso(value: Any) -> Optional[date]:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.isoformat() == str(value) else None


def _field_problems(symbol: str, info: dict, *, require: bool = False) -> List[str]:
    """Validate declared fields; with *require*, also report missing essentials."""
    problems: List[str] = []
    kind = info.get("kind")
    if kind not in (None, "share", "cedear"):
        problems.append(f"{symbol}.kind must be 'share' or 'cedear' (got {kind!r})")
    elif require and kind is None:
        problems.append(f"{symbol}.kind is required ('share' or 'cedear')")
    if info.get("currency", "ARS") != "ARS":
        problems.append(f"{symbol}.currency: only ARS lines are supported")
    lot = info.get("lot_size", 1)
    if isinstance(lot, bool) or not isinstance(lot, int) or lot < 1:
        problems.append(f"{symbol}.lot_size must be a positive integer")
    if info.get("tick_size") is not None:
        try:
            parsed_tick = Decimal(str(info["tick_size"]))
            if not parsed_tick.is_finite() or not parsed_tick > 0:
                raise ArithmeticError
        except (ValueError, ArithmeticError):
            problems.append(
                f"{symbol}.tick_size must be a positive number (omit it for BYMA bands)"
            )
    elif require and info.get("tick_table") not in _TICK_TABLES:
        problems.append(
            f"{symbol}: declare tick_size, tick_table or global ar_tick_table from {tuple(_TICK_TABLES)}; panel membership and historical tick rules are not inferred"
        )
    if info.get("tick_table") is not None and info["tick_table"] not in _TICK_TABLES:
        problems.append(f"{symbol}.tick_table must be one of {tuple(_TICK_TABLES)}")
    if kind == "cedear":
        if not info.get("underlying"):
            problems.append(f"{symbol}.underlying is required for a CEDEAR")
        history = info.get("ratio_history")
        if not isinstance(history, list) or not history:
            problems.append(f"{symbol}.ratio_history (dated CEDEAR ratios) is required")
            return problems
        previous: Optional[date] = None
        for item in history:
            effective = (
                _iso(item.get("effective_date")) if isinstance(item, dict) else None
            )
            try:
                ratio = Decimal(str(item["ratio"]))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                ratio = Decimal(0)
            credit = item.get("credit_date") if isinstance(item, dict) else None
            if (
                effective is None
                or not ratio.is_finite()
                or ratio <= 0
                or (previous is not None and effective <= previous)
            ):
                problems.append(
                    f"{symbol}.ratio_history needs increasing ISO effective_date "
                    "and positive ratio entries"
                )
                break
            if credit is not None and (
                _iso(credit) is None or _iso(credit) < effective
            ):
                problems.append(
                    f"{symbol}: credit_date must be an ISO date on/after effective_date"
                )
                break
            if item.get("price_series") not in (None, "adjusted", "unadjusted"):
                problems.append(
                    f"{symbol}: price_series must be 'adjusted' or 'unadjusted'"
                )
                break
            previous = effective
    return problems
