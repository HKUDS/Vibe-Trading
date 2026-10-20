"""Dated listing exchange for Vietnamese names that moved exchange.

A suffix names the exchange a symbol lists on today. A name that moved to
HOSE from HNX or UPCoM keeps its ``.VN`` code over its whole history in local
files, so without a dated listing its HNX or UPCoM sessions run under HOSE's
±7% band and tick grid: moves the old exchange allowed read as locked days,
and fills land on a grid that did not apply. ``vn_exchange_history`` dates the
listing; these tests pin the lookup, the bands it selects, the band check and
fill grid that follow from it, and the composite path.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.composite import CompositeEngine
from backtest.engines.vietnam_equity import (
    VN_FIRST_DAY_BANDS,
    VN_PRICE_BANDS,
    VietnamEquityEngine,
    hose_base_price,
    parse_exchange_history,
)

CODE = "ACB.VN"
MOVE = "2020-12-09"  # first session on HOSE
HISTORY = {CODE: {"2018-01-02": "HNX", MOVE: "HOSE"}}

HNX_DAY = pd.Timestamp("2020-12-08")
MOVE_DAY = pd.Timestamp(MOVE)
HOSE_DAY = pd.Timestamp("2020-12-10")


def _engine(**overrides) -> VietnamEquityEngine:
    config = {"initial_cash": 1_000_000_000, "vn_exchange_history": HISTORY}
    config.update(overrides)
    return VietnamEquityEngine(config)


def _check(engine, ts, direction: int, open_price: float, reference: float) -> bool:
    engine._bar_ts = ts
    bar = pd.Series({"open": open_price, "pre_close": reference}, name=ts)
    return engine.can_execute(CODE, direction, bar)


class TestConfig:
    def test_entries_are_sorted_and_names_normalised(self) -> None:
        parsed = parse_exchange_history({CODE: {MOVE: "hose", "2018-01-02": " hnx "}})

        assert parsed == {
            CODE: (
                (pd.Timestamp("2018-01-02"), pd.Timestamp(MOVE)),
                ("HNX", "HOSE"),
            )
        }

    def test_hsx_is_read_as_hose(self) -> None:
        assert parse_exchange_history({CODE: {MOVE: "HSX"}})[CODE][1] == ("HOSE",)

    @pytest.mark.parametrize("empty", [None, {}])
    def test_no_value_means_no_history(self, empty) -> None:
        assert parse_exchange_history(empty) == {}

    @pytest.mark.parametrize(
        "history,message",
        [
            ([CODE], "must map each symbol"),
            ({CODE: {}}, "non-empty"),
            ({CODE: [MOVE, "HOSE"]}, "non-empty"),
            ({CODE: {"2020-13-45": "HOSE"}}, "is not a date"),
            ({CODE: {"": "HOSE"}}, "is not a date"),
            ({CODE: {MOVE: "NYSE"}}, "unknown exchange"),
            ({CODE: {MOVE: "HOSE", f"{MOVE} 09:15": "HNX"}}, "two entries"),
        ],
    )
    def test_a_malformed_history_is_refused(self, history, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_exchange_history(history)

    def test_the_engine_refuses_it_at_construction(self) -> None:
        with pytest.raises(ValueError, match="unknown exchange"):
            VietnamEquityEngine({"vn_exchange_history": {CODE: {MOVE: "NYSE"}}})


class TestListingOn:
    @pytest.mark.parametrize(
        "ts,expected",
        [
            (None, ("HOSE", False)),  # no bar: the suffix
            (pd.Timestamp("2017-06-01"), ("HOSE", False)),  # before the history
            # The earliest date starts the history; it is not a move.
            (pd.Timestamp("2018-01-02"), ("HNX", False)),
            (HNX_DAY, ("HNX", False)),
            (MOVE_DAY, ("HOSE", True)),
            (pd.Timestamp(f"{MOVE} 14:45"), ("HOSE", True)),
            (HOSE_DAY, ("HOSE", False)),
        ],
    )
    def test_the_exchange_follows_the_date(self, ts, expected) -> None:
        assert _engine().listing_on(CODE, ts) == expected

    def test_a_tz_aware_bar_keeps_its_local_date(self) -> None:
        # Local midnight is 17:00 UTC the day before; the session is still 9 Dec.
        ts = pd.Timestamp(MOVE, tz="Asia/Ho_Chi_Minh")
        assert _engine().listing_on(CODE, ts) == ("HOSE", True)

    def test_a_symbol_without_history_reads_its_suffix(self) -> None:
        engine = _engine()
        assert engine.listing_on("PVS.HNX", HNX_DAY) == ("HNX", False)
        assert engine.listing_on("VIC.VN", MOVE_DAY) == ("HOSE", False)


class TestBandFor:
    def test_each_bar_takes_the_band_of_its_exchange(self) -> None:
        engine = _engine()
        assert engine.band_for(CODE, HNX_DAY) == VN_PRICE_BANDS["HNX"]
        assert engine.band_for(CODE, MOVE_DAY) == VN_FIRST_DAY_BANDS["HOSE"]
        assert engine.band_for(CODE, HOSE_DAY) == VN_PRICE_BANDS["HOSE"]

    def test_a_move_off_hose_takes_the_new_exchanges_first_day_band(self) -> None:
        engine = _engine(
            vn_exchange_history={
                "XYZ.VN": {"2015-01-05": "HOSE", "2023-04-03": "UPCOM"}
            }
        )
        assert engine.band_for("XYZ.VN", pd.Timestamp("2023-03-31")) == 0.07
        assert engine.band_for("XYZ.VN", pd.Timestamp("2023-04-03")) == 0.40
        assert engine.band_for("XYZ.VN", pd.Timestamp("2023-04-04")) == 0.15

    def test_without_history_the_bands_are_unchanged(self) -> None:
        engine = VietnamEquityEngine({})
        assert engine.band_for(CODE) == 0.07
        assert engine.band_for(CODE, HNX_DAY) == 0.07
        assert engine.band_for("PVS.HNX", HNX_DAY) == 0.10

    def test_a_configured_price_limit_still_sets_every_band(self) -> None:
        engine = _engine(price_limit=0.07)
        assert engine.band_for(CODE, HNX_DAY) == 0.07
        assert engine.band_for(CODE, MOVE_DAY) == 0.07
        # ...while the tick grid still follows the dated exchange.
        assert engine.exchange_on(CODE, HNX_DAY) == "HNX"

    def test_a_disabled_band_stays_disabled(self) -> None:
        assert _engine(price_limit=0).band_for(CODE, MOVE_DAY) is None


class TestBandCheck:
    """Reference 20,000 VND; slippage 0.1% as in the engine's default."""

    def test_a_buy_above_seven_percent_fills_while_on_hnx(self) -> None:
        # Open +8%: fill 21,621.6 -> 21,700 on HNX's grid, under 22,000.
        assert _check(_engine(), HNX_DAY, 1, 21_600.0, 20_000.0) is True
        # Read as HOSE (no history) the same order meets the 21,400 ceiling.
        assert _check(VietnamEquityEngine({}), HNX_DAY, 1, 21_600.0, 20_000.0) is False

    def test_a_sell_below_seven_percent_fills_while_on_hnx(self) -> None:
        # Open -8.5%: fill 18,281.7 -> 18,200 on HNX's grid, above 18,000.
        assert _check(_engine(), HNX_DAY, 0, 18_300.0, 20_000.0) is True
        assert _check(VietnamEquityEngine({}), HNX_DAY, 0, 18_300.0, 20_000.0) is False

    def test_the_first_hose_session_takes_the_first_day_band(self) -> None:
        # Open +15% on the move day: inside ±20%, outside ±7% the day after.
        assert _check(_engine(), MOVE_DAY, 1, 23_000.0, 20_000.0) is True
        assert _check(_engine(), HOSE_DAY, 1, 23_000.0, 20_000.0) is False

    def test_the_ceiling_still_binds_on_hnx(self) -> None:
        # Open +10%: the fill 22,022 rounds up past HNX's 22,000 ceiling.
        assert _check(_engine(), HNX_DAY, 1, 22_000.0, 20_000.0) is False


class TestTickGrid:
    def test_fills_slip_onto_the_grid_of_the_day(self) -> None:
        engine = _engine()
        engine._active_symbol = CODE
        engine._bar_ts = HNX_DAY
        assert engine.apply_slippage(20_000.0, 1) == 20_100.0  # 100 VND grid
        engine._bar_ts = HOSE_DAY
        assert engine.apply_slippage(20_000.0, 1) == 20_050.0  # HOSE: 50 VND

    def test_the_reference_rounds_onto_the_grid_of_the_day(self) -> None:
        engine = _engine()
        bar = pd.Series({"open": 20_100.0, "pre_close": 20_060.0})
        assert hose_base_price(engine, CODE, bar, "HNX") == 20_000.0
        assert hose_base_price(engine, CODE, bar, "HOSE") == 20_050.0
        engine._bar_ts = HNX_DAY
        assert engine._base_price(CODE, bar) == 20_000.0


class TestComposite:
    """The composite owns the bar cursor; its Vietnam rule book must follow it."""

    def _composite(self) -> CompositeEngine:
        codes = [CODE, "AAPL.US"]
        config = {
            "initial_cash": 1_000_000_000,
            "codes": codes,
            "vn_exchange_history": HISTORY,
        }
        return CompositeEngine(config, codes)

    def test_the_band_follows_the_composites_bar(self) -> None:
        engine = self._composite()
        assert _check(engine, HNX_DAY, 1, 21_600.0, 20_000.0) is True
        assert _check(engine, HOSE_DAY, 1, 21_600.0, 20_000.0) is False

    def test_fills_slip_onto_the_grid_of_the_composites_bar(self) -> None:
        engine = self._composite()
        engine._active_symbol = CODE
        engine._bar_ts = HNX_DAY
        assert engine.apply_slippage(20_000.0, 1) == 20_100.0
        engine._bar_ts = HOSE_DAY
        assert engine.apply_slippage(20_000.0, 1) == 20_050.0


# ── Through BaseEngine's own execution path ──

# Bar 1 opens 8% above bar 0's close: inside HNX's band, at HOSE's ceiling.
_DATES = pd.bdate_range("2020-12-02", periods=6)  # 2 Dec .. 9 Dec, the move day
_BARS = pd.DataFrame(
    {
        "open": [20_000.0, 21_600.0, 21_700.0, 21_800.0, 21_900.0, 22_000.0],
        "high": [20_100.0, 21_700.0, 21_800.0, 21_900.0, 22_000.0, 22_100.0],
        "low": [19_900.0, 21_500.0, 21_600.0, 21_700.0, 21_800.0, 21_900.0],
        "close": [20_000.0, 21_600.0, 21_700.0, 21_800.0, 21_900.0, 22_000.0],
        "volume": [1_000_000.0] * 6,
    },
    index=_DATES,
)


class _Loader:
    def fetch(self, *args, **kwargs):
        return {CODE: _BARS.copy()}


class _Signal:
    def generate(self, data_map):
        return {CODE: pd.Series(0.5, index=data_map[CODE].index)}


def _run(run_dir: Path, **overrides) -> VietnamEquityEngine:
    config = {
        "codes": [CODE],
        "start_date": "2020-12-02",
        "end_date": "2020-12-09",
        "source": "local",
        "initial_cash": 1_000_000_000,
        "position_adjustment": "rebalance",
        **overrides,
    }
    engine = VietnamEquityEngine(config)
    engine.run_backtest(config, _Loader(), _Signal(), run_dir)
    return engine


def test_a_run_fills_the_hnx_session_that_hose_rules_would_lock(tmp_path: Path) -> None:
    dated = _run(tmp_path / "dated", vn_exchange_history=HISTORY)
    suffix_only = _run(tmp_path / "suffix")

    first = dated.fill_records[0]
    assert (first.bar_idx, first.action) == (1, "open")
    assert first.execution_price == 21_700.0  # 21,621.6 on HNX's 100 VND grid
    # As HOSE, bar 1 opens at the ceiling and the buy waits a session.
    late = suffix_only.fill_records[0]
    assert (late.bar_idx, late.action) == (2, "open")
    assert late.execution_price == 21_750.0  # 21,721.7 on HOSE's 50 VND grid


def test_the_engine_exposes_the_bar_it_is_on(tmp_path: Path) -> None:
    engine = _run(tmp_path, vn_exchange_history=HISTORY)
    assert engine._bar_ts == _DATES[-1]
    assert engine.exchange_on(CODE, engine._bar_ts) == "HOSE"
