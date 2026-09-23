"""Tests for Hierarchical Risk Parity and portfolio allocation algorithms."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.quantlib.portfolio import (
    correlation_distance,
    hierarchical_risk_parity,
    inverse_variance_weights,
)


class TestPortfolioAllocation:
    """Validate HRP and inverse-variance weighting properties."""

    def test_correlation_distance_properties(self) -> None:
        # Distance is 0 on diagonal, in [0, 1] for rho in [0, 1]
        corr = np.array([
            [1.0, 0.5, -0.5],
            [0.5, 1.0, 0.0],
            [-0.5, 0.0, 1.0],
        ])
        dist = correlation_distance(corr)
        assert np.allclose(np.diag(dist), 0.0)
        assert dist[0, 1] == pytest.approx(np.sqrt(0.5 * (1.0 - 0.5)))
        assert dist[0, 2] == pytest.approx(np.sqrt(0.5 * (1.0 - (-0.5))))

    def test_inverse_variance_weights_sum_to_one(self) -> None:
        cov = np.array([
            [0.04, 0.01],
            [0.01, 0.16],
        ])
        w = inverse_variance_weights(cov)
        assert len(w) == 2
        assert np.sum(w) == pytest.approx(1.0)
        # Lower variance gets higher weight: 1/0.04 = 25, 1/0.16 = 6.25 -> 25/31.25 = 0.8
        assert w[0] == pytest.approx(0.8)
        assert w[1] == pytest.approx(0.2)

    def test_hrp_weights_dataframe_and_sum(self) -> None:
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
        # Generate positive definite covariance matrix
        rng = np.random.default_rng(42)
        A = rng.standard_normal((4, 4))
        cov_mat = A @ A.T + np.eye(4) * 0.1
        cov_df = pd.DataFrame(cov_mat, index=tickers, columns=tickers)

        weights = hierarchical_risk_parity(cov_df)
        assert isinstance(weights, pd.Series)
        assert list(weights.index) == tickers
        assert np.sum(weights) == pytest.approx(1.0)
        assert np.all(weights >= 0.0)

    def test_hrp_single_asset_case(self) -> None:
        cov = np.array([[0.04]])
        w = hierarchical_risk_parity(cov)
        assert len(w) == 1
        assert w[0] == pytest.approx(1.0)

    def test_hrp_invalid_inputs(self) -> None:
        with pytest.raises(ValueError, match="square 2-D"):
            hierarchical_risk_parity(np.array([1.0, 2.0]))
        with pytest.raises(ValueError, match="strictly positive"):
            hierarchical_risk_parity(np.array([[0.0, 0.0], [0.0, 0.04]]))

    def test_hrp_rejects_a_corr_reordered_relative_to_cov(self) -> None:
        # corr is positionally aligned with cov internally; a caller-supplied
        # corr in a different row/column order is silently wrong data, not a
        # cosmetic difference, and must be rejected rather than producing a
        # plausible-looking wrong allocation.
        tickers = ["AAPL", "MSFT", "GOOGL", "TLT"]
        std = np.array([0.30, 0.28, 0.32, 0.08])
        corr_vals = np.array(
            [
                [1.00, 0.70, 0.65, -0.10],
                [0.70, 1.00, 0.60, -0.05],
                [0.65, 0.60, 1.00, -0.08],
                [-0.10, -0.05, -0.08, 1.00],
            ]
        )
        cov = pd.DataFrame(
            corr_vals * np.outer(std, std), index=tickers, columns=tickers
        )
        corr_full = pd.DataFrame(corr_vals, index=tickers, columns=tickers)
        reordered = ["TLT", "AAPL", "MSFT", "GOOGL"]
        corr_reordered = corr_full.loc[reordered, reordered]

        with pytest.raises(ValueError, match="same row/column labels and order"):
            hierarchical_risk_parity(cov, corr=corr_reordered)

    def test_hrp_rejects_a_corr_shaped_differently_from_cov(self) -> None:
        cov = np.eye(4) * 0.04
        corr = np.eye(3)

        with pytest.raises(ValueError, match="same shape"):
            hierarchical_risk_parity(cov, corr=corr)

    def test_hrp_accepts_a_correctly_aligned_corr(self) -> None:
        tickers = ["AAPL", "MSFT", "GOOGL", "TLT"]
        std = np.array([0.30, 0.28, 0.32, 0.08])
        corr_vals = np.array(
            [
                [1.00, 0.70, 0.65, -0.10],
                [0.70, 1.00, 0.60, -0.05],
                [0.65, 0.60, 1.00, -0.08],
                [-0.10, -0.05, -0.08, 1.00],
            ]
        )
        cov = pd.DataFrame(
            corr_vals * np.outer(std, std), index=tickers, columns=tickers
        )
        corr = pd.DataFrame(corr_vals, index=tickers, columns=tickers)

        weights = hierarchical_risk_parity(cov, corr=corr)
        assert np.sum(weights) == pytest.approx(1.0)
