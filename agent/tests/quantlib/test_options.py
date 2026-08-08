"""Pin the Black-Scholes primitives in ``src.quantlib.options``.

Three independent kinds of check, because each catches what the others miss:

  * Published reference values (Hull, *Options, Futures and Other
    Derivatives*). These catch a formula that is self-consistently wrong.
  * Structural identities -- put-call parity, and Greeks against central
    finite-difference bumps of the price function. These catch a Greek that
    disagrees with the price it is supposed to differentiate, including unit
    errors in theta (per day) and vega/rho (per percentage point).
  * Round-trips and edges -- price to implied vol and back, degenerate inputs,
    deep in/out of the money, and the last day before expiry.
"""

from __future__ import annotations

import math

import pytest

from src.quantlib.options import (
    bs_greeks,
    bs_price,
    implied_volatility,
    normalise_option_type,
)

# Hull, Example 15.6: a six-month European option on a non-dividend stock.
_HULL_15_6 = {"S": 42.0, "K": 40.0, "T": 0.5, "r": 0.10, "sigma": 0.20}
# Hull, Example 19.1: the worked example the Greek chapter tabulates.
_HULL_19_1 = {"S": 49.0, "K": 50.0, "T": 0.3846, "r": 0.05, "sigma": 0.20}


class TestPublishedReferenceValues:
    """Prices and Greeks against textbook-published numbers."""

    def test_hull_15_6_call_and_put_prices(self) -> None:
        # Hull publishes c = 4.76 and p = 0.81.
        assert bs_price(**_HULL_15_6, option_type="call") == pytest.approx(4.76, abs=5e-3)
        assert bs_price(**_HULL_15_6, option_type="put") == pytest.approx(0.81, abs=5e-3)

    def test_hull_19_1_price(self) -> None:
        # Hull publishes a call value of 2.40.
        assert bs_price(**_HULL_19_1, option_type="call") == pytest.approx(2.40, abs=5e-3)

    @pytest.mark.parametrize(
        "greek, published, scale",
        [
            # Hull tabulates delta 0.522, gamma 0.066 in native units...
            ("delta", 0.522, 1.0),
            ("gamma", 0.066, 1.0),
            # ...and theta -4.31/year, vega 12.1 and rho 8.91 per 1.0 of the
            # input, whereas this module reports theta per calendar day and
            # vega/rho per percentage point.
            ("theta", -4.31, 365.0),
            ("vega", 12.1, 100.0),
            ("rho", 8.91, 100.0),
        ],
    )
    def test_hull_19_1_greeks(self, greek: str, published: float, scale: float) -> None:
        got = bs_greeks(**_HULL_19_1, option_type="call")[greek] * scale
        assert got == pytest.approx(published, abs=5e-3 * max(abs(published), 1.0))

    def test_at_the_money_one_year_reference(self) -> None:
        # The standard S=K=100, T=1, r=5%, sigma=20% case.
        assert bs_price(100, 100, 1.0, 0.05, 0.2, "call") == pytest.approx(10.450584, abs=1e-6)
        assert bs_price(100, 100, 1.0, 0.05, 0.2, "put") == pytest.approx(5.573526, abs=1e-6)


class TestPutCallParity:
    """``C - P == S*exp(-qT) - K*exp(-rT)`` must hold exactly."""

    @pytest.mark.parametrize(
        "S, K, T, r, sigma, q",
        [
            (100.0, 100.0, 1.0, 0.05, 0.20, 0.0),
            (100.0, 80.0, 0.25, 0.03, 0.45, 0.0),
            (100.0, 130.0, 2.0, 0.01, 0.15, 0.0),
            (100.0, 100.0, 1.0, 0.05, 0.20, 0.03),
            (250.0, 200.0, 0.5, 0.04, 0.60, 0.02),
            (7.5, 10.0, 0.75, 0.00, 0.30, 0.05),
        ],
    )
    def test_parity_holds(self, S, K, T, r, sigma, q) -> None:
        call = bs_price(S, K, T, r, sigma, "call", q)
        put = bs_price(S, K, T, r, sigma, "put", q)
        assert call - put == pytest.approx(
            S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-9
        )

    def test_parity_holds_for_the_greeks_too(self) -> None:
        # Gamma and vega are identical for call and put; deltas differ by
        # exactly exp(-qT); rho differs by K*T*exp(-rT)/100.
        args = {"S": 100.0, "K": 105.0, "T": 0.6, "r": 0.04, "sigma": 0.25, "q": 0.02}
        call = bs_greeks(**args, option_type="call")
        put = bs_greeks(**args, option_type="put")
        assert call["gamma"] == pytest.approx(put["gamma"], rel=1e-12)
        assert call["vega"] == pytest.approx(put["vega"], rel=1e-12)
        assert call["delta"] - put["delta"] == pytest.approx(
            math.exp(-args["q"] * args["T"]), abs=1e-12
        )
        assert call["rho"] - put["rho"] == pytest.approx(
            args["K"] * args["T"] * math.exp(-args["r"] * args["T"]) / 100.0, abs=1e-12
        )


class TestGreeksAgainstFiniteDifferences:
    """Every Greek must be the derivative of the price function it claims."""

    _CASES = [
        (100.0, 100.0, 1.00, 0.05, 0.20, 0.00, "call"),
        (100.0, 100.0, 1.00, 0.05, 0.20, 0.00, "put"),
        (100.0, 120.0, 0.50, 0.03, 0.35, 0.02, "call"),
        (100.0, 80.0, 0.25, 0.04, 0.45, 0.01, "put"),
        (100.0, 100.0, 0.05, 0.02, 0.15, 0.00, "call"),
    ]

    @pytest.mark.parametrize("S, K, T, r, sigma, q, kind", _CASES)
    def test_delta_and_gamma(self, S, K, T, r, sigma, q, kind) -> None:
        h = 1e-4 * S
        up = bs_price(S + h, K, T, r, sigma, kind, q)
        mid = bs_price(S, K, T, r, sigma, kind, q)
        down = bs_price(S - h, K, T, r, sigma, kind, q)
        greeks = bs_greeks(S, K, T, r, sigma, kind, q)
        assert greeks["delta"] == pytest.approx((up - down) / (2 * h), rel=1e-5)
        assert greeks["gamma"] == pytest.approx((up - 2 * mid + down) / h**2, rel=1e-3)

    @pytest.mark.parametrize("S, K, T, r, sigma, q, kind", _CASES)
    def test_vega_is_per_percentage_point(self, S, K, T, r, sigma, q, kind) -> None:
        h = 1e-5
        d_price = (
            bs_price(S, K, T, r, sigma + h, kind, q)
            - bs_price(S, K, T, r, sigma - h, kind, q)
        ) / (2 * h)
        assert bs_greeks(S, K, T, r, sigma, kind, q)["vega"] == pytest.approx(
            d_price / 100.0, rel=1e-5
        )

    @pytest.mark.parametrize("S, K, T, r, sigma, q, kind", _CASES)
    def test_theta_is_negative_dprice_dT_per_calendar_day(
        self, S, K, T, r, sigma, q, kind
    ) -> None:
        h = 1e-5
        d_price = (
            bs_price(S, K, T + h, r, sigma, kind, q)
            - bs_price(S, K, T - h, r, sigma, kind, q)
        ) / (2 * h)
        assert bs_greeks(S, K, T, r, sigma, kind, q)["theta"] == pytest.approx(
            -d_price / 365.0, rel=1e-5
        )

    @pytest.mark.parametrize("S, K, T, r, sigma, q, kind", _CASES)
    def test_rho_is_per_percentage_point(self, S, K, T, r, sigma, q, kind) -> None:
        h = 1e-6
        d_price = (
            bs_price(S, K, T, r + h, sigma, kind, q)
            - bs_price(S, K, T, r - h, sigma, kind, q)
        ) / (2 * h)
        assert bs_greeks(S, K, T, r, sigma, kind, q)["rho"] == pytest.approx(
            d_price / 100.0, rel=1e-4
        )


class TestImpliedVolatility:
    """Price -> implied vol -> price must return the original price."""

    @pytest.mark.parametrize(
        "S, K, T, r, sigma, q, kind",
        [
            (100.0, 100.0, 1.00, 0.05, 0.20, 0.00, "call"),
            (100.0, 100.0, 1.00, 0.05, 0.20, 0.00, "put"),
            (100.0, 130.0, 0.50, 0.03, 0.45, 0.00, "call"),
            (100.0, 70.0, 0.25, 0.03, 0.55, 0.00, "put"),
            (100.0, 100.0, 2.00, 0.02, 0.08, 0.03, "call"),
            (100.0, 95.0, 0.10, 0.04, 1.20, 0.01, "put"),
            (3000.0, 3100.0, 0.75, 0.045, 0.18, 0.015, "call"),
        ],
    )
    def test_round_trip(self, S, K, T, r, sigma, q, kind) -> None:
        price = bs_price(S, K, T, r, sigma, kind, q)
        implied = implied_volatility(price, S, K, T, r, kind, q)
        assert implied == pytest.approx(sigma, abs=1e-4)
        assert bs_price(S, K, T, r, implied, kind, q) == pytest.approx(price, abs=1e-6)

    def test_deep_out_of_the_money_round_trip(self) -> None:
        # The Brenner-Subrahmanyam seed lands at sigma 0.00113 for this quote,
        # where vega underflows to 0.0, so Newton breaks on the first step and
        # the bisection branch carries the whole solve. The vol itself must come
        # back, not merely a vol that reprices to the same number.
        price = bs_price(100.0, 150.0, 0.25, 0.03, 0.30, "call")
        assert price > 1e-3  # resolvable: far above the 1e-6 price tolerance
        implied = implied_volatility(price, 100.0, 150.0, 0.25, 0.03, "call")
        assert implied == pytest.approx(0.30, abs=1e-4)

    @pytest.mark.parametrize(
        "S, K, T, sigma, label",
        [
            (100.0, 200.0, 0.05, 0.25, "out of the money, price 1.2e-35"),
            (200.0, 100.0, 0.05, 0.25, "in the money, price flat to 1e-16"),
        ],
    )
    def test_unidentifiable_vol_is_refused_rather_than_guessed(
        self, S: float, K: float, T: float, sigma: float, label: str
    ) -> None:
        """A quote that carries no vol information must return nan, not a number.

        Where the price is flat in ``sigma`` to machine precision, every vol in
        a wide band satisfies ``tol``, so "converged" means only that the search
        stopped somewhere. Returning that endpoint reports a 140% error as a
        solved volatility (true 0.25, returned 0.60 for the in-the-money case).
        The solver checks vega at the candidate and refuses instead.
        """
        r = 0.03
        price = bs_price(S, K, T, r, sigma, "call")
        implied = implied_volatility(price, S, K, T, r, "call")
        assert math.isnan(implied)

    def test_identifiability_threshold_tracks_the_requested_tolerance(self) -> None:
        """The refusal scales with ``tol``; it is not an absolute vega floor.

        Loosening the tolerance widens the band of volatilities that reprice
        within it, so the same quote goes from identifiable to unidentifiable.
        This quote has vega 1.85e-3 per unit sigma, which puts the flip at
        tol = 1.85e-5: solvable at 1e-6, refused at 1e-2.
        """
        S, K, T, r, sigma = 100.0, 135.0, 0.08, 0.03, 0.25
        price = bs_price(S, K, T, r, sigma, "call")
        tight = implied_volatility(price, S, K, T, r, "call", tol=1e-6)
        assert tight == pytest.approx(sigma, abs=1e-4)
        assert math.isnan(implied_volatility(price, S, K, T, r, "call", tol=1e-2))


    def test_near_expiry_round_trip(self) -> None:
        one_day = 1.0 / 365.0
        price = bs_price(100.0, 100.5, one_day, 0.03, 0.30, "call")
        implied = implied_volatility(price, 100.0, 100.5, one_day, 0.03, "call")
        assert implied == pytest.approx(0.30, abs=1e-3)

    def test_below_intrinsic_raises(self) -> None:
        # A call cannot trade below its discounted forward intrinsic.
        with pytest.raises(ValueError, match="below intrinsic"):
            implied_volatility(2.0, 120.0, 100.0, 1.0, 0.05, "call")

    def test_put_below_undiscounted_intrinsic_is_accepted(self) -> None:
        # A deep in-the-money European put legitimately trades below K - S.
        # Guarding on the undiscounted intrinsic would reject this real price.
        S, K, T, r = 90.0, 100.0, 1.0, 0.10
        price = bs_price(S, K, T, r, 0.05, "put")
        assert price < K - S  # below undiscounted intrinsic, and still valid
        assert implied_volatility(price, S, K, T, r, "put") == pytest.approx(
            0.05, abs=1e-4
        )

    def test_above_no_arbitrage_ceiling_raises(self) -> None:
        # No volatility takes a call above the present value of the spot.
        with pytest.raises(ValueError, match="ceiling"):
            implied_volatility(101.0, 100.0, 90.0, 1.0, 0.05, "call")

    def test_unconverged_solve_returns_nan_not_a_scipy_exception(self) -> None:
        # brentq raises RuntimeError when it exhausts its own iteration budget.
        # The documented contract for "no volatility found" is nan; a scipy
        # exception type must not leak out of the implementation.
        result = implied_volatility(
            bs_price(100.0, 150.0, 0.25, 0.03, 0.30, "call"),
            100.0, 150.0, 0.25, 0.03, "call", tol=1e-14, max_iter=1,
        )
        assert math.isnan(result)

    @pytest.mark.parametrize("bad_T", [0.0, -0.5])
    def test_non_positive_expiry_raises(self, bad_T: float) -> None:
        with pytest.raises(ValueError, match="T must be > 0"):
            implied_volatility(5.0, 100.0, 100.0, bad_T, 0.05, "call")

    def test_non_positive_spot_or_strike_raises(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            implied_volatility(5.0, 0.0, 100.0, 1.0, 0.05, "call")
        with pytest.raises(ValueError, match="must be > 0"):
            implied_volatility(5.0, 100.0, -1.0, 1.0, 0.05, "call")


class TestEdgeCases:
    """Degenerate inputs, and the deep/near-expiry tails."""

    @pytest.mark.parametrize(
        "T, sigma, S, K",
        [(0.0, 0.2, 100.0, 90.0), (-1.0, 0.2, 100.0, 90.0), (1.0, 0.0, 100.0, 90.0),
         (1.0, -0.2, 100.0, 90.0), (1.0, 0.2, 0.0, 90.0), (1.0, 0.2, 100.0, 0.0)],
    )
    def test_degenerate_inputs_return_intrinsic(self, T, sigma, S, K) -> None:
        assert bs_price(S, K, T, 0.05, sigma, "call") == max(S - K, 0.0)
        assert bs_price(S, K, T, 0.05, sigma, "put") == max(K - S, 0.0)

    def test_expiring_in_the_money_option_keeps_unit_delta(self) -> None:
        # The regression the skill's copy had: reporting delta 0 for an option
        # that is certain to be exercised.
        itm_call = bs_greeks(120.0, 100.0, 0.0, 0.05, 0.2, "call")
        assert itm_call["delta"] == 1.0
        itm_put = bs_greeks(80.0, 100.0, 0.0, 0.05, 0.2, "put")
        assert itm_put["delta"] == -1.0
        for degenerate in (itm_call, itm_put):
            assert degenerate["gamma"] == 0.0
            assert degenerate["theta"] == 0.0
            assert degenerate["vega"] == 0.0
            assert degenerate["rho"] == 0.0

    def test_expiring_out_of_the_money_option_has_zero_delta(self) -> None:
        assert bs_greeks(80.0, 100.0, 0.0, 0.05, 0.2, "call")["delta"] == 0.0
        assert bs_greeks(120.0, 100.0, 0.0, 0.05, 0.2, "put")["delta"] == 0.0

    def test_deep_in_the_money_call_approaches_discounted_forward(self) -> None:
        S, K, T, r, sigma = 100.0, 1.0, 1.0, 0.05, 0.20
        price = bs_price(S, K, T, r, sigma, "call")
        assert price == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)
        assert bs_greeks(S, K, T, r, sigma, "call")["delta"] == pytest.approx(1.0, abs=1e-6)

    def test_deep_out_of_the_money_call_is_worthless_but_non_negative(self) -> None:
        price = bs_price(100.0, 1000.0, 0.1, 0.05, 0.20, "call")
        assert 0.0 <= price < 1e-6
        assert bs_greeks(100.0, 1000.0, 0.1, 0.05, 0.20, "call")["delta"] < 1e-6

    def test_near_expiry_converges_to_intrinsic(self) -> None:
        tiny_T = 1e-8
        assert bs_price(110.0, 100.0, tiny_T, 0.05, 0.2, "call") == pytest.approx(
            10.0, abs=1e-5
        )
        assert bs_price(90.0, 100.0, tiny_T, 0.05, 0.2, "call") == pytest.approx(
            0.0, abs=1e-5
        )

    def test_price_is_monotone_in_volatility(self) -> None:
        prices = [bs_price(100.0, 105.0, 0.5, 0.03, s, "call") for s in
                  (0.05, 0.10, 0.20, 0.40, 0.80)]
        assert prices == sorted(prices)

    @pytest.mark.parametrize("alias", ["CALL", " Call ", "put", "PUT"])
    def test_option_type_is_case_insensitive(self, alias: str) -> None:
        expected = bs_price(100.0, 100.0, 1.0, 0.05, 0.2, alias.strip().lower())
        assert bs_price(100.0, 100.0, 1.0, 0.05, 0.2, alias) == expected

    # "c" used to appear here as an unknown type. It is now an accepted alias
    # (see _CALL_ALIASES), so the cases below are genuine typos and non-types --
    # the values for which guessing is unsafe.
    @pytest.mark.parametrize("bad", ["cal", "straddle", "", "1", "long"])
    def test_unknown_option_type_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="option_type"):
            bs_price(100.0, 100.0, 1.0, 0.05, 0.2, bad)
        with pytest.raises(ValueError, match="option_type"):
            bs_greeks(100.0, 100.0, 1.0, 0.05, 0.2, bad)


def test_engine_and_quantlib_are_the_same_object() -> None:
    """The engine must not carry a second copy of this math."""
    from backtest.engines import options_portfolio

    assert options_portfolio.bs_price is bs_price
    assert options_portfolio.bs_greeks is bs_greeks


class TestEngineFoldsOptionTypeTheSameWay:
    """Pricing and settlement must not disagree about a leg typed ``"Call"``.

    ``bs_price`` folds case; ``OptionPosition.intrinsic_value`` compares the
    stored string. If the position keeps the raw string, a leg typed ``"Call"``
    is priced as a call at open and settled as a put at expiry, which fabricates
    P&L out of nothing.
    """

    @pytest.mark.parametrize("alias", ["call", "Call", "CALL", " call "])
    def test_stored_type_is_folded(self, alias: str) -> None:
        from backtest.engines.options_portfolio import OptionPosition

        pos = OptionPosition(alias, 100.0, "2026-01-01", 1, 5.0, "2025-10-01", "X")
        assert pos.option_type == "call"

    @pytest.mark.parametrize("alias", ["call", "Call", "CALL"])
    def test_price_and_settlement_agree(self, alias: str) -> None:
        from backtest.engines.options_portfolio import OptionPosition

        pos = OptionPosition(alias, 100.0, "2026-01-01", 1, 5.0, "2025-10-01", "X")
        # Spot above the strike: a call settles at 30, a put at 0.
        assert bs_price(130.0, 100.0, 0.25, 0.03, 0.20, alias) > 29.0
        assert pos.intrinsic_value(130.0) == 30.0

    def test_matching_is_case_insensitive(self) -> None:
        from backtest.engines.options_portfolio import (
            OptionPosition, _find_matching_position, normalise_option_type,
        )

        pos = OptionPosition("Call", 100.0, "2026-01-01", 1, 5.0, "2025-10-01", "X")
        for alias in ("call", "Call", "CALL"):
            assert _find_matching_position(
                [pos], "X", normalise_option_type(alias), 100.0, "2026-01-01"
            ) is pos

    def test_unknown_type_is_rejected_at_construction(self) -> None:
        from backtest.engines.options_portfolio import OptionPosition

        # A genuine typo, not "c" -- that is an accepted alias now.
        with pytest.raises(ValueError, match="option_type"):
            OptionPosition("cal", 100.0, "2026-01-01", 1, 5.0, "2025-10-01", "X")

    def test_an_aliased_type_is_accepted_at_construction(self) -> None:
        from backtest.engines.options_portfolio import OptionPosition

        # The engine folds through the same rule, so a config typed "C" builds
        # a position that prices AND settles as a call.
        pos = OptionPosition("C", 100.0, "2026-01-01", 1, 5.0, "2025-10-01", "X")
        assert pos.option_type == "call"


# --- option-type aliases: compatibility without reintroducing the defaulting bug ---


@pytest.mark.parametrize(
    "raw", ["call", "Call", "CALL", " call ", "calls", "C", "c", "看涨", "认购"]
)
def test_unambiguous_call_spellings_are_accepted(raw):
    assert normalise_option_type(raw) == "call"


@pytest.mark.parametrize(
    "raw", ["put", "Put", "PUT", " put ", "puts", "P", "p", "看跌", "认沽"]
)
def test_unambiguous_put_spellings_are_accepted(raw):
    assert normalise_option_type(raw) == "put"


@pytest.mark.parametrize("raw", ["cal", "kall", "pu", "", "   ", "option", "1", "long"])
def test_a_typo_still_raises_rather_than_being_guessed_at(raw):
    # This is the half of the contract that must NOT be relaxed. Defaulting an
    # unrecognised type to put is what settled ten in-the-money call contracts
    # at zero.
    with pytest.raises(ValueError, match="unrecognised option_type"):
        normalise_option_type(raw)


def test_the_error_message_lists_what_is_accepted():
    with pytest.raises(ValueError) as excinfo:
        normalise_option_type("cal")
    message = str(excinfo.value)
    assert "calls" in message and "puts" in message


def test_aliases_price_identically_to_the_canonical_spelling():
    canonical = bs_price(100, 100, 1.0, 0.05, 0.2, "call")
    for alias in ("C", "CALLS", " 认购 "):
        assert bs_price(100, 100, 1.0, 0.05, 0.2, alias) == pytest.approx(canonical)


def test_an_aliased_leg_prices_and_settles_as_the_same_side():
    # The original defect in one assertion: whatever the leg was typed as, the
    # side used to price it must be the side used to settle it.
    for alias, expected in (("C", "call"), ("认沽", "put"), ("Puts", "put")):
        folded = normalise_option_type(alias)
        assert folded == expected
        deep_itm = bs_price(200, 100, 0.01, 0.0, 0.2, alias) if folded == "call" else \
            bs_price(50, 100, 0.01, 0.0, 0.2, alias)
        assert deep_itm > 45.0
