"""Invalid sector data must not masquerade as residual-free attribution."""

import json
import math

import pytest

from src.quantlib.attribution import brinson_fachler, carino_factor, carino_link


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_matching_nonfinite_weights_do_not_bypass_weight_sum_guard(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        brinson_fachler({"A": bad}, {"A": bad}, {"A": 0.1}, {"A": 0.05})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("side", ["portfolio", "benchmark"])
def test_nonfinite_sector_returns_are_rejected(bad: float, side: str) -> None:
    portfolio_returns = {"A": bad if side == "portfolio" else 0.1}
    benchmark_returns = {"A": bad if side == "benchmark" else 0.05}
    with pytest.raises(ValueError, match="finite"):
        brinson_fachler({"A": 1.0}, {"A": 1.0}, portfolio_returns, benchmark_returns)


@pytest.mark.parametrize("tolerance", [math.nan, math.inf, -1.0])
def test_invalid_tolerance_cannot_disable_attribution_reconciliation(
    tolerance: float,
) -> None:
    with pytest.raises(ValueError, match="weight_sum_tolerance"):
        brinson_fachler({"A": 0.8}, {"A": 1.0}, {"A": 0.1}, {"A": 0.05}, tolerance)


@pytest.mark.parametrize("bad", [math.nan, math.inf])
@pytest.mark.parametrize("side", ["portfolio", "benchmark"])
def test_carino_factor_rejects_nonfinite_returns(bad: float, side: str) -> None:
    portfolio = bad if side == "portfolio" else 0.1
    benchmark = bad if side == "benchmark" else 0.05
    with pytest.raises(ValueError, match="finite"):
        carino_factor(portfolio, benchmark)


def test_finite_short_weights_and_absent_zero_weight_returns_still_reconcile() -> None:
    result = brinson_fachler(
        {"A": 1.2, "B": -0.2, "C": 0.0},
        {"A": 0.8, "B": 0.2, "C": 0.0},
        {"A": 0.1, "B": -0.05},
        {"A": 0.08, "B": -0.02, "C": 0.04},
        weight_sum_tolerance=0.0,
    )
    assert result.total_effect == pytest.approx(result.active_return)
    linked = carino_link([result, result])
    assert linked.total_effect == pytest.approx(linked.active_return)
    assert all(math.isfinite(value) for value in linked.scaling_factors)


@pytest.mark.parametrize(
    "function, kwargs",
    [
        (
            "brinson_fachler",
            {
                "portfolio_weights": {"A": 1.0},
                "benchmark_weights": {"A": 1.0},
                "portfolio_returns": {"A": math.nan},
                "benchmark_returns": {"A": 0.05},
            },
        ),
        ("carino_factor", {"portfolio_return": math.nan, "benchmark_return": 0.05}),
    ],
)
def test_quantlib_tool_reports_invalid_attribution_as_error(
    function: str, kwargs: dict
) -> None:
    from src.tools.quantlib_tool import QuantlibCallTool

    result = json.loads(
        QuantlibCallTool().execute(
            action="call", module="attribution", function=function, kwargs=kwargs
        )
    )
    assert result["ok"] is False
    assert "finite" in result["error"]
