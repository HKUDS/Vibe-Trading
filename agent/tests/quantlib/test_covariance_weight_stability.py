import numpy as np
import pytest
from src.quantlib.portfolio import hierarchical_risk_parity, inverse_variance_weights


def test_inverse_weights_remain_finite_for_small_positive_variances() -> None:
    cov = np.diag([1e-310, 2e-310])
    actual = inverse_variance_weights(cov)
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(actual, [2 / 3, 1 / 3])


@pytest.mark.parametrize("variance", [0.0, -1.0, float("nan"), float("inf")])
def test_singleton_hrp_rejects_invalid_variance_before_assigning_weight(
    variance: float,
) -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        hierarchical_risk_parity(np.array([[variance]]))


@pytest.mark.parametrize("variance", [float("nan"), float("inf")])
def test_inverse_weights_reject_nonfinite_variance(variance: float) -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        inverse_variance_weights(np.diag([0.04, variance]))


def test_valid_singleton_and_ordinary_inverse_weights_are_unchanged() -> None:
    np.testing.assert_array_equal(hierarchical_risk_parity(np.array([[0.04]])), [1.0])
    np.testing.assert_allclose(
        inverse_variance_weights(np.diag([0.04, 0.16])), [0.8, 0.2]
    )
