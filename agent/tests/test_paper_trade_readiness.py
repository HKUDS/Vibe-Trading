"""T5-gate readiness tests for the paper_trade data layer (Step 2 / T2).

Offline by construction: every fetch injects a fake CH bar client and a fake
network loader, so no test resolves the real registry chain or touches the
network (``--disable-socket`` is a hard gate).  Contract anchors:

* AM-9 — readiness is judged on the FEDERATED MERGED frame: CH missing the
  target day while the network leg serves it ⇒ READY (judging on the CH frame
  alone would false-alarm every trading day); both legs missing ⇒ in-band
  ``PAPER_DATA_NOT_READY`` material (never an exception).
* AM-6 — hk/us zero-calendar three-state matrix: target-day all-market zero
  bar ⇒ not_ready; mid-range all-market zero bar ⇒ ``market_closed_inferred``
  + warning (NOT a failure, never silently ``non_trading_day``); single-symbol
  zero bar ⇒ suspended fact + carry-forward valuation.
* R-V3 — non-positive OHLC bars flag the symbol-day untradable + structured
  warning, no crash.
* VD-6/B3 — K=120 lookback trim; VD-10 — sorted symbols, frozen order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.tools.paper_trade import data as data_layer
from src.tools.paper_trade.calendar import (
    VERDICT_MARKET_CLOSED_INFERRED,
    VERDICT_NOT_READY,
    VERDICT_TRADING_DAY,
    classify_zero_calendar_day,
    hk_us_candidate_days,
)
from src.tools.paper_trade.data import (
    LOOKBACK_TRADING_DAYS,
    assess_readiness,
    day_bar_availability,
    fetch_market_data,
    symbols_for_request,
)
from src.tools.paper_trade.schema import (
    ERROR_CODES,
    SKIPPED_DAY_REASONS,
    AccountState,
    DateRange,
    ErrorEnvelope,
    Order,
    Position,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "market"


class FakeChClient:
    """Recorded CH bar leg; captures requested ranges."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
        self.calls: list[tuple[str, str, str]] = []

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((ts_code, start_date, end_date))
        return self._frames.get(ts_code, pd.DataFrame())


class FakeLoader:
    """Recorded network leg speaking the DataLoaderProtocol fetch shape."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "tencent") -> None:
        self.name = name
        self._frames = frames
        self.calls: list[tuple[list[str], str, str, str]] = []

    def is_available(self) -> bool:
        return True

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        self.calls.append((list(codes), start_date, end_date, interval))
        return {code: self._frames[code] for code in codes if code in self._frames}


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _fixture_frame(name: str) -> tuple[pd.DataFrame, dict]:
    document = json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]], document


# A realistic cn_a week: CH holds Thu 10-15 / Fri 10-16 (T-1 caliber); the
# network leg serves Mon 10-20 (the target day) after the close.
_CH_HISTORY = _frame([("2026-10-15", 1418.0), ("2026-10-16", 1425.5)])
_NET_TODAY = _frame([("2026-10-20", 1430.0)])


def _fetch_cn_a(ch_frames, net_frames, symbols=("600519.SH",), **kwargs):
    return fetch_market_data(
        "cn_a",
        list(symbols),
        kwargs.pop("from_date", "2026-10-20"),
        kwargs.pop("to_date", "2026-10-20"),
        loader=FakeLoader(net_frames, name="tencent"),
        ch_client=FakeChClient(ch_frames),
        **kwargs,
    )


# ── AM-9: cn_a federated merged-frame readiness, dual path ──


def test_network_leg_supplies_target_day_is_ready_even_though_ch_lacks_it() -> None:
    result = _fetch_cn_a({"600519.SH": _CH_HISTORY}, {"600519.SH": _NET_TODAY})

    verdict = assess_readiness(result, "2026-10-20")
    assert verdict.ready is True
    assert verdict.code is None

    prov = result.provenance
    assert prov.source == "clickhouse+tencent(merged)"
    assert prov.ch_as_of == "2026-10-16"
    assert prov.network_as_of == "2026-10-20"
    assert prov.bars_as_of == "2026-10-20"

    merged = result.data["600519.SH"]
    assert merged.bar_dates == frozenset({"2026-10-15", "2026-10-16", "2026-10-20"})
    assert merged.valuation_price == 1430.0
    assert merged.valuation_basis == "last_close"


def test_both_legs_missing_target_day_yields_not_ready_material() -> None:
    result = _fetch_cn_a({"600519.SH": _CH_HISTORY}, {"600519.SH": _CH_HISTORY})

    verdict = assess_readiness(result, "2026-10-20")
    assert verdict.ready is False
    assert verdict.code == "PAPER_DATA_NOT_READY"
    assert verdict.code in ERROR_CODES
    assert "target bar 2026-10-20" in verdict.message
    assert "2026-10-16" in verdict.message


def test_not_ready_materializes_as_in_band_error_envelope() -> None:
    result = _fetch_cn_a({"600519.SH": _CH_HISTORY}, {})
    verdict = assess_readiness(result, "2026-10-20")

    envelope = ErrorEnvelope(
        code=verdict.code,
        account_id="pa_x",
        market="cn_a",
        range=DateRange(from_="2026-10-20", to="2026-10-20"),
        message=verdict.message,
    )
    assert envelope.status == "error"
    assert envelope.code in ERROR_CODES
    assert envelope.account_id == "pa_x"


def test_ch_unreachable_degrades_to_network_only_and_still_ready() -> None:
    result = fetch_market_data(
        "cn_a",
        ["600519.SH"],
        "2026-10-20",
        "2026-10-20",
        loader=FakeLoader({"600519.SH": _NET_TODAY}, name="tencent"),
        ch_client=None,
    )
    verdict = assess_readiness(result, "2026-10-20")
    assert verdict.ready is True
    assert result.provenance.source == "tencent"
    assert result.provenance.ch_as_of is None
    assert result.provenance.network_as_of == "2026-10-20"


def test_single_symbol_missing_target_bar_is_a_suspended_fact_not_not_ready() -> None:
    symbols = ("000001.SZ", "600519.SH")
    result = _fetch_cn_a(
        {"600519.SH": _CH_HISTORY},
        {"600519.SH": _NET_TODAY},
        symbols=symbols,
    )
    assert assess_readiness(result, "2026-10-20").ready is True
    availability = day_bar_availability(result, ["2026-10-20"])
    assert availability == {"2026-10-20": ("600519.SH",)}
    # The zero-bar symbol values at avg_cost with a structured warning (B3).
    missing = result.data["000001.SZ"]
    assert missing.valuation_price is None
    assert missing.valuation_basis == "avg_cost"
    assert any("000001.SZ" in warning and "avg_cost" in warning for warning in result.warnings)


def test_no_available_source_is_a_warning_and_not_ready_never_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(data_layer, "_resolve_network_loader", lambda *_a, **_k: None)
    result = fetch_market_data(
        "cn_a", ["600519.SH"], "2026-10-20", "2026-10-20", ch_client=None
    )
    assert result.provenance.source == "unavailable"
    assert any("no available data source" in warning for warning in result.warnings)
    verdict = assess_readiness(result, "2026-10-20")
    assert verdict.ready is False
    assert verdict.code == "PAPER_DATA_NOT_READY"


# ── AM-6: hk/us zero-calendar three-state matrix ──


def test_mid_range_zero_bars_are_market_closed_inferred_not_a_failure() -> None:
    frame, document = _fixture_frame("synthetic_holiday_gap.json")
    result = fetch_market_data(
        "us",
        ["SYNTH-GAP"],
        "2026-03-02",
        "2026-04-10",
        loader=FakeLoader({"SYNTH-GAP": frame}, name="sina"),
    )
    candidates = hk_us_candidate_days("2026-03-02", "2026-04-10")
    availability = day_bar_availability(result, candidates)

    for gap in document["gap_samples"]:
        for day in gap["missing_weekdays"]:
            verdict = classify_zero_calendar_day(
                "us", day, is_target_day=False, symbols=("SYNTH-GAP",),
                symbols_with_bars=availability[day],
            )
            assert verdict.kind == VERDICT_MARKET_CLOSED_INFERRED
            assert verdict.kind != "non_trading_day"  # never silent
            assert verdict.kind in SKIPPED_DAY_REASONS  # frozen vocabulary member
            assert verdict.warning is not None and day in verdict.warning

    # The run itself is NOT a failure: the target day is served and ready.
    assert availability["2026-04-10"] == ("SYNTH-GAP",)
    assert assess_readiness(result, "2026-04-10").ready is True
    trading = classify_zero_calendar_day(
        "us", "2026-04-10", is_target_day=True, symbols=("SYNTH-GAP",),
        symbols_with_bars=availability["2026-04-10"],
    )
    assert trading.kind == VERDICT_TRADING_DAY
    assert trading.suspended_symbols == ()


def test_target_day_all_market_zero_bar_classifies_as_not_ready() -> None:
    verdict = classify_zero_calendar_day(
        "hk", "2026-10-20", is_target_day=True, symbols=("00700.HK",), symbols_with_bars=()
    )
    assert verdict.kind == VERDICT_NOT_READY
    assert verdict.warning is None


def test_single_symbol_zero_bar_on_trading_day_is_suspended_set() -> None:
    verdict = classify_zero_calendar_day(
        "hk", "2026-10-20", is_target_day=False,
        symbols=("00700.HK", "09988.HK"), symbols_with_bars=("00700.HK",),
    )
    assert verdict.kind == VERDICT_TRADING_DAY
    assert verdict.suspended_symbols == ("09988.HK",)


def test_classify_refuses_cn_a_and_candidate_days_are_weekdays_only() -> None:
    with pytest.raises(ValueError, match="hk/us only"):
        classify_zero_calendar_day(
            "cn_a", "2026-10-20", is_target_day=True, symbols=("600519.SH",),
            symbols_with_bars=(),
        )
    assert hk_us_candidate_days("2026-10-15", "2026-10-20") == (
        "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20",
    )
    with pytest.raises(ValueError):
        hk_us_candidate_days("2026-10-20", "2026-10-15")


def test_hk_target_day_zero_bar_through_fetch_is_not_ready() -> None:
    result = fetch_market_data(
        "hk",
        ["00700.HK"],
        "2026-10-20",
        "2026-10-20",
        loader=FakeLoader({"00700.HK": _CH_HISTORY}, name="tencent"),
    )
    verdict = assess_readiness(result, "2026-10-20")
    assert verdict.ready is False
    assert verdict.code == "PAPER_DATA_NOT_READY"
    assert result.provenance.source == "tencent"
    assert result.provenance.ch_as_of is None


# ── R-V3 price sanity gate ──


def test_non_positive_price_bars_flag_untradable_days_with_warning() -> None:
    rows = [
        ("2026-10-15", -3.5),  # additive-qfq old level gone negative
        ("2026-10-16", 0.0),
        ("2026-10-20", 12.25),
    ]
    result = _fetch_cn_a({}, {"600519.SH": _frame(rows)})
    symbol_data = result.data["600519.SH"]
    assert symbol_data.untradable_dates == ("2026-10-15", "2026-10-16")
    assert symbol_data.has_bar("2026-10-20")
    assert symbol_data.valuation_price == 12.25
    assert any("price sanity" in warning and "600519.SH" in warning for warning in result.warnings)
    # The gate never crashes and never blocks the healthy target day.
    assert assess_readiness(result, "2026-10-20").ready is True


def test_all_window_closes_non_positive_falls_back_to_avg_cost() -> None:
    result = _fetch_cn_a({}, {"600519.SH": _frame([("2026-10-20", -1.0)])})
    symbol_data = result.data["600519.SH"]
    assert symbol_data.valuation_price is None
    assert symbol_data.valuation_basis == "avg_cost"
    assert any("avg_cost" in warning for warning in result.warnings)


# ── VD-6/B3 window freeze + VD-10 deterministic ordering ──


def test_lookback_window_trims_to_exactly_k_trading_bars() -> None:
    long_history = pd.DataFrame(
        {
            "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1.0,
        },
        index=pd.DatetimeIndex(
            pd.bdate_range(end="2026-10-16", periods=LOOKBACK_TRADING_DAYS + 30),
            name="trade_date",
        ),
    )
    target = _frame([("2026-10-20", 11.0)])
    merged = pd.concat([long_history, target])
    result = _fetch_cn_a({}, {"600519.SH": merged})
    frame = result.data["600519.SH"].frame
    before = frame[frame.index < pd.Timestamp("2026-10-20")]
    assert len(before) == LOOKBACK_TRADING_DAYS
    assert frame.index.max() == pd.Timestamp("2026-10-20")


def test_symbols_are_sorted_before_fetch_and_frozen_in_output() -> None:
    net = {"000001.SZ": _NET_TODAY, "300750.SZ": _NET_TODAY, "600519.SH": _NET_TODAY}
    loader = FakeLoader(net, name="tencent")
    result = fetch_market_data(
        "cn_a",
        ["600519.SH", "000001.SZ", "300750.SZ", "000001.SZ"],
        "2026-10-20",
        "2026-10-20",
        loader=loader,
        ch_client=FakeChClient({}),
    )
    assert result.symbols == ("000001.SZ", "300750.SZ", "600519.SH")
    assert list(result.data) == list(result.symbols)
    assert loader.calls[0][0] == ["000001.SZ", "300750.SZ", "600519.SH"]


def test_symbols_for_request_is_the_sorted_union_of_positions_and_orders() -> None:
    state = AccountState(
        cash=1000.0,
        positions=(Position("600519.SH", 100, 1418.0), Position("000001.SZ", 200, 10.5)),
    )
    orders = (Order("600519.SH", "buy", 100), Order("300750.SZ", "sell", 50))
    assert symbols_for_request(state, orders) == ("000001.SZ", "300750.SZ", "600519.SH")
    # Zero-order pure-valuation path.
    assert symbols_for_request(state, None) == ("000001.SZ", "600519.SH")
    assert symbols_for_request(AccountState(cash=1.0), ()) == ()


def test_empty_universe_is_vacuously_ready() -> None:
    result = fetch_market_data(
        "cn_a", [], "2026-10-20", "2026-10-20",
        loader=FakeLoader({}), ch_client=FakeChClient({}),
    )
    assert result.symbols == ()
    assert assess_readiness(result, "2026-10-20").ready is True


# ── Input validation + determinism ──


def test_invalid_inputs_fail_closed_with_deterministic_messages() -> None:
    with pytest.raises(ValueError, match="unknown market"):
        fetch_market_data("crypto", ["BTC-USDT"], "2026-10-20", "2026-10-20")
    with pytest.raises(ValueError, match="from_date"):
        fetch_market_data(
            "cn_a", ["600519.SH"], "2026-10-21", "2026-10-20",
            loader=FakeLoader({}), ch_client=None,
        )
    with pytest.raises(ValueError, match="clickhouse"):
        fetch_market_data(
            "cn_a", ["600519.SH"], "2026-10-20", "2026-10-20",
            loader=FakeLoader({}, name="clickhouse"), ch_client=None,
        )


def test_same_inputs_produce_identical_results() -> None:
    def run():
        return _fetch_cn_a({"600519.SH": _CH_HISTORY}, {"600519.SH": _NET_TODAY})

    first, second = run(), run()
    assert first.symbols == second.symbols
    assert first.provenance == second.provenance
    assert first.warnings == second.warnings
    assert first.data["600519.SH"].bar_dates == second.data["600519.SH"].bar_dates
    assert first.data["600519.SH"].frame.equals(second.data["600519.SH"].frame)
