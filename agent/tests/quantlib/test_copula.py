"""Tests for Copula models and tail dependence analytics."""

from __future__ import annotations

import numpy as np
import pytest

from src.quantlib.copula import (
    clayton_copula_cdf,
    clayton_tail_dependence,
    fit_copula_from_tau,
    frank_copula_cdf,
    gaussian_copula_cdf,
    gumbel_copula_cdf,
    gumbel_tail_dependence,
    pseudo_observations,
)


class TestCopulaAnalytics:
    """Validate copula CDF properties, tail dependencies, and tau calibration."""

    def test_pseudo_observations(self) -> None:
        data = np.array([10.0, 50.0, 20.0, 40.0])
        u = pseudo_observations(data)
        # ranks: 10->1, 20->2, 40->3, 50->4. divided by (4+1=5) -> [0.2, 0.8, 0.4, 0.6]
        assert np.allclose(u, [0.2, 0.8, 0.4, 0.6])

    def test_clayton_copula_properties(self) -> None:
        # C(u, 1) = u, C(1, v) = v
        u = 0.4
        theta = 2.0
        assert clayton_copula_cdf(u, 1.0, theta) == pytest.approx(u)
        assert clayton_copula_cdf(1.0, u, theta) == pytest.approx(u)

        # Tail dependence for theta=2.0 -> 2^{-1/2} = 1/sqrt(2) ~ 0.7071
        tail = clayton_tail_dependence(2.0)
        assert tail["lambda_lower"] == pytest.approx(np.sqrt(0.5))
        assert tail["lambda_upper"] == 0.0

    def test_gumbel_copula_properties(self) -> None:
        u = 0.6
        theta = 1.5
        assert gumbel_copula_cdf(u, 1.0, theta) == pytest.approx(u)

        tail = gumbel_tail_dependence(2.0)
        # lambda_U = 2 - 2^{1/2} = 2 - sqrt(2) ~ 0.5858
        assert tail["lambda_upper"] == pytest.approx(2.0 - np.sqrt(2.0))
        assert tail["lambda_lower"] == 0.0

    def test_frank_copula_properties(self) -> None:
        u = 0.5
        theta = 3.0
        assert frank_copula_cdf(u, 1.0, theta) == pytest.approx(u)

    def test_gaussian_copula_properties(self) -> None:
        u, v = 0.5, 0.5
        # For rho=0, independent copula C(0.5, 0.5) = 0.25
        val = gaussian_copula_cdf(u, v, rho=0.0)
        assert val == pytest.approx(0.25, abs=1e-4)

    def test_fit_copula_from_tau(self) -> None:
        # Clayton: tau = 0.5 -> theta = 2*0.5/(1-0.5) = 2.0
        res_clay = fit_copula_from_tau(0.5, family="clayton")
        assert res_clay["theta"] == pytest.approx(2.0)

        # Gumbel: tau = 0.5 -> theta = 1/(1-0.5) = 2.0
        res_gum = fit_copula_from_tau(0.5, family="gumbel")
        assert res_gum["theta"] == pytest.approx(2.0)

        # Gaussian: tau = 0.5 -> rho = sin(pi/4) ~ 0.7071
        res_gauss = fit_copula_from_tau(0.5, family="gaussian")
        assert res_gauss["rho"] == pytest.approx(np.sin(np.pi / 4))
