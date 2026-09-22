"""One annualisation convention for cross-market runs (issue #1237).

A basket spanning markets has no single per-market bar count, so the runner
passes ``bars_per_year=None`` (``runner.py``: *"Cross-market: use calendar-day
annualization"*). Four consumers have to agree on what that means — portfolio
metrics, the risk x-ray, options metrics, and validation — or one run card
reports a Sharpe and an annualised volatility computed on different footings.

These tests pin all four to ``metrics.effective_bars_per_year``. They fail if
any consumer grows its own copy of the span derivation and drifts.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest.engines.options_portfolio import _calc_options_metrics
from backtest.metrics import calc_bars_per_year, calc_metrics, effective_bars_per_year
from backtest.risk_xray import compute_risk_xray
from backtest.validation import _sharpe, run_validation


def _zigzag(n: int, base: float, step: float, period: int) -> list[float]:
    """Prices with both up and down moves, so downside statistics exist."""
    return [base + (i % period) * step - step * (period - 1) / 2 for i in range(n)]


class TestEffectiveBarsPerYear:
    def test_daily_bars_over_a_full_year(self):
        idx = pd.date_range("2024-01-01", periods=253, freq="B")
        span_years = (idx[-1] - idx[0]).days / 365.25
        assert effective_bars_per_year(idx) == int(253 / span_years)

    def test_span_shorter_than_a_day_counts_as_one_year(self):
        # Two bars on the same calendar day: no measurable span, so the series
        # annualises to itself rather than exploding on a near-zero divisor.
        idx = pd.DatetimeIndex(["2024-01-01T09:30", "2024-01-01T15:00"])
        assert effective_bars_per_year(idx) == 2

    def test_empty_index_falls_back_to_default(self):
        assert effective_bars_per_year(pd.DatetimeIndex([])) == 252
        assert effective_bars_per_year(pd.DatetimeIndex([]), default=365) == 365

    def test_non_datetime_index_has_no_measurable_span(self):
        # An integer index carries no ``days``; the series annualises to its
        # own length rather than raising.
        assert effective_bars_per_year(pd.Index([0, 1, 2, 3])) == 4


class TestConsumersShareTheConvention:
    """Every ``bars_per_year=None`` consumer resolves the same factor."""

    idx = pd.date_range("2024-01-01", periods=120, freq="B")

    @property
    def expected_bpy(self) -> int:
        return effective_bars_per_year(self.idx)

    def test_risk_xray(self):
        closes = pd.DataFrame(
            {
                "AAA": _zigzag(120, 100.0, 2.0, 5),
                "BBB": _zigzag(120, 50.0, 1.0, 7),
            },
            index=self.idx,
        )
        weights = {"AAA": 0.5, "BBB": 0.5}
        result = compute_risk_xray(closes, weights, min_history=10, periods_per_year=None)

        port = (closes.pct_change().dropna() * pd.Series(weights)).sum(axis=1)
        expected = effective_bars_per_year(port.index)
        assert result["volatility"]["annualized_vol"] == pytest.approx(
            port.std(ddof=1) * math.sqrt(expected)
        )

    def test_options_metrics(self):
        equity = pd.Series(_zigzag(120, 100_000.0, 500.0, 5), index=self.idx)
        metrics = _calc_options_metrics(equity, 100_000.0, [], bars_per_year=None)

        returns = equity.pct_change(fill_method=None).iloc[1:]
        # Options metrics round their reported ratios to 4 decimals.
        assert metrics["sharpe"] == pytest.approx(
            returns.mean() / returns.std() * math.sqrt(self.expected_bpy), abs=5e-5
        )

    def test_validation(self):
        equity = pd.Series(_zigzag(120, 100_000.0, 500.0, 5), index=self.idx)
        result = run_validation(
            {"validation": {"bootstrap": {"n_bootstrap": 10}}},
            equity,
            [],
            100_000.0,
            bars_per_year=None,
        )

        returns = equity.pct_change().dropna().to_numpy()
        assert result["bootstrap"]["observed_sharpe"] == pytest.approx(
            round(_sharpe(returns, self.expected_bpy), 4)
        )

    def test_portfolio_metrics(self):
        equity = pd.Series(np.linspace(100_000.0, 130_000.0, 120), index=self.idx)
        metrics = calc_metrics(equity, [], 100_000.0, bars_per_year=None)

        growth = 1.3
        assert metrics["annual_return"] == pytest.approx(
            growth ** (self.expected_bpy / 120) - 1, rel=1e-6
        )


class TestSingleMarketAnnualisationChecksTheServedData:
    """The declared interval is a request, not a fact about what arrived.

    A loader may legitimately serve coarser bars than asked for — the local
    loader cannot upsample a daily file to ``1H`` and only logs a warning —
    and annualising at the declared rate then scales CAGR, Sharpe and the
    annualised volatility by the ratio between the two.

    The comparison is on bar *spacing*, not on bars per calendar year: a
    calendar-year count is a property of the window as much as of the data,
    so it flags correctly served short runs (see the window-length tests).
    """

    @staticmethod
    def _frame(index) -> dict:
        return {"600519.SH": pd.DataFrame({"close": [10.0] * len(index)}, index=index)}

    @staticmethod
    def _session(days: int, per_day: int, freq: str, start: str = "2026-09-07") -> pd.DatetimeIndex:
        """Intraday bars inside a trading session, so the index carries the
        overnight gaps a real one does."""
        stamps: list[pd.Timestamp] = []
        for day in pd.bdate_range(start, periods=days):
            stamps += list(
                pd.date_range(day.replace(hour=9, minute=30), periods=per_day, freq=freq)
            )
        return pd.DatetimeIndex(stamps)

    def test_matching_declaration_keeps_the_per_source_table(self):
        """A correctly served run keeps the trading-day table it always had,
        rather than drifting to a count measured off its own window."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        assert _annualisation_bars("1D", "tushare", data, ["600519.SH"]) == 252

    def test_declared_intraday_against_daily_bars_uses_the_matched_interval(self):
        """The corrected count still comes from the per-source table, looked up
        with the interval the spacing actually matches."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        resolved = _annualisation_bars("1H", "tushare", data, ["600519.SH"])

        assert calc_bars_per_year("1H", "tushare") > 1000   # the declaration is intraday
        assert resolved == calc_bars_per_year("1D", "tushare") == 252

    # --- window length must not decide the outcome (issue found in review) ---

    def test_five_daily_bars_keep_the_declared_count(self):
        """Five bars is a quick check, not a granularity change."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.bdate_range("2026-09-08", periods=5))
        assert _annualisation_bars("1D", "yahoo", data, ["600519.SH"]) == 252

    def test_five_daily_bars_starting_monday_keep_the_declared_count(self):
        """Calendar alignment must not change the verdict: a Monday-start week
        spans four calendar days and a Tuesday-start week spans six, so a
        bars-per-calendar-year measurement flags one and not the other."""
        from backtest.runner import _annualisation_bars

        monday = pd.bdate_range("2026-09-07", periods=5)
        assert monday[0].day_name() == "Monday"
        assert (monday[-1] - monday[0]).days == 4

        data = self._frame(monday)
        assert _annualisation_bars("1D", "yahoo", data, ["600519.SH"]) == 252

    def test_one_week_of_hourly_bars_keeps_the_declared_count(self):
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=7, freq="1h"))
        declared = calc_bars_per_year("1H", "yahoo")
        assert _annualisation_bars("1H", "yahoo", data, ["600519.SH"]) == declared

    def test_one_session_of_minute_bars_keeps_the_declared_count(self):
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=1, per_day=390, freq="1min"))
        declared = calc_bars_per_year("1m", "yahoo")
        assert _annualisation_bars("1m", "yahoo", data, ["600519.SH"]) == declared

    # --- session shapes that a spacing measurement must tolerate ---

    def test_a_share_four_hour_session_keeps_the_declared_count(self):
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=4, freq="1h"))
        assert _annualisation_bars("1H", "tushare", data, ["600519.SH"]) == \
            calc_bars_per_year("1H", "tushare")

    def test_a_trading_halt_does_not_change_the_verdict(self):
        """The median reports the regular spacing; one long gap cannot outvote it."""
        from backtest.runner import _annualisation_bars

        index = pd.bdate_range("2025-01-06", periods=60).append(
            pd.bdate_range("2025-08-01", periods=60)
        )
        assert _annualisation_bars("1D", "tushare", self._frame(index), ["600519.SH"]) == 252

    def test_crypto_daily_is_not_tripped_by_the_check(self):
        """365-day markets keep their own table entry."""
        from backtest.runner import _annualisation_bars

        n = 700
        data = {"BTC-USDT": pd.DataFrame(
            {"close": [10.0] * n}, index=pd.date_range("2024-01-02", periods=n, freq="D")
        )}
        assert _annualisation_bars("1D", "okx", data, ["BTC-USDT"]) == 365

    # --- degenerate inputs ---

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"600519.SH": pd.DataFrame({"close": []})},
            # Too few bars for a median that survives a weekend gap.
            {"600519.SH": pd.DataFrame(
                {"close": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-11", "2026-09-14"])
            )},
        ],
    )
    def test_unmeasurable_data_falls_back_to_the_declaration(self, data):
        from backtest.runner import _annualisation_bars

        assert _annualisation_bars("1D", "tushare", data, ["600519.SH"]) == 252

    def test_only_price_frames_are_measured(self):
        """Injected fundamental panels must not decide the annualisation."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        data["_fundamentals"] = pd.DataFrame(
            {"pe": [1.0] * 5}, index=pd.date_range("2024-01-02", periods=5, freq="YE")
        )
        assert _annualisation_bars("1D", "tushare", data, ["600519.SH"]) == 252

    # --- weekly / monthly files, and spacing wider than any supported interval ---

    @pytest.mark.parametrize("declared", ["1D", "1H"])
    def test_a_weekly_file_is_annualised_as_weekly(self, declared, caplog):
        """A weekly file declared finer is read as ``1W``: 52 a year.

        Keeping the declaration was the bug -- a weekly file declared ``1H``
        annualised at 1,764 bars a year.
        """
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-05", periods=60, freq="W-FRI"))
        with caplog.at_level("WARNING", logger="backtest.runner"):
            resolved = _annualisation_bars(declared, "tushare", data, ["600519.SH"])

        assert resolved == 52
        assert any("annualising as 1W (52 bars/year)" in r.getMessage() for r in caplog.records)

    def test_monthly_bars_are_twelve_a_year(self):
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2020-01-01", periods=48, freq="MS"))
        assert _annualisation_bars("1D", "yahoo", data, ["600519.SH"]) == 12

    @pytest.mark.parametrize(("declared", "freq"), [("1W", "W-FRI"), ("1M", "BME")])
    def test_a_declared_weekly_or_monthly_run_keeps_its_count_silently(self, declared, freq, caplog):
        """Weekly and monthly are intervals now (#1479): no mismatch report."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2020-01-01", periods=60, freq=freq))
        with caplog.at_level("WARNING", logger="backtest.runner"):
            resolved = _annualisation_bars(declared, "tushare", data, ["600519.SH"])

        assert resolved == {"1W": 52, "1M": 12}[declared]
        assert caplog.records == []

    @pytest.mark.parametrize("declared", ["1W", "1M"])
    def test_a_period_run_served_daily_bars_is_caught(self, declared, caplog):
        """The spacing check covers the new intervals too: daily bars under a
        weekly or monthly declaration annualise as daily, and say so."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.bdate_range("2024-01-01", periods=120))
        with caplog.at_level("WARNING", logger="backtest.runner"):
            resolved = _annualisation_bars(declared, "tushare", data, ["600519.SH"])

        assert resolved == 252
        assert any("annualising as 1D (252 bars/year)" in r.getMessage() for r in caplog.records)

    def test_a_quarterly_file_is_annualised_from_the_calendar(self, caplog):
        """Wider than every supported interval: four bars a year, from the
        spacing, since no interval has a count to look up."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2015-03-31", periods=40, freq="QE"))
        with caplog.at_level("WARNING", logger="backtest.runner"):
            resolved = _annualisation_bars("1D", "tushare", data, ["600519.SH"])

        assert resolved == 4
        assert any("wider than any supported interval" in r.getMessage() for r in caplog.records)

    def test_a_daily_series_over_a_holiday_week_is_not_read_as_weekly(self, caplog):
        """Five daily bars around Christmas measure a two-day median: the
        declaration stands, the report states the spacings, and the count is
        not recomputed from a spacing that is only gaps."""
        from backtest.runner import _annualisation_bars

        index = pd.to_datetime(["2025-12-22", "2025-12-23", "2025-12-24", "2025-12-26", "2025-12-29"])
        with caplog.at_level("WARNING", logger="backtest.runner"):
            resolved = _annualisation_bars("1D", "yahoo", self._frame(index), ["600519.SH"])

        assert resolved == 252
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "matches no supported interval" in message
        assert "re-run" not in message

    def test_sub_minute_bars_keep_the_declaration_and_say_so(self, caplog):
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2026-09-07 09:30", periods=200, freq="10s"))
        with caplog.at_level("WARNING", logger="backtest.runner"):
            resolved = _annualisation_bars("1m", "yahoo", data, ["600519.SH"])

        assert resolved == calc_bars_per_year("1m", "yahoo")
        assert any("matches no supported interval" in r.getMessage() for r in caplog.records)

    # --- properties the code relies on, each pinned against its mutation ---

    def test_hourly_bars_declared_30m_switch_to_the_hourly_count(self):
        """Neighbouring intervals differ by 2x, above the 1.5 gate."""
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=7, freq="1h"))
        assert _annualisation_bars("30m", "yahoo", data, ["600519.SH"]) == calc_bars_per_year("1H", "yahoo")

    def test_four_hour_bars_declared_1h_switch_to_the_four_hour_count(self):
        """A 4x mismatch must switch too: the gate is 1.5, not a larger number."""
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=2, freq="4h"))
        assert _annualisation_bars("1H", "yahoo", data, ["600519.SH"]) == calc_bars_per_year("4H", "yahoo")

    def test_spacing_inside_the_tolerance_keeps_the_declaration(self):
        """Bars 72 minutes apart declared 1H sit at ratio 1.2: not a mismatch."""
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=5, freq="72min"))
        assert _annualisation_bars("1H", "yahoo", data, ["600519.SH"]) == calc_bars_per_year("1H", "yahoo")

    def test_spacing_near_a_neighbouring_interval_resolves_to_it(self):
        """Bars 72 minutes apart declared 30m are a mismatch (ratio 2.4) whose
        nearest interval, 1H, sits inside the tolerance (ratio 1.2): the run
        annualises as 1H. A tighter gate would find no match and keep 30m."""
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=5, freq="72min"))
        assert _annualisation_bars("30m", "yahoo", data, ["600519.SH"]) == calc_bars_per_year("1H", "yahoo")

    def test_bars_finer_than_declared_switch_as_well(self):
        """The gate is two-sided: hourly bars declared 1D annualise as 1H."""
        from backtest.runner import _annualisation_bars

        data = self._frame(self._session(days=5, per_day=7, freq="1h"))
        assert _annualisation_bars("1D", "yahoo", data, ["600519.SH"]) == calc_bars_per_year("1H", "yahoo")

    def test_three_bars_are_too_few_to_overrule_the_declaration(self):
        """Two differences cannot outvote one gap, so the declaration stands."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.bdate_range("2026-09-08", periods=3))
        assert _annualisation_bars("1H", "yahoo", data, ["600519.SH"]) == calc_bars_per_year("1H", "yahoo")

    def test_only_price_frames_are_measured_even_when_a_panel_is_longer(self):
        """A longer injected panel must not win the measurement by length."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        data["_fundamentals"] = pd.DataFrame(
            {"pe": [1.0] * 1000}, index=pd.date_range("2024-01-02", periods=1000, freq="h")
        )
        assert _annualisation_bars("1D", "tushare", data, ["600519.SH"]) == 252

    def test_the_longest_price_frame_decides(self):
        """A short hourly stub beside a long daily series does not switch the run."""
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        data["000001.SZ"] = pd.DataFrame(
            {"close": [10.0] * 10}, index=pd.date_range("2024-01-02 09:30", periods=10, freq="h")
        )
        assert _annualisation_bars("1D", "tushare", data, ["600519.SH", "000001.SZ"]) == 252

    def test_the_report_is_handed_to_the_caller_for_the_run_card(self):
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        warnings: list[str] = []
        resolved = _annualisation_bars("1H", "tushare", data, ["600519.SH"], warnings=warnings)

        assert resolved == 252
        assert len(warnings) == 1 and "annualising as 1D" in warnings[0]

    def test_a_clean_run_hands_over_no_report(self):
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        warnings: list[str] = []
        _annualisation_bars("1D", "tushare", data, ["600519.SH"], warnings=warnings)

        assert warnings == []

    def test_mismatch_is_logged(self, caplog):
        from backtest.runner import _annualisation_bars

        data = self._frame(pd.date_range("2024-01-02", periods=654, freq="B"))
        with caplog.at_level("WARNING", logger="backtest.runner"):
            _annualisation_bars("1H", "tushare", data, ["600519.SH"])

        assert any("1H" in r.getMessage() for r in caplog.records)
