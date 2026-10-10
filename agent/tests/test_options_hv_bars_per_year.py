"""Options pricing uses the supplied cadence or a causal per-bar estimate.

Cross-market pricing may use timestamps known at the current bar only.
Finished-run reporting metrics may use their full span, but reusing that span
to price earlier trades creates lookahead.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.options_portfolio import historical_volatility, run_options_backtest
from src.quantlib.options import bs_price

DEFAULT_IV = 0.3
WINDOW = 30


def _annualised_hv(close: pd.Series, bars_per_year: float) -> pd.Series:
    """Independent oracle: rolling log-return std scaled by ``sqrt(bars/yr)``."""
    log_ret = np.log(close / close.shift(1))
    scaled = log_ret.rolling(window=WINDOW).std() * math.sqrt(bars_per_year)
    return scaled.fillna(DEFAULT_IV)


def _alternating_close(bars: int = 60) -> pd.Series:
    """Deterministic zigzag whose 30-bar rolling std is non-zero and stable."""
    steps = np.where(np.arange(bars) % 2 == 0, 0.02, -0.015)
    index = pd.date_range("2024-01-01", periods=bars, freq="D")
    return pd.Series(100.0 * np.exp(np.cumsum(steps)), index=index)


def test_hv_annualises_on_the_supplied_cadence() -> None:
    """A 365-bar venue must scale by sqrt(365), not the equity-market 252."""
    close = _alternating_close()

    hv = historical_volatility(close, default_iv=DEFAULT_IV, bars_per_year=365)

    pd.testing.assert_series_equal(hv, _annualised_hv(close, 365))
    # The whole point: the same series on another cadence is another volatility.
    assert not hv.equals(historical_volatility(close, default_iv=DEFAULT_IV, bars_per_year=252))


def test_hv_defaults_to_252_so_daily_equity_runs_are_unchanged() -> None:
    """The default keeps every existing caller and the pinned warm-up test."""
    close = _alternating_close()

    pd.testing.assert_series_equal(
        historical_volatility(close),
        _annualised_hv(close, 252),
    )
    pd.testing.assert_series_equal(
        historical_volatility(close),
        historical_volatility(close, bars_per_year=252),
    )


def test_hv_none_resolves_daily_return_cadence_causally() -> None:
    """Daily return intervals annualise to calendar days, without future bars."""
    close = _alternating_close()
    expected_factor = 365.25
    assert expected_factor != 252, "fixture must exercise a non-default factor"

    hv = historical_volatility(close, default_iv=DEFAULT_IV, bars_per_year=None)

    pd.testing.assert_series_equal(hv, _annualised_hv(close, expected_factor))


@pytest.mark.parametrize("frequency,yearly", [("1min", 365.25 * 1440), ("1h", 365.25 * 24), ("7D", 365.25 / 7)])
def test_cross_market_hv_preserves_elapsed_subday_and_weekly_intervals(frequency, yearly):
    close = _alternating_close()
    close.index = pd.date_range("2024-01-01", periods=len(close), freq=frequency)
    pd.testing.assert_series_equal(
        historical_volatility(close, bars_per_year=None), _annualised_hv(close, yearly),
    )


@pytest.mark.parametrize("frequency", ["D", "B", "1h", "1min"])
def test_future_cadence_changes_cannot_change_past_volatility(frequency):
    close = _alternating_close()
    past_dates = pd.date_range("2024-01-01", periods=45, freq=frequency)
    future_dates = pd.date_range(past_dates[-1] + pd.Timedelta(days=10), periods=15, freq="7D")
    close.index = past_dates.append(future_dates)
    past = historical_volatility(close.iloc[:45], bars_per_year=None)
    extended = historical_volatility(close, bars_per_year=None).iloc[:45]
    pd.testing.assert_series_equal(past, extended)


class _SingleCodeLoader:
    """Serves one deterministic daily series, ignoring the requested window."""

    name = "okx"

    def __init__(self, close: pd.Series) -> None:
        self._close = close

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        frame = pd.DataFrame(
            {
                "close": self._close.to_numpy(),
                "open": self._close.to_numpy(),
            },
            index=self._close.index,
        )
        return {code: frame for code in codes}


class _OpenOneCallEngine:
    """Opens one at-the-money call, dated so it fills on the next bar."""

    def __init__(self, signal_date: str, strike: float, expiry: str) -> None:
        self._signal_date = signal_date
        self._strike = strike
        self._expiry = expiry

    def generate(self, data_map):  # noqa: ANN001
        return [
            {
                "date": self._signal_date,
                "action": "open",
                "underlying": "BTC-USDT",
                "legs": [
                    {
                        "type": "call",
                        "strike": self._strike,
                        "expiry": self._expiry,
                        "qty": 1,
                    }
                ],
            }
        ]


def _run_one_call(tmp_path: Path, bars_per_year: int | None) -> tuple[float, float, float]:
    """Open one ATM 30-day call and return (recorded price, spot, sigma at fill)."""
    close = _alternating_close()
    signal_bar = close.index[40]
    fill_bar = close.index[41]
    strike = float(close.at[fill_bar])
    expiry = str((fill_bar + pd.Timedelta(days=30)).date())

    result = run_options_backtest(
        {
            "codes": ["BTC-USDT"],
            "start_date": str(close.index[0].date()),
            "end_date": str(close.index[-1].date()),
            "source": "okx",
            "engine": "options",
            "initial_cash": 1_000_000.0,
            "options_config": {
                "risk_free_rate": 0.05,
                "default_iv": DEFAULT_IV,
                "margin_enabled": False,
            },
        },
        _SingleCodeLoader(close),
        _OpenOneCallEngine(str(signal_bar.date()), strike, expiry),
        tmp_path,
        bars_per_year=bars_per_year,
    )

    trades = pd.read_csv(tmp_path / "artifacts" / "trades.csv")
    opens = trades[trades["side"] == "buy"]
    assert len(opens) == 1, f"expected exactly one fill, got {trades.to_dict('records')}"
    assert result["trade_count"] == 1
    return float(opens.iloc[0]["price"]), strike, float(close.at[fill_bar])


def test_options_backtest_prices_the_leg_on_the_run_cadence(tmp_path: Path) -> None:
    """End to end: a 365-bar run must fill at the 365-annualised vol.

    This is the defect the unit tests above cannot catch on their own -- the
    factor has to survive the call site, not just exist as a parameter.
    """
    close = _alternating_close()
    fill_bar = close.index[41]

    price, strike, spot = _run_one_call(tmp_path, bars_per_year=365)

    sigma_365 = float(_annualised_hv(close, 365).at[fill_bar])
    sigma_252 = float(_annualised_hv(close, 252).at[fill_bar])
    expiry_years = 30 / 365.0
    expected = bs_price(spot, strike, expiry_years, 0.05, sigma_365, "call")
    stale = bs_price(spot, strike, expiry_years, 0.05, sigma_252, "call")

    assert price == pytest.approx(expected, abs=1e-4)
    # Quantifies what the hardcoded factor cost: the stale mark sits ~16% below
    # the price this leg should have filled at, and that number is what reached
    # trades.csv, greeks.csv and the run card.
    assert expected > stale
    assert (expected - stale) / expected == pytest.approx(0.16, abs=0.01)


def test_options_backtest_cross_market_none_prices_on_causal_cadence(
    tmp_path: Path,
) -> None:
    """``bars_per_year=None`` must reach pricing too, not just the metrics."""
    close = _alternating_close()
    fill_bar = close.index[41]
    factor = 365.25

    price, strike, spot = _run_one_call(tmp_path, bars_per_year=None)

    sigma = float(_annualised_hv(close, factor).at[fill_bar])
    expected = bs_price(spot, strike, 30 / 365.0, 0.05, sigma, "call")
    assert price == pytest.approx(expected, abs=1e-4)


def _run_call_prefix(path, count, bars_per_year):
    dates = pd.date_range('2026-01-01', periods=80)
    values = 100 * np.exp(np.cumsum(np.where(np.arange(80) % 2, 0.02, -0.015)))
    close = pd.Series(values[:count], index=dates[:count])

    class Loader:
        def fetch(self, codes, *args, **kwargs):
            return {code: pd.DataFrame({'open': close, 'close': close}) for code in codes}

    class Signals:
        def generate(self, data):
            return [{
                'date': str(dates[40].date()), 'action': 'open', 'underlying': 'BTC-USDT',
                'legs': [{'type': 'call', 'strike': float(values[41]),
                          'expiry': str((dates[41] + pd.Timedelta(days=30)).date()), 'qty': 1}],
            }]

    run_options_backtest(
        {'codes': ['BTC-USDT', 'AAPL.US'], 'source': 'auto', 'engine': 'options',
         'start_date': str(dates[0].date()), 'end_date': str(dates[count-1].date()),
         'initial_cash': 1_000_000., 'options_config': {'margin_enabled': False}},
        Loader(), Signals(), path, bars_per_year=bars_per_year,
    )
    trades = pd.read_csv(path / 'artifacts' / 'trades.csv')
    return float(trades[trades['side'] == 'buy'].iloc[0]['price'])


@pytest.mark.parametrize('factor', [None, 365], ids=['cross-market', 'fixed-cadence-control'])
def test_future_bars_do_not_reprice_a_past_option_fill(tmp_path, factor):
    prefix = _run_call_prefix(tmp_path / 'prefix', 45, factor)
    extended = _run_call_prefix(tmp_path / 'extended', 80, factor)
    assert extended == pytest.approx(prefix, abs=1e-10)
