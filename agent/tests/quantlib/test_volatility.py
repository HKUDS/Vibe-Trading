"""Unit and property tests for Heston (1993) stochastic volatility model."""

import math
import pytest
from src.quantlib.volatility import (
    heston_characteristic_function,
    heston_price,
    heston_feller_condition,
)
from src.quantlib.options import bs_price, implied_volatility


class TestHestonModel:
    def test_feller_condition(self):
        # 2 * 1.5 * 0.04 = 0.12, sigma_v**2 = 0.575**2 = 0.330625 -> ratio ~ 0.363 (< 1, violated)
        res = heston_feller_condition(kappa=1.5, theta=0.04, sigma_v=0.575)
        assert not res["is_satisfied"]
        assert pytest.approx(res["feller_ratio"], abs=1e-3) == 0.363

        # Satisfied case: kappa=2.0, theta=0.1, sigma_v=0.2 -> 2*2*0.1 / 0.04 = 10.0 (> 1)
        res_sat = heston_feller_condition(kappa=2.0, theta=0.1, sigma_v=0.2)
        assert res_sat["is_satisfied"]
        assert pytest.approx(res_sat["feller_ratio"], rel=1e-7) == 10.0

    def test_characteristic_function_at_zero(self):
        # phi(0) = E[e^0] = 1.0
        cf = heston_characteristic_function(
            u=0.0,
            S0=100.0,
            T=1.0,
            r=0.05,
            q=0.02,
            v0=0.04,
            kappa=1.5,
            theta=0.04,
            sigma_v=0.3,
            rho=-0.5,
        )
        assert pytest.approx(cf.real, abs=1e-7) == 1.0
        assert pytest.approx(cf.imag, abs=1e-7) == 0.0

    def test_heston_moodley_benchmark(self):
        # Moodley (2005) Table 2: S0=100, K=100, T=0.5, r=0.0, q=0.0, v0=0.04, kappa=1.5, theta=0.04, sigma_v=0.575, rho=-0.5711
        # Call price = 5.0272...
        price = heston_price(
            S0=100.0,
            K=100.0,
            T=0.5,
            r=0.0,
            v0=0.04,
            kappa=1.5,
            theta=0.04,
            sigma_v=0.575,
            rho=-0.5711,
            option_type="call",
        )
        assert pytest.approx(price, abs=1e-3) == 5.027

    def test_put_call_parity(self):
        S0, K, T, r, q = 100.0, 95.0, 1.0, 0.04, 0.01
        v0, kappa, theta, sigma_v, rho = 0.04, 2.0, 0.04, 0.3, -0.7
        call = heston_price(S0, K, T, r, v0, kappa, theta, sigma_v, rho, option_type="call", q=q)
        put = heston_price(S0, K, T, r, v0, kappa, theta, sigma_v, rho, option_type="put", q=q)
        # Parity: Call - Put = S0*exp(-qT) - K*exp(-rT)
        parity = S0 * math.exp(-q * T) - K * math.exp(-r * T)
        assert pytest.approx(call - put, abs=1e-4) == parity

    def test_convergence_to_black_scholes_zero_vol_of_vol(self):
        # When sigma_v -> 0, Heston approaches Black-Scholes with constant variance v0=theta
        S0, K, T, r, q = 100.0, 100.0, 1.0, 0.05, 0.0
        vol = 0.2
        v0 = theta = vol**2
        h_price = heston_price(
            S0=S0,
            K=K,
            T=T,
            r=r,
            v0=v0,
            kappa=1.0,
            theta=theta,
            sigma_v=1e-4,
            rho=0.0,
            option_type="call",
            q=q,
        )
        bs = bs_price(S=S0, K=K, T=T, r=r, sigma=vol, option_type="call", q=q)
        assert pytest.approx(h_price, abs=1e-3) == bs

    def test_negative_rho_produces_a_downward_sloping_skew(self):
        """A leverage-effect correlation must make low strikes the expensive ones.

        This is the only property in this file that can see the sign of the
        Lewis integrand's ``e^{iuk}`` factor. With ``sigma_v -> 0`` the centered
        characteristic function is real, so the Black-Scholes limit is identical
        under either sign; at the money ``k`` is zero, so the benchmark and the
        put-call parity check are identical too. Flipping the sign inverts the
        skew and nothing else in the suite moves.
        """
        S0, T, r, q = 100.0, 1.0, 0.02, 0.01
        kappa, theta, sigma_v, v0 = 3.0, 0.04, 0.2, 0.04

        def iv(K: float, rho: float) -> float:
            price = heston_price(
                S0, K, T, r, v0, kappa, theta, sigma_v, rho, option_type="call", q=q
            )
            return implied_volatility(price, S0, K, T, r, "call", q=q)

        low, high = 80.0, 120.0
        assert iv(low, -0.6) > iv(high, -0.6), "rho < 0 must give a negative skew"
        assert iv(low, 0.6) < iv(high, 0.6), "rho > 0 must give a positive skew"
        # Symmetric parameters: flipping rho must mirror the smile, not shift it.
        assert iv(low, -0.6) == pytest.approx(iv(high, 0.6), abs=2e-3)

    def test_negative_rho_cheapens_out_of_the_money_calls(self):
        """The price-level consequence of the skew, checked without inverting IV."""
        S0, K, T, r, q = 100.0, 120.0, 1.0, 0.02, 0.01
        kappa, theta, sigma_v, v0 = 3.0, 0.04, 0.2, 0.04

        def price(rho: float) -> float:
            return heston_price(
                S0, K, T, r, v0, kappa, theta, sigma_v, rho, option_type="call", q=q
            )

        assert price(-0.6) < price(0.0) < price(0.6)

    def test_invalid_parameters_raise(self):
        with pytest.raises(ValueError):
            heston_price(S0=-100.0, K=100.0, T=1.0, r=0.05, v0=0.04, kappa=1.0, theta=0.04, sigma_v=0.3, rho=0.0)
        with pytest.raises(ValueError):
            heston_price(S0=100.0, K=100.0, T=1.0, r=0.05, v0=0.04, kappa=1.0, theta=0.04, sigma_v=0.3, rho=1.5)
        with pytest.raises(ValueError):
            heston_feller_condition(kappa=-1.0, theta=0.04, sigma_v=0.3)
