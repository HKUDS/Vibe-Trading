"""Implied-volatility surface grid construction and public tool exposure."""

from __future__ import annotations

import copy
import json
import math

import pytest

from src.quantlib.volatility import implied_volatility_surface
from src.tools.quantlib_tool import QuantlibCallTool


def _point(strike, expiry, iv):
    return {
        "strike": strike,
        "time_to_expiry": expiry,
        "implied_volatility": iv,
    }


def _rectangle():
    return [
        _point(90.0, 0.1, 0.25),
        _point(110.0, 0.1, 0.35),
        _point(90.0, 0.2, 0.30),
        _point(110.0, 0.2, 0.40),
    ]


def test_observed_anchors_and_input_order_are_deterministic():
    observations = _rectangle()
    original = copy.deepcopy(observations)

    first = implied_volatility_surface(observations, spot=100.0)
    second = implied_volatility_surface(list(reversed(observations)), spot=100.0)

    assert first == second
    assert observations == original
    assert first["strikes"] == [90.0, 110.0]
    assert first["expiries"] == [0.1, 0.2]
    assert first["interpolation"] == {
        "strike": "linear_iv_log_moneyness",
        "expiry": "linear_total_variance",
        "extrapolation": "rejected",
    }
    assert [point["source"] for point in first["points"]] == ["observed"] * 4
    assert [point["implied_volatility"] for point in first["points"]] == [
        0.25,
        0.35,
        0.30,
        0.40,
    ]


def test_strike_grid_uses_log_moneyness_not_arithmetic_strike():
    strike = math.sqrt(90.0 * 110.0)

    result = implied_volatility_surface(
        [_point(90.0, 0.1, 0.25), _point(110.0, 0.1, 0.35)],
        spot=100.0,
        strikes=[strike],
    )

    point = result["points"][0]
    assert point["source"] == "interpolated"
    assert point["implied_volatility"] == pytest.approx(0.30)
    assert point["total_variance"] == pytest.approx(0.30**2 * 0.1)


def test_expiry_grid_interpolates_total_variance_not_raw_iv():
    observations = [_point(100.0, 0.1, 0.20), _point(100.0, 0.2, 0.40)]

    result = implied_volatility_surface(observations, spot=100.0, expiries=[0.15])

    point = result["points"][0]
    lower_variance = 0.20**2 * 0.1
    upper_variance = 0.40**2 * 0.2
    expected_variance = (lower_variance + upper_variance) / 2.0
    assert point["total_variance"] == pytest.approx(expected_variance)
    assert point["implied_volatility"] == pytest.approx(math.sqrt(expected_variance / 0.15))
    assert point["implied_volatility"] != pytest.approx(0.30)


def test_interpolation_requires_coverage_on_each_adjacent_slice():
    observations = [
        _point(90.0, 0.1, 0.20),
        _point(100.0, 0.1, 0.25),
        _point(100.0, 0.2, 0.30),
        _point(110.0, 0.2, 0.35),
    ]

    with pytest.raises(ValueError, match="no extrapolation"):
        implied_volatility_surface(observations, spot=100.0, strikes=[95.0], expiries=[0.15])


@pytest.mark.parametrize("grid", [{"strikes": [120.0]}, {"expiries": [0.3]}])
def test_grid_outside_observed_domain_is_rejected(grid):
    with pytest.raises(ValueError, match="no extrapolation"):
        implied_volatility_surface(_rectangle(), spot=100.0, **grid)


def test_duplicate_expiry_strike_quotes_are_rejected_even_when_identical():
    observations = _rectangle()
    observations.append(_point(90.0, 0.1, 0.25))

    with pytest.raises(ValueError, match="duplicate"):
        implied_volatility_surface(observations, spot=100.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strike", 0.0),
        ("strike", math.nan),
        ("strike", True),
        ("time_to_expiry", 0.0),
        ("time_to_expiry", math.inf),
        ("implied_volatility", -0.01),
        ("implied_volatility", math.nan),
        ("implied_volatility", False),
    ],
)
def test_invalid_observation_values_are_rejected(field, value):
    observations = _rectangle()
    observations[0][field] = value

    with pytest.raises(ValueError):
        implied_volatility_surface(observations, spot=100.0)


def test_empty_inputs_and_invalid_spot_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        implied_volatility_surface([], spot=100.0)
    with pytest.raises(ValueError, match="spot"):
        implied_volatility_surface(_rectangle(), spot=0.0)
    with pytest.raises(ValueError, match="grid"):
        implied_volatility_surface(_rectangle(), spot=100.0, strikes=[])


def test_quantlib_tool_lists_and_calls_surface_builder():
    tool = QuantlibCallTool()
    listed = json.loads(tool.execute(action="list", module="volatility"))

    assert "implied_volatility_surface" in {item["name"] for item in listed["functions"]}
    called = json.loads(
        tool.execute(
            action="call",
            module="volatility",
            function="implied_volatility_surface",
            kwargs={
                "observations": _rectangle(),
                "spot": 100.0,
                "expiries": [0.15],
                "strikes": [100.0],
            },
        )
    )

    assert called["ok"] is True
    assert called["result"]["points"][0]["source"] == "interpolated"
    assert called["result"]["interpolation"]["extrapolation"] == "rejected"


@pytest.mark.parametrize("spot", [math.ulp(0.0), 1e-308, 1e308])
def test_interpolated_surface_is_independent_of_spot_scale(spot):
    kwargs = dict(observations=_rectangle(), strikes=[100.0], expiries=[0.15])
    expected = implied_volatility_surface(**kwargs, spot=100.0)
    actual = implied_volatility_surface(**kwargs, spot=spot)

    assert actual == expected
    json.dumps(actual, allow_nan=False)


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_log_interpolation_handles_extreme_strike_scales(scale):
    result = implied_volatility_surface(
        [_point(scale, 0.1, 0.2), _point(4 * scale, 0.1, 0.4)],
        spot=1e308,
        strikes=[2 * scale],
    )
    assert result["points"][0]["implied_volatility"] == pytest.approx(0.3)


def test_log_interpolation_preserves_distinct_nearby_strikes():
    left = 100.0
    middle = math.nextafter(left, math.inf)
    right = math.nextafter(middle, math.inf)
    result = implied_volatility_surface(
        [_point(left, 0.1, 0.2), _point(right, 0.1, 0.4)],
        spot=1.0,
        strikes=[middle],
    )
    assert result["points"][0]["implied_volatility"] == pytest.approx(0.3)


def test_log_interpolation_handles_a_ratio_larger_than_float_range():
    result = implied_volatility_surface(
        [_point(1e-300, 0.1, 0.2), _point(1e300, 0.1, 0.4)],
        spot=1.0,
        strikes=[1.0],
    )
    assert result["points"][0]["implied_volatility"] == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("iv", "expiry", "variance"),
    [
        (1e200, 1e-300, 1e100),
        (1e-200, 1e300, 1e-100),
        (0.0, 0.1, 0.0),
    ],
)
def test_total_variance_avoids_intermediate_overflow_and_underflow(iv, expiry, variance):
    result = implied_volatility_surface([_point(100.0, expiry, iv)], spot=100.0)
    assert result["points"][0]["total_variance"] == pytest.approx(variance, rel=1e-12, abs=0.0)


@pytest.mark.parametrize("iv", [1e200, 1e-200])
def test_unrepresentable_total_variance_is_refused(iv):
    with pytest.raises(ValueError, match="total variance"):
        implied_volatility_surface([_point(100.0, 1.0, iv)], spot=100.0)


def test_expiry_interpolation_avoids_overflow_before_square_root():
    result = implied_volatility_surface(
        [_point(100.0, 1e-300, 1e200), _point(100.0, 3e-300, 1e200)],
        spot=100.0,
        expiries=[2e-300],
    )
    assert result["points"][0]["implied_volatility"] == pytest.approx(1e200)


def test_quantlib_surface_returns_finite_results_or_an_explicit_error():
    tool = QuantlibCallTool()
    kwargs = dict(observations=_rectangle(), spot=1e-308, strikes=[100.0], expiries=[0.15])
    good = json.loads(
        tool.execute(
            action="call",
            module="volatility",
            function="implied_volatility_surface",
            kwargs=kwargs,
        )
    )
    assert good["ok"] is True
    assert math.isfinite(good["result"]["points"][0]["implied_volatility"])
    kwargs["observations"] = [_point(100.0, 1.0, 1e200)]
    kwargs["expiries"] = [1.0]
    bad = json.loads(
        tool.execute(
            action="call",
            module="volatility",
            function="implied_volatility_surface",
            kwargs=kwargs,
        )
    )
    assert bad["ok"] is False
