"""Observed-strike checks are distinct from interpolating an IV display grid."""

from __future__ import annotations

import copy
import json
import math

import pytest

from src.quantlib.options import bs_price, implied_volatility
from src.tools.quantlib_tool import QuantlibCallTool


def _observation(strike: float, iv: float, expiry: float = 1.0) -> dict[str, float]:
    return {"strike": strike, "time_to_expiry": expiry, "implied_volatility": iv}


def _from_call_prices(strikes, prices, *, spot=100.0, rate=0.0):
    return [
        _observation(
            strike, implied_volatility(price, spot, strike, 1.0, rate, tol=1e-10)
        )
        for strike, price in zip(strikes, prices)
    ]


def _call(observations, *, spot=100.0, rate=0.0, dividend=0.0):
    return json.loads(
        QuantlibCallTool().execute(
            action="call",
            module="volatility",
            function="diagnose_iv_surface",
            kwargs={
                "observations": observations,
                "spot": spot,
                "risk_free_rate": rate,
                "dividend_yield": dividend,
            },
        )
    )


def _diagnose(observations, **kwargs):
    payload = _call(observations, **kwargs)
    assert payload["ok"] is True, payload
    json.dumps(payload, allow_nan=False)
    return payload["result"]


def test_diagnostics_are_available_through_the_readonly_quantlib_tool() -> None:
    payload = json.loads(QuantlibCallTool().execute(action="list", module="volatility"))

    assert "diagnose_iv_surface" in {item["name"] for item in payload["functions"]}


def test_flat_vol_slices_have_coverage_without_a_pricing_certificate() -> None:
    observations = [
        _observation(strike, 0.2, expiry)
        for expiry in [0.5, 1.0]
        for strike in [80.0, 100.0, 130.0]
    ]

    result = _diagnose(observations, rate=0.03, dividend=0.01)

    assert result["basis"] == "european_bsm_calls"
    assert result["scope"] == "observed_strikes_per_expiry"
    assert result["checked"] == {"vertical_spreads": 4, "butterflies": 2}
    assert result["findings"] == []
    assert result["total_findings"] == 0
    assert [item["status"] for item in result["slices"]] == ["checked", "checked"]
    assert "arbitrage_free" not in result


def test_nonuniform_strike_convexity_uses_the_correct_linear_weights() -> None:
    observations = _from_call_prices([80.0, 100.0, 130.0], [25.0, 20.0, 5.0])

    result = _diagnose(observations)

    assert result["checked"] == {"vertical_spreads": 2, "butterflies": 1}
    assert result["total_findings"] == 1
    finding = result["findings"][0]
    assert finding["kind"] == "butterfly_convexity"
    assert finding["strikes"] == [80.0, 100.0, 130.0]
    assert finding["value"] == pytest.approx(-3.0, abs=1e-8)
    assert finding["lower_bound"] == 0.0


def test_call_prices_cannot_increase_with_strike() -> None:
    result = _diagnose(_from_call_prices([90.0, 100.0], [15.0, 20.0]))

    assert result["total_findings"] == 1
    finding = result["findings"][0]
    assert finding["kind"] == "vertical_spread_bounds"
    assert finding["value"] == pytest.approx(-5.0, abs=1e-8)
    assert finding["lower_bound"] == 0.0
    assert finding["upper_bound"] == 10.0


def test_a_vertical_spread_cannot_cost_more_than_its_discounted_payoff() -> None:
    rate = math.log(2.0)
    observations = _from_call_prices([90.0, 100.0], [15.0, 5.0], spot=50.0, rate=rate)

    result = _diagnose(observations, spot=50.0, rate=rate)

    finding = result["findings"][0]
    assert result["total_findings"] == 1
    assert finding["kind"] == "vertical_spread_bounds"
    assert finding["value"] == pytest.approx(10.0, abs=1e-8)
    assert finding["upper_bound"] == pytest.approx(5.0)
    assert result["parameters"]["risk_free_rate"] == rate


def test_insufficient_strikes_are_not_reported_as_a_checked_surface() -> None:
    result = _diagnose([_observation(100.0, 0.2, 0.5), _observation(110.0, 0.3, 1.0)])

    assert result["checked"] == {"vertical_spreads": 0, "butterflies": 0}
    assert [item["status"] for item in result["slices"]] == ["insufficient_points"] * 2
    assert result["findings"] == []


def test_zero_iv_uses_the_shared_deterministic_forward_limit() -> None:
    result = _diagnose([_observation(strike, 0.0) for strike in [80.0, 100.0, 130.0]])

    assert result["checked"] == {"vertical_spreads": 2, "butterflies": 1}
    assert result["total_findings"] == 0
    assert result["slices"][0]["status"] == "checked"


def test_negative_rates_and_dividend_yields_remain_valid_model_inputs() -> None:
    observations = [_observation(strike, 0.2) for strike in [80.0, 100.0, 130.0]]

    result = _diagnose(observations, rate=-0.01, dividend=-0.02)

    assert result["total_findings"] == 0
    assert result["parameters"]["risk_free_rate"] == -0.01
    assert result["parameters"]["dividend_yield"] == -0.02


def test_finding_limit_does_not_shrink_the_number_of_checks() -> None:
    strikes = [90.0 + index for index in range(41)]
    prices = [15.0 if index % 2 == 0 else 40.0 for index in range(41)]

    result = _diagnose(_from_call_prices(strikes, prices))

    assert result["checked"] == {"vertical_spreads": 40, "butterflies": 39}
    assert result["total_findings"] > 20
    assert result["limit"] == len(result["findings"]) == 20


def test_model_discount_overflow_is_unavailable_not_a_clean_slice() -> None:
    result = _diagnose([_observation(90.0, 0.2), _observation(100.0, 0.3)], rate=-1e308)

    assert result["checked"] == {"vertical_spreads": 0, "butterflies": 0}
    assert result["slices"][0]["status"] == "unavailable"
    assert result["slices"][0]["reason"] == "model_price_out_of_range"
    assert result["findings"] == []


def test_price_resolution_below_machine_range_is_unavailable() -> None:
    tiny = math.ulp(0.0)
    result = _diagnose(
        [_observation(2.0 * tiny, 0.2), _observation(4.0 * tiny, 0.3)], spot=tiny
    )

    assert result["slices"][0]["status"] == "unavailable"
    assert result["checked"] == {"vertical_spreads": 0, "butterflies": 0}


def test_a_checked_slice_requires_physically_admissible_model_prices() -> None:
    observations = [_observation(strike, 0.2) for strike in [1e-165, 2e-165, 3e-165]]
    spot, rate, dividend = 1e165, -400.0, 400.0
    prices = [
        bs_price(spot, point["strike"], 1.0, rate, 0.2, "call", dividend)
        for point in observations
    ]
    spot_pv = spot * math.exp(-dividend)
    tolerance = max(1e-9 * spot_pv, 8.0 * math.ulp(spot_pv))
    admissible = all(-tolerance <= price <= spot_pv + tolerance for price in prices)

    result = _diagnose(observations, spot=spot, rate=rate, dividend=dividend)

    assert result["slices"][0]["status"] == "unavailable" or admissible
    if not admissible:
        assert result["checked"] == {"vertical_spreads": 0, "butterflies": 0}


def test_unsorted_inputs_are_unchanged_and_produce_deterministic_diagnostics() -> None:
    observations = [
        _observation(strike, 0.2, expiry)
        for expiry in [1.0, 0.5]
        for strike in [130.0, 80.0, 100.0]
    ]
    original = copy.deepcopy(observations)

    result = _diagnose(observations)

    assert result == _diagnose(list(reversed(observations)))
    assert observations == original


@pytest.mark.parametrize(
    "argument,value",
    [("rate", True), ("rate", math.inf), ("dividend", math.nan), ("dividend", "0.05")],
)
def test_model_rates_must_be_finite_real_numbers(argument, value) -> None:
    payload = _call(
        [_observation(90.0, 0.2), _observation(100.0, 0.2)], **{argument: value}
    )

    assert payload["ok"] is False
    assert "finite real number" in payload["error"]


def test_duplicate_observed_quotes_are_refused_without_averaging() -> None:
    payload = _call([_observation(100.0, 0.2), _observation(100.0, 0.3)])

    assert payload["ok"] is False
    assert "duplicate expiry/strike" in payload["error"]


def test_diagnostics_bound_the_observation_input_not_only_display_size() -> None:
    payload = _call([_observation(50.0 + index, 0.2) for index in range(401)])

    assert payload["ok"] is False
    assert "400 observations" in payload["error"]
