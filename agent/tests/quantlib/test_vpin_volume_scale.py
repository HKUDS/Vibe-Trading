"""VPIN completion must not depend on the unit chosen for volume."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json

import numpy as np
import pytest

from src.quantlib.microstructure import vpin
from src.tools.quantlib_tool import QuantlibCallTool


@pytest.mark.parametrize("scale", [1e-12, 1e-10, 1e-8, 1.0, 1e8])
def test_incomplete_bucket_is_not_emitted_at_any_volume_scale(scale: float) -> None:
    # One buy unit fills only half of a two-unit bucket.
    assert vpin([scale], [0.0], 2 * scale, n_buckets=1).size == 0


@pytest.mark.parametrize("scale", [1e-12, 1e-10, 1e-8, 1.0, 1e8])
def test_completed_bucket_and_partial_tail_are_scale_invariant(scale: float) -> None:
    # Bar1 buys1; bar2 buys1/sells1. The completed two-unit bucket
    # has buys1.5/sells0.5 => imbalance1/volume2 = 0.5. The tail is incomplete.
    actual = vpin([scale, scale], [0.0, scale], 2 * scale, n_buckets=1)
    np.testing.assert_allclose(actual, [0.5], rtol=1e-12)


@pytest.mark.parametrize("scale", [1e-12, 1.0, 1e8])
def test_a_completed_bucket_is_still_emitted(scale: float) -> None:
    np.testing.assert_allclose(vpin([2 * scale], [0.0], 2 * scale, n_buckets=1), [1.0])


def test_quantlib_call_keeps_completed_bucket_count_for_fractional_volume() -> None:
    response = json.loads(
        QuantlibCallTool(roots=FileRoots.from_config(get_env_config().api)).execute(
            action="call",
            module="microstructure",
            function="vpin",
            kwargs={
                "buy_volume": [1e-10, 1e-10],
                "sell_volume": [0.0, 1e-10],
                "bucket_size": 2e-10,
                "n_buckets": 1,
            },
        )
    )
    assert response["ok"] is True
    assert response["result"] == pytest.approx([0.5])
