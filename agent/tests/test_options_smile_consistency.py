"""Regression: a leg must be marked at the vol it was opened at.

The engine applied the IV smile when pricing an opening leg but marked every
position at the flat at-the-money vol, so a position booked a profit the instant
it existed. Measured on a 30-day call at ``skew=-0.15``, ``curvature=0.05``,
``S=100``, ``r=0``: +16.7% of premium at 10% out-of-the-money and +93.0% at 20%.
That flows straight into the equity curve and every metric derived from it.

The same flat vol was also used for the Greeks and for the American
early-exercise continuation value, so those are pinned here too.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.options_portfolio import (
    bs_price,
    iv_smile_adjustment,
    leg_iv,
    run_options_backtest,
)

_DATES = pd.bdate_range("2025-01-01", periods=4)
_BARS = pd.DataFrame(
    {
        "open": [100.0, 100.0, 100.0, 100.0],
        "high": [100.0, 100.0, 100.0, 100.0],
        "low": [100.0, 100.0, 100.0, 100.0],
        "close": [100.0, 100.0, 100.0, 100.0],
        "volume": [1000, 1000, 1000, 1000],
    },
    index=_DATES,
)

_INITIAL_CASH = 100_000.0
# Fewer than 30 bars, so historical_volatility falls back to a flat 0.3.
_BASE_IV = 0.3


class _FlatLoader:
    name = "yfinance"

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        return {"SPY": _BARS.copy()}


def _open_call(strike: float):
    class _Engine:
        def generate(self, data_map):  # noqa: ANN001
            return [
                {
                    "date": "2025-01-01",
                    "action": "open",
                    "underlying": "SPY",
                    "legs": [
                        {
                            "type": "call",
                            "strike": strike,
                            "expiry": "2025-02-21",
                            "qty": 10,
                        }
                    ],
                }
            ]

    return _Engine()


def _run(tmp_path: Path, *, strike: float, skew: float, curvature: float):
    run_options_backtest(
        {
            "codes": ["SPY"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-07",
            "source": "yfinance",
            "engine": "options",
            "initial_cash": _INITIAL_CASH,
            "commission": 0.0,
            "options_config": {
                "risk_free_rate": 0.0,
                "contract_multiplier": 1.0,
                "iv_skew": skew,
                "iv_curvature": curvature,
            },
        },
        _FlatLoader(),
        _open_call(strike),
        tmp_path,
    )
    return pd.read_csv(tmp_path / "artifacts" / "equity.csv")


class TestLegIv:
    """The single definition of the vol a leg is priced at."""

    def test_a_flat_surface_returns_the_base_vol(self):
        assert leg_iv(100.0, 110.0, _BASE_IV, 0.0, 0.0) == _BASE_IV

    def test_a_smile_matches_the_smile_model(self):
        assert leg_iv(100.0, 110.0, _BASE_IV, -0.15, 0.05) == iv_smile_adjustment(
            100.0, 110.0, _BASE_IV, -0.15, 0.05
        )

    def test_at_the_money_is_unchanged_by_the_smile(self):
        assert leg_iv(100.0, 100.0, _BASE_IV, -0.15, 0.05) == pytest.approx(_BASE_IV)


class TestDayZeroPnl:
    """Opening a position must not move equity on the bar that opens it."""

    @pytest.mark.parametrize("strike", [80.0, 95.0, 100.0, 110.0, 120.0])
    def test_day_zero_equity_is_unchanged_under_a_smile(self, tmp_path, strike):
        equity = _run(tmp_path, strike=strike, skew=-0.15, curvature=0.05)

        assert float(equity.iloc[0]["equity"]) == pytest.approx(_INITIAL_CASH, abs=1e-6)

    @pytest.mark.parametrize("strike", [95.0, 110.0])
    def test_day_zero_equity_is_unchanged_without_a_smile(self, tmp_path, strike):
        equity = _run(tmp_path, strike=strike, skew=0.0, curvature=0.0)

        assert float(equity.iloc[0]["equity"]) == pytest.approx(_INITIAL_CASH, abs=1e-6)

    def test_a_flat_underlying_never_moves_equity(self, tmp_path):
        # Spot, vol and rate are all constant, so the only P&L that can appear
        # is time decay — which must be identical under either vol surface.
        smile = _run(tmp_path / "smile", strike=110.0, skew=-0.15, curvature=0.05)
        flat = _run(tmp_path / "flat", strike=110.0, skew=0.0, curvature=0.0)

        assert float(smile.iloc[0]["equity"]) == pytest.approx(
            float(flat.iloc[0]["equity"]), abs=1e-6
        )


class TestGreeksUseTheLegVol:
    """Greeks priced at a vol the leg is not marked at are a silent error."""

    def test_greeks_are_reported_at_the_smile_vol(self, tmp_path):
        run_options_backtest(
            {
                "codes": ["SPY"],
                "start_date": "2025-01-01",
                "end_date": "2025-01-07",
                "source": "yfinance",
                "engine": "options",
                "initial_cash": _INITIAL_CASH,
                "commission": 0.0,
                "options_config": {
                    "risk_free_rate": 0.0,
                    "contract_multiplier": 1.0,
                    "iv_skew": -0.15,
                    "iv_curvature": 0.05,
                },
            },
            _FlatLoader(),
            _open_call(110.0),
            tmp_path,
        )
        greeks = pd.read_csv(tmp_path / "artifacts" / "greeks.csv")

        from backtest.engines.options_portfolio import bs_greeks

        smile_vol = leg_iv(100.0, 110.0, _BASE_IV, -0.15, 0.05)
        expiry = pd.Timestamp("2025-02-21")
        time_to_expiry = max((expiry - _DATES[0]).days / 365.0, 0.001)
        expected = bs_greeks(100.0, 110.0, time_to_expiry, 0.0, smile_vol, "call")

        assert float(greeks.iloc[0]["delta"]) == pytest.approx(
            expected["delta"] * 10, rel=1e-6
        )

    def test_the_smile_vol_differs_from_the_flat_vol_for_this_leg(self):
        # Guards the test above from silently passing on an unchanged surface.
        assert leg_iv(100.0, 110.0, _BASE_IV, -0.15, 0.05) != _BASE_IV
        assert bs_price(100.0, 110.0, 30 / 365, 0.0, _BASE_IV, "call") != bs_price(
            100.0, 110.0, 30 / 365, 0.0, leg_iv(100.0, 110.0, _BASE_IV, -0.15, 0.05), "call"
        )
