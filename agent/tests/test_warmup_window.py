"""Warm-up history must feed the indicators without joining the performance.

Issue #1240: a strategy with a long lookback (MA200) needs bars from before the
period the user asked about. The agent loaded them by moving ``start_date``
earlier — and the backtest then graded them. A run billed as ten years reported
eleven: trades fired in the extra year, and CAGR and the benchmark were computed
over the longer window. Nothing raised, and the metrics were internally
consistent, so the wrong evaluation period was invisible in the output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import BaseEngine, evaluation_start_index


class _Engine(BaseEngine):
    """Frictionless engine: only the evaluation window is under test."""

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return float(raw_size)

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price


class _Loader:
    def __init__(self, data_map):
        self._data_map = data_map

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return self._data_map


class _MovingAverageCross:
    """Long while price is above its own moving average — needs `window` bars."""

    def __init__(self, window: int):
        self.window = window

    def generate(self, data):
        out = {}
        for code, frame in data.items():
            ma = frame["close"].rolling(self.window).mean()
            out[code] = (frame["close"] > ma).astype(float)
        return out


def _prices(n: int, start: str = "2015-01-01") -> pd.DataFrame:
    """A rising series with a dip, so the MA rule both enters and exits."""
    idx = pd.bdate_range(start, periods=n)
    base = np.linspace(100.0, 200.0, n)
    wobble = 8.0 * np.sin(np.arange(n) / 9.0)
    return pd.DataFrame({"open": base + wobble, "close": base + wobble}, index=idx)


class TestEvaluationStartIndex:
    dates = pd.bdate_range("2015-01-01", periods=100)

    def test_absent_declaration_evaluates_everything(self):
        assert evaluation_start_index({}, self.dates) == 0
        assert evaluation_start_index({"warmup_bars": 0}, self.dates) == 0

    def test_warmup_bars(self):
        assert evaluation_start_index({"warmup_bars": 30}, self.dates) == 30

    def test_evaluation_start_date_lands_on_the_first_bar_at_or_after_it(self):
        boundary = self.dates[40]
        cfg = {"evaluation_start_date": boundary.strftime("%Y-%m-%d")}
        assert evaluation_start_index(cfg, self.dates) == 40
        # A weekend date resolves forward to the next trading bar.
        assert self.dates[evaluation_start_index(
            {"evaluation_start_date": "2015-03-14"}, self.dates
        )] >= pd.Timestamp("2015-03-14")

    def test_declaring_both_is_refused(self):
        with pytest.raises(ValueError, match="not both"):
            evaluation_start_index(
                {"warmup_bars": 10, "evaluation_start_date": "2015-03-01"}, self.dates
            )

    def test_a_boundary_that_leaves_nothing_is_refused(self):
        with pytest.raises(ValueError, match="evaluation window"):
            evaluation_start_index({"warmup_bars": 99}, self.dates)
        with pytest.raises(ValueError, match="after the last loaded bar"):
            evaluation_start_index({"evaluation_start_date": "2030-01-01"}, self.dates)

    def test_malformed_warmup_is_refused(self):
        with pytest.raises(ValueError, match="non-negative"):
            evaluation_start_index({"warmup_bars": -5}, self.dates)
        with pytest.raises(ValueError, match="must be an integer"):
            evaluation_start_index({"warmup_bars": "two hundred"}, self.dates)


class TestWarmupIsExcludedFromPerformance:
    frame = _prices(600)
    boundary = 250

    def _run(self, tmp_path, config_extra):
        data_map = {"AAA": self.frame}
        engine = _Engine({"initial_cash": 100_000.0})
        config = {
            "codes": ["AAA"],
            "start_date": str(self.frame.index[0].date()),
            "end_date": str(self.frame.index[-1].date()),
            **config_extra,
        }
        metrics = engine.run_backtest(
            config, _Loader(data_map), _MovingAverageCross(60), tmp_path
        )
        return engine, metrics

    def test_no_trade_and_no_equity_point_precedes_the_boundary(self, tmp_path):
        engine, _ = self._run(tmp_path, {"warmup_bars": self.boundary})
        first_bar = self.frame.index[self.boundary]

        assert engine.equity_snapshots, "the evaluated window produced no equity curve"
        assert min(s.timestamp for s in engine.equity_snapshots) >= first_bar
        assert engine.trades, "fixture must trade, or it proves nothing"
        assert min(t.entry_time for t in engine.trades) >= first_bar

    def test_the_warmup_year_changes_the_reported_performance(self, tmp_path):
        """The bug: identical loaded data, and the metrics silently differed."""
        _, graded_everything = self._run(tmp_path / "a", {})
        _, graded_after_warmup = self._run(
            tmp_path / "b", {"warmup_bars": self.boundary}
        )

        assert graded_everything["total_return"] != graded_after_warmup["total_return"]
        assert graded_everything["annual_return"] != graded_after_warmup["annual_return"]

    def test_the_two_spellings_agree(self, tmp_path):
        _, by_bars = self._run(tmp_path / "a", {"warmup_bars": self.boundary})
        _, by_date = self._run(
            tmp_path / "b",
            {"evaluation_start_date": str(self.frame.index[self.boundary].date())},
        )
        assert by_bars["total_return"] == pytest.approx(by_date["total_return"])

    def test_warmup_history_still_reaches_the_indicator(self, tmp_path):
        """The point of loading the extra bars: the strategy starts warmed up.

        Same evaluation window, twice. Given warm-up history the moving average
        is already defined on the first evaluated bar, so the book can hold a
        position immediately; loading only the evaluation window leaves the
        indicator NaN until its lookback fills, and the first trade is late.
        """
        warm_engine, _ = self._run(tmp_path / "warm", {"warmup_bars": self.boundary})

        cold_map = {"AAA": self.frame.iloc[self.boundary:]}
        cold_engine = _Engine({"initial_cash": 100_000.0})
        cold_engine.run_backtest(
            {
                "codes": ["AAA"],
                "start_date": str(self.frame.index[self.boundary].date()),
                "end_date": str(self.frame.index[-1].date()),
            },
            _Loader(cold_map),
            _MovingAverageCross(60),
            tmp_path / "cold",
        )

        assert warm_engine.trades and cold_engine.trades
        assert min(t.entry_time for t in warm_engine.trades) < min(
            t.entry_time for t in cold_engine.trades
        )


class TestOptionsEngineHonoursTheBoundary:
    """The options pipeline builds its own date sequence and needs the same cut."""

    dates = pd.bdate_range("2025-01-01", periods=8)
    bars = pd.DataFrame(
        {
            "open": np.linspace(100.0, 107.0, 8),
            "high": np.linspace(101.0, 108.0, 8),
            "low": np.linspace(99.0, 106.0, 8),
            "close": np.linspace(100.5, 107.5, 8),
            "volume": [1000] * 8,
        },
        index=dates,
    )

    class _OptionsLoader:
        name = "yfinance"

        def __init__(self, bars):
            self._bars = bars

        def fetch(self, codes, start_date, end_date):
            return {"SPY": self._bars.copy()}

    class _OpenOnDay:
        """Opens on day 1 — inside the warm-up — and never closes."""

        def generate(self, data_map):
            return [
                {
                    "date": "2025-01-01",
                    "action": "open",
                    "underlying": "SPY",
                    "legs": [
                        {"type": "call", "strike": 101.0, "expiry": "2025-03-21", "qty": 5}
                    ],
                }
            ]

    def _run(self, tmp_path, extra):
        from backtest.engines.options_portfolio import run_options_backtest

        run_options_backtest(
            {
                "codes": ["SPY"],
                "start_date": "2025-01-01",
                "end_date": "2025-01-10",
                "source": "yfinance",
                "engine": "options",
                "initial_cash": 100_000,
                **extra,
            },
            self._OptionsLoader(self.bars),
            self._OpenOnDay(),
            tmp_path,
        )
        return tmp_path / "artifacts"

    def test_a_signal_inside_the_warmup_never_fills(self, tmp_path):
        graded_everything = pd.read_csv(self._run(tmp_path / "a", {}) / "trades.csv")
        assert not graded_everything.empty, "fixture must trade, or it proves nothing"

        after_warmup = self._run(tmp_path / "b", {"warmup_bars": 3}) / "trades.csv"
        assert pd.read_csv(after_warmup).empty


class TestExplicitBenchmarkIsMeasuredOverTheEvaluatedWindow:
    """The explicit-benchmark path measured the benchmark over the FETCHED window.

    ``resolve_benchmark`` fetches ``start_date``..``end_date`` and reports the
    buy-and-hold return over all of it. The per-bar ``ret_series`` was reindexed
    onto the clipped evaluation dates, but ``benchmark_return`` — and therefore
    the ``excess_return`` derived from it — kept the full-window number. A run
    that declared a warm-up then compared its own short-window total_return
    against a benchmark measured over the longer window: the same
    mismatched-window error #1240 exists to prevent, surviving inside the fix
    for it. Only ``benchmark="auto"`` (the mean of the already-clipped return
    frame) was correct.
    """

    boundary = 60

    @staticmethod
    def _frame(n=260):
        idx = pd.bdate_range("2024-01-01", periods=n)
        # Strategy prices: a clean uptrend so the run trades and is gradeable.
        price = pd.Series(np.linspace(100.0, 160.0, n), index=idx)
        return pd.DataFrame(
            {
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": 1_000.0,
            },
            index=idx,
        )

    def _run(self, tmp_path, extra, bench_close):
        from backtest import benchmark as bench_mod
        from backtest.benchmark import BenchmarkResult
        from backtest.metrics import bar_returns, buy_and_hold_return

        frame = self._frame()
        engine = _Engine({"initial_cash": 100_000.0})
        result = BenchmarkResult(
            ticker="SPY",
            ret_series=bar_returns(bench_close, label="bench"),
            total_ret=buy_and_hold_return(bench_close),
            close=bench_close,
        )
        original = bench_mod.resolve_benchmark
        bench_mod.resolve_benchmark = lambda **kwargs: result
        try:
            metrics = engine.run_backtest(
                {
                    "codes": ["AAA"],
                    "start_date": str(frame.index[0].date()),
                    "end_date": str(frame.index[-1].date()),
                    "benchmark": "SPY",
                    **extra,
                },
                _Loader({"AAA": frame}),
                _MovingAverageCross(30),
                tmp_path,
            )
        finally:
            bench_mod.resolve_benchmark = original
        return metrics, frame

    def test_benchmark_return_excludes_the_warmup_window(self, tmp_path):
        frame = self._frame()
        # The benchmark doubles inside the warm-up and is flat afterwards, so
        # the full-window and evaluated-window numbers cannot be confused.
        bench = pd.Series(100.0, index=frame.index)
        bench.iloc[: self.boundary] = np.linspace(100.0, 200.0, self.boundary)
        bench.iloc[self.boundary :] = 200.0

        graded_all, _ = self._run(tmp_path / "a", {}, bench)
        graded_after, _ = self._run(
            tmp_path / "b", {"warmup_bars": self.boundary}, bench
        )

        # Full window: 100 -> 200 = +100%.
        assert graded_all["benchmark_return"] == pytest.approx(1.0, abs=1e-6)
        # Evaluated window: the benchmark is flat at 200 throughout = 0%.
        assert graded_after["benchmark_return"] == pytest.approx(0.0, abs=1e-6)

    def test_excess_return_uses_the_same_window_as_total_return(self, tmp_path):
        frame = self._frame()
        bench = pd.Series(100.0, index=frame.index)
        bench.iloc[: self.boundary] = np.linspace(100.0, 200.0, self.boundary)
        bench.iloc[self.boundary :] = 200.0

        metrics, _ = self._run(tmp_path, {"warmup_bars": self.boundary}, bench)

        assert metrics["excess_return"] == pytest.approx(
            round(metrics["total_return"] - metrics["benchmark_return"], 6), abs=1e-6
        )
        # And the strategy's own window really is the short one, or the
        # assertion above would hold trivially for the full window too.
        assert metrics["benchmark_return"] == pytest.approx(0.0, abs=1e-6)
