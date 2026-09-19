import numpy as np
import pytest

from src.quantlib.copula import pseudo_observations


def test_pseudo_observations_give_ties_equal_rank():
    result = pseudo_observations(np.array([1.0, 1.0, 3.0]))
    assert result[0] == pytest.approx(result[1])
    assert result.tolist() == pytest.approx([0.375, 0.375, 0.75])


def test_pseudo_observations_preserve_missing_values_per_column():
    data = np.array([[1.0, 5.0], [1.0, np.nan], [3.0, 7.0]])
    result = pseudo_observations(data)
    assert result[0, 0] == pytest.approx(result[1, 0])
    assert np.isnan(result[1, 1])
    assert result[0, 1] == pytest.approx(1.0 / 3.0)
    assert result[2, 1] == pytest.approx(2.0 / 3.0)
