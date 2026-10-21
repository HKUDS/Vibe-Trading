"""The price models are scalar-only: a container is refused, never broadcast."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.quantlib.impact import (
    fixed_slippage,
    linear_impact,
    sqrt_impact,
)

PRICE = 100.0
ADV = 1_000_000.0
VOLUME = 100_000.0
VOLATILITY = 0.02

CONTAINERS = (
    pytest.param([100.0, 200.0], id="list"),
    pytest.param((100.0, 200.0), id="tuple"),
    pytest.param(np.array([100.0, 200.0]), id="ndarray"),
    pytest.param(np.array(100.0), id="ndarray-0d"),
    pytest.param(pd.Series([100.0, 200.0]), id="series"),
)


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_container_price_is_refused_by_every_model(container):
    """A container price never yields an array of fills."""
    with pytest.raises(TypeError, match="price must be a real scalar"):
        fixed_slippage(container, 1)
    with pytest.raises(TypeError, match="price must be a real scalar"):
        linear_impact(container, 1, VOLUME, ADV)
    with pytest.raises(TypeError, match="price must be a real scalar"):
        sqrt_impact(container, 1, VOLUME, ADV, VOLATILITY)


def test_a_container_size_is_refused():
    """Order size and ADV are scalar-only too."""
    with pytest.raises(TypeError, match="volume_traded must be a real scalar"):
        linear_impact(PRICE, 1, np.array([0.0, VOLUME]), ADV)
    with pytest.raises(TypeError, match="adv must be a real scalar"):
        sqrt_impact(PRICE, 1, VOLUME, pd.Series([ADV, ADV]), VOLATILITY)


def test_container_model_parameters_are_refused():
    """A swept parameter is a container too, and is refused alike."""
    with pytest.raises(TypeError, match="bps must be a real scalar"):
        fixed_slippage(PRICE, 1, bps=np.array([1.0, 5.0]))
    with pytest.raises(TypeError, match="impact_coeff must be a real scalar"):
        linear_impact(PRICE, 1, VOLUME, ADV, impact_coeff=[0.1, 0.2])
    with pytest.raises(TypeError, match="volatility must be a real scalar"):
        sqrt_impact(PRICE, 1, VOLUME, ADV, volatility=np.array([0.02, 0.03]))
    with pytest.raises(TypeError, match="eta must be a real scalar"):
        sqrt_impact(PRICE, 1, VOLUME, ADV, VOLATILITY, eta=[0.5, 0.6])


def test_a_bool_is_not_a_price():
    """``bool`` is a Real by inheritance but a caller error as a price."""
    with pytest.raises(TypeError, match="price must be a real scalar"):
        fixed_slippage(True, 1)


def test_scalar_calls_are_unchanged_and_return_floats():
    """The valid scalar path keeps its exact previous values and float type."""
    for value in (
        fixed_slippage(PRICE, 1, bps=5.0),
        linear_impact(PRICE, 1, VOLUME, ADV, impact_coeff=0.1),
        sqrt_impact(PRICE, 1, 250_000.0, ADV, VOLATILITY, eta=0.5),
    ):
        assert isinstance(value, float)

    assert fixed_slippage(PRICE, 1, bps=5.0) == pytest.approx(100.05, abs=1e-12)
    assert fixed_slippage(PRICE, -1, bps=5.0) == pytest.approx(99.95, abs=1e-12)
    assert linear_impact(PRICE, 1, VOLUME, ADV, impact_coeff=0.1) == pytest.approx(101.0, abs=1e-12)
    # numpy scalar types stay acceptable: they are real scalars, not containers.
    assert fixed_slippage(np.float64(PRICE), 1, bps=5.0) == pytest.approx(100.05, abs=1e-12)
    assert linear_impact(PRICE, 1, np.int64(VOLUME), ADV, impact_coeff=0.1) == pytest.approx(101.0, abs=1e-12)
