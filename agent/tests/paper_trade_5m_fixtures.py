"""Offline dual-leg market data for the cn_a 5m paper-trade tests (T6).

ONE loader serves both legs the engine needs, from the committed CSV fixtures
under ``agent/tests/fixtures/paper_trade/5m/<symbol>/<date>.csv``:

* ``interval="5m"`` returns the raw day files (49 rows: the 09:30 opening
  call-auction print plus 48 continuous bars, labels are bar ENDS).
* every other interval returns a DAILY frame DERIVED from the same session
  bars (open = first continuous open, high/low = session extremes, close =
  last continuous close, volume = the 5m share volume / 100 to reach the
  daily frame's lot unit, T1).

Deriving the daily leg instead of authoring a second fixture keeps the two
legs mutually consistent by construction, which matters because the engine
treats "daily bar present XOR 5m session bar present" as a provider fault
(D6).  A header-only CSV is the zero-bar sentinel for a suspended session, so
a halted symbol has neither leg - exactly what Tushare serves (T1: suspended
days are absent from BOTH endpoints).

The fixtures are SYNTHETIC (see ``MANIFEST.json``); no test may present their
prices as market data.  No network, no clock, no writes.

The module also hosts the shared step harness for the three 5m tool suites
(``test_paper_trade_5m_tool``, ``test_paper_trade_5m_scope``,
``test_paper_trade_5m_strategy``): the seed constants, the payload builders,
and the strategy-file helpers, so a split suite cannot drift apart.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.config.paths import get_runtime_root
from src.tools.paper_trade.tool import run_paper_trade_step

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "paper_trade" / "5m"

OHLCV: tuple[str, ...] = ("open", "high", "low", "close", "volume")
AUCTION_LABEL = "09:30"
_VOLUME_LOTS_PER_SHARE = 100.0

__all__ = [
    "AUCTION_LABEL",
    "FIXTURE_ROOT",
    "FixtureCalendar",
    "FixtureLoader",
    "continuous_bars",
    "derive_daily",
    "fixture_files",
    "fixture_manifest",
    "fixture_reference",
    "fixture_days",
    "load_5m",
    "load_5m_all",
    "session_values",
]


def fixture_manifest() -> dict[str, Any]:
    """The fixture index (synthetic provenance, conventions, per-file digests)."""
    return json.loads((FIXTURE_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))


def fixture_files() -> tuple[Path, ...]:
    """Every committed 5m fixture, symbol-major then day-ascending."""
    return tuple(sorted(FIXTURE_ROOT.glob("*/*.csv")))


def fixture_days(symbol: str) -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in (FIXTURE_ROOT / symbol).glob("*.csv")))


def _empty_intraday() -> pd.DataFrame:
    columns = {column: pd.Series(dtype="float64") for column in OHLCV}
    return pd.DataFrame(columns, index=pd.DatetimeIndex([], name="bar_time"))


def load_5m(symbol: str, day: str) -> pd.DataFrame:
    """One symbol-day's raw bars; a header-only file is zero bars, not an error."""
    path = FIXTURE_ROOT / symbol / f"{day}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"no 5m fixture for {symbol} on {day}: {path}")
    frame = pd.read_csv(path, parse_dates=["bar_time"])
    if frame.empty:
        return _empty_intraday()
    return frame.set_index("bar_time")[list(OHLCV)].sort_index()


def load_5m_all(symbol: str) -> pd.DataFrame:
    """All of one symbol's fixture bars in ascending label order."""
    frames = [load_5m(symbol, day) for day in fixture_days(symbol)]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty_intraday()
    return pd.concat(frames).sort_index()


def continuous_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the 09:30 opening-auction print, leaving the continuous bars."""
    if frame.empty:
        return frame
    return frame[frame.index.strftime("%H:%M") != AUCTION_LABEL]


def session_values(frame: pd.DataFrame) -> dict[str, float]:
    """The D1 session bar (open/high/low/close/volume) from a raw day frame."""
    continuous = continuous_bars(frame)
    if continuous.empty:
        raise ValueError("no continuous 5m bars to assemble a session bar from")
    return {
        "open": float(continuous["open"].iloc[0]),
        "high": float(continuous["high"].max()),
        "low": float(continuous["low"].min()),
        "close": float(continuous["close"].iloc[-1]),
        "volume": float(continuous["volume"].sum()),
    }


def derive_daily(symbol: str) -> pd.DataFrame:
    """A daily frame assembled from the fixture's session bars (lots, T1 units)."""
    records: list[dict[str, Any]] = []
    for day in fixture_days(symbol):
        frame = load_5m(symbol, day)
        if continuous_bars(frame).empty:
            continue
        bar = session_values(frame)
        records.append(
            {
                "trade_date": pd.Timestamp(day),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"] / _VOLUME_LOTS_PER_SHARE,
            }
        )
    frame = pd.DataFrame(records, columns=["trade_date", *OHLCV])
    return frame.set_index("trade_date").sort_index()


def fixture_reference(symbol: str, day: str, path_model: str = "bar_median") -> Decimal:
    """The reference price recomputed from the CSV with Decimal arithmetic.

    Deliberately independent of the engine: ``money()`` is ``Decimal(str(x))``
    and the frozen tick is 2dp HALF_UP, both restated here rather than imported,
    so a change in the engine's helper cannot make this assertion agree with a
    wrong price.
    """
    bar = session_values(load_5m(symbol, day))
    prices = sorted(
        Decimal(str(bar[key])) for key in ("open", "high", "low", "close")
    )
    raw = prices[3] if path_model == "bar_close" else (prices[1] + prices[2]) / Decimal(2)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _window(frame: pd.DataFrame, start_date: str, end_date: str, *, end_inclusive: bool):
    if frame.empty:
        return frame
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    mask = (frame.index >= start) & (
        (frame.index <= end) if end_inclusive else (frame.index < end)
    )
    return frame[mask]


class FixtureLoader:
    """The network leg's structural shape, served entirely from CSV fixtures.

    ``calls`` records every request so a test can prove a step issued exactly
    ONE ranged 5m call (the provider allows 2/day, T1).
    """

    name = "fixture"

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str, str, str]] = []
        self._daily: dict[str, pd.DataFrame] = {}

    def is_available(self) -> bool:
        return True

    def five_minute_calls(self) -> list[tuple[tuple[str, ...], str, str, str]]:
        return [call for call in self.calls if call[3] in ("5m", "5min", "5")]

    def fetch(
        self,
        codes: Iterable[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Sequence[str] | None = None,
    ) -> Mapping[str, pd.DataFrame]:
        ordered = tuple(str(code) for code in codes)
        kind = str(interval)
        self.calls.append((ordered, start_date, end_date, kind))
        five_minute = kind.lower() in ("5m", "5min", "5")
        served: dict[str, pd.DataFrame] = {}
        for code in ordered:
            if five_minute:
                frame = _window(load_5m_all(code), start_date, end_date, end_inclusive=False)
            else:
                if code not in self._daily:
                    self._daily[code] = derive_daily(code)
                frame = _window(self._daily[code], start_date, end_date, end_inclusive=True)
            if not frame.empty:
                served[code] = frame
        return served


class FixtureCalendar:
    """The structural ``TradeCalendarClient`` shape; exactly ``open_days`` are open."""

    def __init__(self, open_days: Iterable[str]) -> None:
        self.open_days = frozenset(open_days)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self.open_days),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


# ── Shared step harness: one seed payload, the strategy sources, the helpers ──

_DAY = "2026-10-20"
_HALTED = "2026-10-19"
_SYM = "600519.SH"
_WITNESS = "000001.SZ"
_THIRD = "600000.SH"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account_id": "pa_5m_tool",
        "market": "cn_a",
        "account_state": {"cash": 1_000_000.0, "positions": []},
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}],
        "from_date": _DAY,
        "to_date": _DAY,
        "fee_model": dict(_FEES),
        "interval": "5m",
    }
    base.update(overrides)
    return base


def _run(payload: dict[str, Any], *, loader: Any = None, calendar: Any = None):
    loader = FixtureLoader() if loader is None else loader
    calendar = FixtureCalendar((payload["to_date"],)) if calendar is None else calendar
    document = run_paper_trade_step(
        payload,
        loader=loader,
        ch_client=None,
        calendar_client=calendar,
        limits_client=None,
    )
    return json.loads(document), loader


def _strategy_payload(path: str, **overrides: Any) -> dict[str, Any]:
    payload = _payload(**overrides)
    payload.pop("orders")
    payload["strategy_path"] = path
    return payload


def _install_strategy(name: str, source: str) -> str:
    # The path policy only admits <runtime_root>/strategies; the conftest HOME
    # sandbox makes that a per-session temp dir.
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _strategy_source(*universe: str) -> str:
    """A minimal SignalEngine selling each target symbol held at call start.

    With ``universe`` it declares UNIVERSE and orders exactly those symbols;
    without it, orders ``ctx.symbols`` (the served universe fallback).
    """
    declaration = f"UNIVERSE = {universe!r}\n\n" if universe else ""
    target = repr(universe) if universe else "ctx.symbols"
    return (
        declaration
        + "class SignalEngine:\n"
        + "\n"
        + "    def generate_signals(self, ctx, trade_date):\n"
        + "        held = {position.symbol: position.qty\n"
        + "                for position in ctx.account_state.positions}\n"
        + "        return [\n"
        + '            {"symbol": symbol, "side": "sell", "qty": held[symbol]}\n'
        + f"            for symbol in {target} if symbol in held\n"
        + "        ]\n"
    )


def _outside_universe_source(declared: tuple[str, ...], target: str) -> str:
    """Declare one 5m UNIVERSE but order a held symbol, possibly outside it."""
    return (
        f"UNIVERSE = {declared!r}\n\n"
        "class SignalEngine:\n"
        "\n"
        "    def generate_signals(self, ctx, trade_date):\n"
        "        held = {position.symbol: position.qty\n"
        "                for position in ctx.account_state.positions}\n"
        f"        if {target!r} not in held:\n"
        "            return []\n"
        f"        return [{{'symbol': {target!r}, 'side': 'sell', 'qty': held[{target!r}]}}]\n"
    )
