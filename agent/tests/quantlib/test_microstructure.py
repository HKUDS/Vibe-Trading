"""Tests for microstructure metrics (VPIN, Roll spread, Amihud, Kyle's Lambda)."""

from __future__ import annotations

import numpy as np
import pytest

from src.quantlib.microstructure import (
    amihud_illiquidity,
    kyles_lambda,
    roll_effective_spread,
    vpin,
)


class TestMicrostructureMetrics:
    """Validate microstructure indicators and edge cases."""

    def test_roll_effective_spread(self) -> None:
        # Oscillating prices bounce between bid/ask (100.0, 101.0, 100.0, 101.0, ...)
        # dp = [+1, -1, +1, -1, +1, -1] -> cov(dp_t, dp_{t-1}) < 0
        prices = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
        spread = roll_effective_spread(prices)
        assert spread > 0.0
        assert spread == pytest.approx(2.0, abs=0.2)

        # Monotonic drift (no negative autocovariance) yields 0.0
        monotonic = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
        assert roll_effective_spread(monotonic) == 0.0

    def test_amihud_illiquidity(self) -> None:
        returns = [0.01, -0.02, 0.015]
        dollar_vol = [1_000_000, 2_000_000, 1_500_000]
        ratio = amihud_illiquidity(returns, dollar_vol)
        # mean of [0.01/1M, 0.02/2M, 0.015/1.5M] = [1e-8, 1e-8, 1e-8] -> 1e-8
        assert ratio == pytest.approx(1e-8)

    def test_kyles_lambda(self) -> None:
        # Price change = 0.005 * OrderFlow
        flow = [100.0, -200.0, 300.0, -100.0]
        dp = [0.5, -1.0, 1.5, -0.5]
        lam = kyles_lambda(dp, flow)
        assert lam == pytest.approx(0.005)

    def test_vpin(self) -> None:
        # Total volume = (100+100) + (200+100) + (300+100) + (100+100) = 1100.
        # With bucket_size = 200, produces 5 completed buckets.
        buy_vol = np.array([100.0, 200.0, 300.0, 100.0])
        sell_vol = np.array([100.0, 100.0, 100.0, 100.0])
        res = vpin(buy_vol, sell_vol, bucket_size=200.0, n_buckets=3)
        assert len(res) >= 3
        assert np.all(res >= 0.0)
        assert np.all(res <= 1.0)

    def test_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="at least 4 points"):
            roll_effective_spread([10.0, 11.0])
        with pytest.raises(ValueError, match="matching shapes"):
            amihud_illiquidity([0.01], [100.0, 200.0])
