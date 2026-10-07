import numpy as np
import pytest

from src.quantlib.copula import fit_copula_from_tau, gaussian_copula_cdf


@pytest.mark.parametrize("rho,expected", [(0.9999999999, 0.3), (-0.9999999999, 0.1)])
def test_near_perfect_valid_correlation_has_a_finite_cdf(rho, expected):
    value = gaussian_copula_cdf(0.3, 0.8, rho)
    assert np.isfinite(value)
    assert value == pytest.approx(expected, abs=2e-5)


@pytest.mark.parametrize("tau,expected", [(0.9999999999, 0.3), (-0.9999999999, 0.1)])
def test_valid_tau_calibration_can_be_consumed_by_the_cdf(tau, expected):
    result = fit_copula_from_tau(tau, "gaussian")
    assert -1.0 < result["rho"] < 1.0
    value = gaussian_copula_cdf(0.3, 0.8, result["rho"])
    assert value == pytest.approx(expected, abs=2e-5)


@pytest.mark.parametrize("rho", [-1.0, 1.0])
def test_exact_correlation_endpoints_still_fail_validation(rho):
    with pytest.raises(ValueError, match="rho must be"):
        gaussian_copula_cdf(0.3, 0.8, rho)
