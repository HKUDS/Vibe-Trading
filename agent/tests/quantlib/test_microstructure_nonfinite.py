import numpy as np
import pytest

from src.quantlib.microstructure import kyles_lambda, roll_effective_spread, vpin


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_roll_spread_rejects_nonfinite_prices(bad):
    with pytest.raises(ValueError, match="finite"):
        roll_effective_spread([100.0, 101.0, bad, 100.0])


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_kyles_lambda_rejects_nonfinite_inputs(bad):
    with pytest.raises(ValueError, match="finite"):
        kyles_lambda([1.0, bad], [2.0, 3.0])
    with pytest.raises(ValueError, match="finite"):
        kyles_lambda([1.0, 2.0], [3.0, bad])


def test_vpin_rejects_negative_volume():
    with pytest.raises(ValueError, match="non-negative"):
        vpin([10.0, -1.0], [5.0, 5.0], bucket_size=10.0)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_vpin_rejects_nonfinite_volume(bad):
    with pytest.raises(ValueError, match="finite"):
        vpin([10.0, bad], [5.0, 5.0], bucket_size=10.0)
