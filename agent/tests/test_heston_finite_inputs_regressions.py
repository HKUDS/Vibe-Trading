import pytest
from src.quantlib.volatility import heston_price, heston_feller_condition


@pytest.mark.parametrize(
    "field",
    [
        "S0",
        "K",
        "T",
        "r",
        "q",
        "v0",
        "kappa",
        "theta",
        "sigma_v",
        "rho",
        "integration_limit",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_heston_rejects_nonfinite_inputs_before_pricing(field, value):
    args = dict(
        S0=100.0,
        K=100.0,
        T=1.0,
        r=0.03,
        q=0.0,
        v0=0.04,
        kappa=2.0,
        theta=0.04,
        sigma_v=0.3,
        rho=-0.7,
        integration_limit=200.0,
    )
    args[field] = value
    with pytest.raises(ValueError, match="finite"):
        heston_price(**args)


@pytest.mark.parametrize("limit", [0.0, -1.0])
def test_heston_rejects_empty_or_reversed_integration_domain(limit):
    with pytest.raises(ValueError, match="integration_limit"):
        heston_price(
            100.0, 100.0, 1.0, 0.03, 0.04, 2.0, 0.04, 0.3, -0.7, integration_limit=limit
        )


@pytest.mark.parametrize("field", ["kappa", "theta", "sigma_v"])
def test_feller_rejects_nonfinite_inputs(field):
    args = dict(kappa=2.0, theta=0.04, sigma_v=0.3)
    args[field] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        heston_feller_condition(**args)


def test_quantlib_tool_rejects_zero_integration_domain():
    import json
    from src.tools.quantlib_tool import QuantlibCallTool

    result = json.loads(
        QuantlibCallTool().execute(
            action="call",
            module="volatility",
            function="heston_price",
            kwargs={
                "S0": 100.0,
                "K": 100.0,
                "T": 1.0,
                "r": 0.03,
                "v0": 0.04,
                "kappa": 2.0,
                "theta": 0.04,
                "sigma_v": 0.3,
                "rho": -0.7,
                "integration_limit": 0.0,
            },
        )
    )
    assert result["ok"] is False
    assert "integration_limit" in result["error"]
