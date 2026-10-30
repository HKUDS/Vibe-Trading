"""Measured semantics of Tushare ``stk_mins`` 5-minute bars for cn_a equities (T1).

Frozen data proof for the 5m paper-trade engine (T2-T6). Everything under
VERIFIED was read from the live ``stk_mins`` endpoint through the production
loader path ``backtest.loaders.tushare.DataLoader.fetch(..., interval="5m")``.

PROBE A (executed 2026-10-21 07:44 CST, one provider call)
    ``600519.SH``, 2026-10-13..2026-10-20 -> 245 rows over 5 trading days.

VERIFIED — bar count and labels
    * 49 raw rows per trading day. First label 09:30:00, last 15:00:00 on
      every one of the five days.
    * The 09:30 row is the opening call-auction snapshot, not a continuous
      bar: on 10-13/14/15/16 its OHLC is one price (1287.00 / 1270.10 /
      1286.00 / 1311.57) and equals that day's ``api.daily`` open.
    * Dropping the 09:30 label leaves exactly 48 continuous bars per day.
      The planbook's "48 five-minute bars" are the CONTINUOUS bars only.
    * 2026-10-17/18 (weekend, ``api.trade_cal`` is_open=0) returned 0 rows.
    * ``end_date`` is exclusive at midnight: fetching 2026-10-13..2026-10-20
      returned 10-13..10-19 only, although ``daily()`` already had 10-20.
      To read day D, pass an end date later than D.

VERIFIED — a label is the bar's END, not its start
    * The 15:00 row is a real 5-minute bar, not a closing-auction print: all
      five days carry a multi-tick range (10-19: O1323.73 H1325.18 L1323.04
      C1324.97). An SSE closing call auction clears at ONE price, so an
      auction-snapshot row would be single-priced; the observed ranges rule
      that reading out.
    * The 09:30 row is single-priced on 4/5 days (the opening auction). Under
      a bar-start convention it would be a full 5-minute continuous bar with
      zero price movement on 20k+ shares — not credible for a 1287 CNY stock.
    * Count arithmetic: a 5-minute grid from 09:30 to 15:00 holds 67 labels;
      only 49 exist, so 18 slots (90 minutes) are skipped — exactly the
      11:30-13:00 lunch break. No bar spans the break.
    * Therefore: 09:35 covers 09:30-09:35, 11:30 covers 11:25-11:30, 13:05
      covers 13:00-13:05, 15:00 covers 14:55-15:00. Session code must read
      label 11:30 as the morning close and 15:00 as the day close, and must
      never expect a 13:00 bar.

VERIFIED — adjustment caliber
    * The 5m close equals the RAW ``api.daily`` close AND the loader's qfq
      close on all five days (1274.89 / 1286.00 / 1312.97 / 1329.00 /
      1324.97); the first 5m open equals the daily open (the auction print).
    * ``api.adj_factor`` is constant over the window (600519: 8.6463;
      603517: 1.5997), so qfq == raw on these days. This probe therefore
      cannot distinguish "raw" from "qfq": what is proven is that the 5m
      frame and the daily frame agree exactly while the factor is constant.
    * Engine rule: never compare a 5m price with a daily qfq price across an
      ex-date without an explicit factor. Anchor on the RAW daily series, or
      scale one leg by ``adj_factor`` on the same day.

VERIFIED — the 5m volume unit differs from the daily frame
    * 5m ``volume`` is in SHARES; the daily loader's ``volume`` is in LOTS
      (``TushareLoader.volume_units == {"a_share": "lots"}``).
    * Proof: 600519 10-13 daily volume is 26,572.76 lots = 2,657,276 shares,
      while that day's 15:00 bar alone reports 154,400. In lots that would be
      15.4M shares = 581% of the whole day; only shares fit.
    * Engine rule: divide 5m volume by 100 (or multiply the daily volume by
      100) before any comparison.

VERIFIED — provider limits observed on this token
    * ``stk_mins`` is capped at 1 call/minute, 1 call/hour AND 2 calls/day.
      A refused request still consumes the daily budget (the cap was hit
      after a single successful call plus two refusals).
    * The daily budget resets at 00:00 Asia/Shanghai.

NOT MEASURED — blocked by that 2-calls/day cap; do not present as fact
    * The explicit 11:30 / 13:05 rows. The bar-end conclusion above is
      derived from the row count, the 09:30 and 15:00 rows, and session
      arithmetic — not from printing those two labels.
    * A suspended symbol-day's 5m response. A real sample is prepared:
      603517.SH is suspended on 2026-10-19 (``api.suspend_d`` type S, and no
      ``daily()`` bar that day) while 10-16 and 10-20 traded. Running the
      command below on a fresh quota probes exactly that window; expect 0
      rows on 10-19. Until then, 5m rows with no continuous session (or a
      zero-volume session) are reported as ``halted``, never as fabricated or
      forward-filled bars; a symbol with no 5m row at all is a provider
      omission and stays ``PAPER_DATA_NOT_READY``.

ENGINE RULE — the day-level session bar (D1, binding for T3/T4)
    pt-v1.2 adds NO order-level bar/timestamp field, so a fill is attributed to
    the bar whose reference price produced it, not to a client order timestamp.
    The engine still assembles ONE session bar per symbol-day from the 48
    CONTINUOUS bars as the day-level gate and summary: open = the 09:35 bar's
    open, high/low = the session extremes, close = the 15:00 bar's close,
    volume = their sum.  The 09:30 opening-auction print is EXCLUDED (T4: the
    auction window never matches), and a label inside 09:15-09:25 or from 14:57
    up to but not including 15:00 is excluded and reported as an
    ``auction_window`` event (the 15:00 label is a continuous bar).  Phase 2
    matching walks the continuous ``bars_by_symbol`` per bar: a market order
    fills at the first marketable bar, a limit order rests until a bar satisfies
    its price and is canceled at session end if none does, and no partial fills
    or volume share are modeled (Phase 3).

Reproduce (repository root, once the daily ``stk_mins`` quota has reset):

    PYTHONPATH=agent conda run -n legonanobot python -m src.tools.paper_trade.data_5m

It prints the per-day label lists, the lunch boundary, the auction row, and
the 48 continuous rows of the first probed day as CSV. Pass
``<code> <start> <end>`` to probe another window.

Run it as a module, not as a file: this directory contains ``calendar.py``,
which would shadow the stdlib ``calendar`` module that pandas imports when
the script's own directory is first on ``sys.path``.
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from . import calendar, state_hash

#: ``agent/`` — the import root the loader package expects (``backtest.*``).
AGENT_DIR = Path(__file__).resolve().parents[3]

#: Label of the opening call-auction row. It is NOT a continuous 5-minute bar.
AUCTION_LABEL = "09:30"

#: Continuous 5-minute bars in one cn_a session pair (09:30-11:30, 13:00-15:00).
#: Hard cap on the symbols ONE 5m step may request.  ``stk_mins`` is measured
#: at 1 call/minute and 1/hour, 2/day; the loader is per-code, so a second
#: symbol in the SAME step is rate-limited immediately — and the refused call
#: still burns the 2/day budget, so a 2-symbol step can never complete (not
#: even on a retry).  P0 constant, re-measure before raising.
MAX_FIVE_MINUTE_SYMBOLS = 1

#: Default probe: a normal day (10-16), a suspended day (10-19) and a resumed
#: day (10-20) in one ranged call, so one unit of the daily quota answers both
#: the session-shape and the suspended-day questions.
DEFAULT_CODE = "603517.SH"
DEFAULT_START = "2026-10-16"
DEFAULT_END = "2026-10-21"

_LUNCH_START = "11:20"
_LUNCH_END = "13:15"

_OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
_PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")

#: cn_a exchange suffixes whose 5-minute (``stk_mins``) leg serves ordinary
#: stocks.  ETFs/LOFs, indices and every other instrument class have no 5m
#: endpoint (the Tushare loader skips funds explicitly), so admitting one would
#: turn a structural limitation into a permanent data-not-ready account (F2).
_FIVE_MINUTE_STOCK_PREFIXES: dict[str, tuple[str, ...]] = {
    "SH": ("600", "601", "603", "605", "688", "689"),
    "SZ": ("000", "001", "002", "003", "300", "301"),
}


def is_supported_five_minute_symbol(symbol: str) -> bool:
    """True when ``stk_mins`` serves 5m bars for this cn_a symbol.

    Only ordinary Shanghai/Shenzhen stocks have a MEASURED 5m leg (T1 probed
    SH; the SZ prefixes share the same ``stk_mins`` endpoint).  ``.SH``
    000/5/88/99/11/12 (indices, bonds, funds), ``.SZ`` 15/16/18/399 (funds,
    indices), every ``.BJ`` listing and every other suffix are rejected: their
    daily bars exist but no 5m endpoint is proven, so admitting them would
    make the step fail closed forever on a provider omission it can never
    observe.
    """
    if not isinstance(symbol, str):
        return False
    code, separator, suffix = symbol.partition(".")
    if separator != "." or len(code) != 6 or not code.isdigit():
        return False
    if suffix == "BJ":
        # BJ 5m not measured in T1; fail fast rather than a permanent
        # provider-omission loop.
        return False
    prefixes = _FIVE_MINUTE_STOCK_PREFIXES.get(suffix)
    return prefixes is not None and code.startswith(prefixes)


def fetch_5m_frame(
    code: str = DEFAULT_CODE,
    start_date: str = DEFAULT_START,
    end_date: str = DEFAULT_END,
) -> tuple[Any | None, Any]:
    """Fetch one cn_a symbol's 5m frame through the production loader path.

    Loads ``agent/.env`` explicitly (the ambient shell is not assumed to carry
    ``TUSHARE_TOKEN``) and calls exactly the method the engine will call:
    ``backtest.loaders.tushare.DataLoader.fetch(..., interval="5m")``.

    Args:
        code: cn_a symbol with exchange suffix, e.g. ``"600519.SH"``.
        start_date: Inclusive first calendar day, ``YYYY-MM-DD``.
        end_date: Last calendar day to request. The provider's end bound is
            exclusive at midnight, so this must be later than the last day
            whose bars are wanted (see the module docstring).

    Returns:
        ``(frame, loader)``: the bar frame indexed by its bar label (a bar
        end, not a bar start), or ``None`` when the provider returns no rows
        for the window; plus the loader instance so the probe can read the
        daily frame without constructing a second ``TushareLoader``.
    """
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))

    from dotenv import load_dotenv

    load_dotenv(AGENT_DIR / ".env", override=True)

    from backtest.loaders.tushare import DataLoader

    loader = DataLoader()
    frames = loader.fetch([code], start_date, end_date, interval="5m")
    return frames.get(code), loader


def _labels(frame: Any) -> list[str]:
    return [timestamp.strftime("%H:%M") for timestamp in frame.index]


def _continuous(day_frame: Any) -> Any:
    """Drop the opening call-auction row, leaving the continuous bars.

    G3 policy: the 09:30 row is the opening call-auction print, not a
    continuous 5-minute bar, so it never participates in matching (T1/T4).
    """
    return day_frame[day_frame.index.strftime("%H:%M") != AUCTION_LABEL]


def _empty_intraday_frame() -> pd.DataFrame:
    columns = {column: pd.Series(dtype="float64") for column in _OHLCV_COLUMNS}
    return pd.DataFrame(columns, index=pd.DatetimeIndex([], name="bar_time"))


def _canonical_intraday_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Canonical 5m shape WITHOUT day normalization (bar labels are kept).

    ``_canonical_frame`` collapses every label to midnight, which is correct
    for day bars and destroys an intraday series — so the 5m leg has its own
    canonicalizer: tz-naive ``DatetimeIndex`` on the provider's Asia/Shanghai
    wall clock (bar ENDS, T1), exactly _OHLCV_COLUMNS, ascending, de-duplicated
    keep-last.  No ``.normalize()``, no resampling, no forwarding.
    """
    if frame is None or len(frame) == 0:
        return _empty_intraday_frame()
    df = frame.copy()
    if "trade_time" in df.columns:
        df = df.set_index(pd.to_datetime(df["trade_time"]))
    elif "trade_date" in df.columns:
        df = df.set_index(pd.to_datetime(df["trade_date"]))
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_convert(calendar.CN_A_SESSION_TIMEZONE).tz_localize(None)
    df.index = index
    df.index.name = "bar_time"
    if "vol" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"vol": "volume"})
    for column in _OHLCV_COLUMNS:
        if column not in df.columns:
            df[column] = float("nan")
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df[list(_OHLCV_COLUMNS)]
    return df[~df.index.duplicated(keep="last")].sort_index()


@dataclass(frozen=True, slots=True)
class SessionBar:
    """One symbol-day's assembled session bar from the continuous 5m bars (D1).

    ``volume`` is the provider's raw 5m unit — SHARES, not the daily frame's
    lots (T1) — so it is never compared with a daily volume without a scale.
    """

    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_count: int


@dataclass(frozen=True)
class FiveMinuteFacts:
    bars_by_symbol: Mapping[str, Mapping[str, pd.DataFrame]] = field(default_factory=dict)
    session_by_symbol: Mapping[str, Mapping[str, SessionBar]] = field(default_factory=dict)
    auction_by_symbol: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    #: Symbol -> days that produced AT LEAST ONE 5m row of any kind (the 09:30
    #: opening-auction print counts).  A symbol with rows but no continuous bar
    #: is a halt candidate; only a symbol with no row at all is a provider
    #: omission (N3).
    observed_days_by_symbol: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    bar_fingerprint: str = ""
    fetch_failed: bool = False
    #: Deterministic reason for ``fetch_failed`` — surfaced verbatim as the
    #: in-band message so a payload fault is never reported as a generic fetch
    #: failure (or, worse, as a caller-contract violation).
    failure_reason: str = ""
    #: Requested symbols for which the provider yielded no 5m row at all.
    missing_symbols: tuple[str, ...] = ()

    def for_symbol(self, symbol: str) -> tuple[Mapping[str, pd.DataFrame], Mapping[str, SessionBar]]:
        return self.bars_by_symbol.get(symbol, {}), self.session_by_symbol.get(symbol, {})


def _finite(value: Any, default: float = 0.0) -> float:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else default


def _assemble_session_bar(continuous: pd.DataFrame) -> SessionBar:
    first = continuous.iloc[0]
    last = continuous.iloc[-1]
    return SessionBar(
        open=float(first["open"]),
        high=float(continuous["high"].max()),
        low=float(continuous["low"].min()),
        close=float(last["close"]),
        volume=float(continuous["volume"].sum()),
        bar_count=int(len(continuous)),
    )


def _split_session_days(
    symbol: str, frame: pd.DataFrame, warnings: list[str]
) -> tuple[dict[str, pd.DataFrame], dict[str, SessionBar], dict[str, tuple[str, ...]]]:
    """Split one symbol's continuous 5m frame into per-day session facts (T4).

    Continuous windows only: the 09:30 opening-auction print is dropped
    silently (it is expected, G3), an auction-window label is dropped AND
    recorded for the ``auction_window`` event, and an out-of-session label is
    dropped with a warning.  A day with zero continuous bars has no session bar
    (the ``halted`` candidate); 1..47 bars are legitimate for an illiquid stock
    and produce one deterministic ``<n>/48`` warning naming the count.

    Payload integrity (G4) is enforced here rather than trusted downstream:

    * a continuous label off the 5-minute grid (a finer interval served as
      5m) raises ``ValueError``;
    * a continuous day whose every row fails the price sanity gate raises
      ``ValueError`` (an all-NaN payload is a provider fault, not a halt);
    * a non-finite session volume raises ``ValueError``;
    * a zero-volume session is a genuine halt: the day is dropped (warned
      about) so the engine's existing halted/suspended path handles it.

    ``fetch_five_minute`` catches these ``ValueError``\\ s and routes them to
    ``failure_reason``, so they surface as ``PAPER_DATA_NOT_READY`` — never as
    a transport error and never as a tradable session.
    """
    bars_by_day: dict[str, pd.DataFrame] = {}
    session_by_day: dict[str, SessionBar] = {}
    auction_by_day: dict[str, tuple[str, ...]] = {}
    if frame.empty:
        return bars_by_day, session_by_day, auction_by_day

    labels = frame.index.strftime("%H:%M")
    days = frame.index.strftime("%Y-%m-%d")
    kinds = [calendar.classify_cn_a_session_label(label) for label in labels]
    framed = frame.copy()
    framed["_day"] = days
    framed["_label"] = labels
    framed["_kind"] = kinds

    for day, chunk in framed.groupby("_day", sort=True):
        # G3: only SESSION_CONTINUOUS rows build the session bar.  The 09:30
        # opening call-auction print is classified separately and excluded.
        continuous = chunk[chunk["_kind"] == calendar.SESSION_CONTINUOUS]
        auction_labels = tuple(sorted(set(chunk.loc[chunk["_kind"] == calendar.SESSION_AUCTION_WINDOW, "_label"])))
        outside_labels = tuple(sorted(set(chunk.loc[chunk["_kind"] == calendar.SESSION_OUTSIDE, "_label"])))
        if auction_labels:
            auction_by_day[day] = auction_labels
            warnings.append(
                f"5m data: {symbol} on {day} has auction-window label(s) "
                f"{', '.join(auction_labels)}; excluded from matching"
            )
        if outside_labels:
            warnings.append(
                f"5m data: {symbol} on {day} has {len(outside_labels)} bar label(s) "
                f"outside the cn_a session windows (first: {outside_labels[0]}); excluded"
            )
        # A 1m payload served as 5m produces labels off the 5-minute grid;
        # accepting them would assemble a ~240-row "session" the matching
        # contract never priced.  Legitimate partial sessions (09:35, 09:40,
        # ..., 11:30, 13:05, ..., 15:00) are all on the grid.
        off_grid = sorted({label for label in continuous["_label"] if int(label[3:5]) % 5 != 0})
        if off_grid:
            raise ValueError(
                f"5m data: {symbol} on {day} has off-grid continuous label(s) "
                f"{', '.join(off_grid[:3])}; labels must sit on the 5-minute grid"
            )
        price_columns = list(_PRICE_COLUMNS)
        had_continuous = not continuous.empty
        bad = (~continuous[price_columns].apply(lambda col: col.map(math.isfinite))).any(axis=1) | (continuous[price_columns] <= 0).any(axis=1)
        bad |= (continuous["high"] < continuous[price_columns].max(axis=1)) | (continuous["low"] > continuous[price_columns].min(axis=1))
        if not continuous["volume"].map(math.isfinite).all() or (continuous["volume"] < 0).any():
            raise ValueError("5m data has invalid bar volume")
        if bad.any():
            warnings.append(
                f"5m data: {symbol} on {day} dropped {int(bad.sum())} bar(s) failing the " "price sanity gate (R-V3)"
            )
            continuous = continuous[~bad]
            if had_continuous and continuous.empty:
                # Every served continuous row was unusable: a provider fault,
                # not a halt.  Fail the payload closed instead of inventing a
                # suspended session from prices that were never valid.
                raise ValueError("all continuous 5m bars failed the price sanity gate")
        if continuous.empty:
            continue
        day_bars = continuous[list(_OHLCV_COLUMNS)].copy()
        session = _assemble_session_bar(day_bars)
        if not math.isfinite(session.volume):
            raise ValueError("5m data has a non-finite session volume")
        if session.volume <= 0:
            # No shares traded across the whole continuous session: a halt.
            # Dropping the day lets the engine's halted/suspended path value
            # positions carry-forward and reject orders `suspended`.
            warnings.append(f"5m data: {symbol} on {day} has a zero-volume session; treated as halted")
            continue
        bars_by_day[day] = day_bars
        session_by_day[day] = session
        if len(day_bars) < calendar.CONTINUOUS_BARS_PER_DAY:
            warnings.append(
                f"5m data: {symbol} on {day} has {len(day_bars)}/48 continuous "
                "bars; session bar assembled from what exists"
            )
    return bars_by_day, session_by_day, auction_by_day


def _bar_fingerprint(facts: FiveMinuteFacts) -> str:
    """D3 bar fingerprint over the continuous 5m bars actually used.

    Payload is a list sorted by (symbol, day, label) so symbol input order and
    dict iteration order cannot change the digest; each row is
    ``[symbol, day, "HH:MM", open, high, low, close, volume]``.  The symbol and
    day are part of the tuple because a bare ``HH:MM`` label repeats across
    symbols and days.  No clock, no paths, no floats beyond the served values.
    """
    payload: list[list[Any]] = []
    for symbol in sorted(facts.bars_by_symbol):
        for day in sorted(facts.bars_by_symbol[symbol]):
            frame = facts.bars_by_symbol[symbol][day]
            for timestamp, row in frame.iterrows():
                payload.append(
                    [
                        symbol,
                        day,
                        timestamp.strftime("%H:%M"),
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        _finite(row["volume"]),
                    ]
                )
    return state_hash.state_hash(payload)


def fetch_five_minute(
    symbols: tuple[str, ...],
    from_date: str,
    to_date: str,
    *,
    loader: Any,
    warnings: list[str],
) -> FiveMinuteFacts:
    """ONE ranged 5m fetch for the whole universe (never one call per day).

    T1: the provider's ``end_date`` is exclusive at midnight, so the request
    end is ``to_date + 1 day``.  The production Tushare loader swallows a
    provider error into an empty mapping, so a failed call and a genuinely
    empty day are indistinguishable at this seam — the caller's whole-universe
    zero-bar rule maps both to ``PAPER_DATA_NOT_READY`` (D6), never to
    ``halted``.  An exception that does surface is caught here, warned about,
    and treated the same way.
    """
    empty = FiveMinuteFacts(bar_fingerprint=state_hash.state_hash([]))
    if not symbols or loader is None:
        return empty
    end_exclusive = (dt.date.fromisoformat(to_date) + dt.timedelta(days=1)).isoformat()
    try:
        served = loader.fetch(list(symbols), from_date, end_exclusive, interval="5m")
    except Exception as exc:  # noqa: BLE001 — a provider fault is data-not-ready, never a halt
        reason = (
            f"5m fetch ({getattr(loader, 'name', 'network')}) failed: "
            f"{type(exc).__name__}; the step is data-not-ready"
        )
        warnings.append(reason)
        return FiveMinuteFacts(
            bar_fingerprint=state_hash.state_hash([]),
            fetch_failed=True,
            failure_reason=reason,
            missing_symbols=tuple(symbols),
        )
    if not served:
        return FiveMinuteFacts(bar_fingerprint=state_hash.state_hash([]), missing_symbols=tuple(symbols))

    start_ts = pd.Timestamp(from_date)
    end_ts = pd.Timestamp(end_exclusive)
    bars_by_symbol: dict[str, Mapping[str, pd.DataFrame]] = {}
    session_by_symbol: dict[str, Mapping[str, SessionBar]] = {}
    auction_by_symbol: dict[str, Mapping[str, tuple[str, ...]]] = {}
    observed_days_by_symbol: dict[str, tuple[str, ...]] = {}
    payload_error = ""
    for symbol in symbols:
        try:
            frame = _canonical_intraday_frame(served.get(symbol))
            if not frame.empty:
                frame = frame[(frame.index >= start_ts) & (frame.index < end_ts)]
            if not frame.empty:
                observed_days_by_symbol[symbol] = tuple(sorted(set(frame.index.strftime("%Y-%m-%d"))))
            bars, sessions, auctions = _split_session_days(symbol, frame, warnings)
        except Exception as exc:  # noqa: BLE001 — a malformed payload is a provider fault
            payload_error = (
                f"5m payload ({getattr(loader, 'name', 'network')}) for {symbol} "
                f"could not be parsed ({type(exc).__name__}); the step is data-not-ready"
            )
            warnings.append(payload_error)
            break
        if bars:
            bars_by_symbol[symbol] = bars
            session_by_symbol[symbol] = sessions
        if auctions:
            auction_by_symbol[symbol] = auctions
    if payload_error:
        return FiveMinuteFacts(
            bar_fingerprint=state_hash.state_hash([]),
            fetch_failed=True,
            failure_reason=payload_error,
            missing_symbols=tuple(symbols),
        )
    facts = FiveMinuteFacts(
        bars_by_symbol=bars_by_symbol,
        session_by_symbol=session_by_symbol,
        auction_by_symbol=auction_by_symbol,
        observed_days_by_symbol=observed_days_by_symbol,
        missing_symbols=tuple(
            symbol for symbol in symbols if symbol not in bars_by_symbol and symbol not in observed_days_by_symbol
        ),
    )
    return _with_fingerprint(facts)


def _with_fingerprint(facts: FiveMinuteFacts) -> FiveMinuteFacts:
    return FiveMinuteFacts(
        bars_by_symbol=facts.bars_by_symbol,
        session_by_symbol=facts.session_by_symbol,
        auction_by_symbol=facts.auction_by_symbol,
        observed_days_by_symbol=facts.observed_days_by_symbol,
        bar_fingerprint=_bar_fingerprint(facts),
        fetch_failed=facts.fetch_failed,
        missing_symbols=facts.missing_symbols,
    )


def main(argv: list[str] | None = None) -> int:
    """Print the probe evidence; exit 2 when the provider yields no 5m rows."""
    args = list(sys.argv[1:] if argv is None else argv)
    code = args[0] if args else DEFAULT_CODE
    start = args[1] if len(args) > 1 else DEFAULT_START
    end = args[2] if len(args) > 2 else DEFAULT_END

    print(f"code={code} start={start} end={end}")
    frame, loader = fetch_5m_frame(code, start, end)
    if frame is None or frame.empty:
        print("NO 5m DATA for this window")
        return 2

    print(f"rows={len(frame)} first={frame.index[0]} last={frame.index[-1]}")
    print(f"columns={list(frame.columns)}")

    daily = loader.fetch([code], start, end, interval="1D").get(code)
    print("\nper-day: count, labels, volume and OHLC vs the daily qfq frame")
    for day, chunk in frame.groupby(frame.index.normalize()):
        labels = _labels(chunk)
        row = daily.loc[day] if daily is not None and day in daily.index else None
        print(f"{day.date()} n={len(chunk)} first={labels[0]} last={labels[-1]} " f"labels={' '.join(labels)}")
        if row is not None:
            print(
                f"    vol5m_sum={chunk['volume'].sum():.2f} daily_vol={row['volume']:.2f} "
                f"ratio={chunk['volume'].sum() / row['volume']:.6f} "
                f"open5m={chunk['open'].iloc[0]:.2f} daily_open={row['open']:.2f} "
                f"close5m={chunk['close'].iloc[-1]:.2f} daily_close={row['close']:.2f} "
                f"high5m={chunk['high'].max():.2f} daily_high={row['high']:.2f} "
                f"low5m={chunk['low'].min():.2f} daily_low={row['low']:.2f}"
            )

    print("\ncalendar days returned:", [str(day.date()) for day in frame.index.normalize().unique()])

    demo_day = frame.index.normalize().unique()[0]
    day_frame = frame[frame.index.normalize() == demo_day]
    print(f"\nauction row vs first continuous bar ({demo_day.date()})")
    print(day_frame.head(2).to_string())
    print("\nlunch boundary rows")
    print(day_frame.loc[f"{demo_day.date()} {_LUNCH_START}" :f"{demo_day.date()} {_LUNCH_END}"].to_string())

    continuous = _continuous(day_frame)
    print(f"\nCSV: full frame ({len(frame)} rows)")
    print(frame.to_csv())
    print(f"CSV: continuous {demo_day.date()} ({len(continuous)} rows)")
    print(continuous.to_csv())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
