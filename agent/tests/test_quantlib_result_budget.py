"""The real quantlib consumer must bound its serialized result, not only numbers."""

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from src.tools.quantlib_tool import (
    QuantlibCallTool,
    _Budget,
    _encode,
    _MAX_RESULT_LEAVES,
)


def leaves(value):
    if isinstance(value, dict):
        return sum(leaves(v) for v in value.values())
    if isinstance(value, list):
        return sum(leaves(v) for v in value)
    return 1


def test_real_exported_monte_carlo_result_stays_within_budget():
    result = json.loads(
        QuantlibCallTool(roots=FileRoots.from_config(get_env_config().api)).execute(
            action="call",
            module="risk",
            function="monte_carlo_gbm",
            kwargs={
                "s0": 100,
                "mu": 0,
                "sigma": 0,
                "n_steps": 1,
                "n_paths": 10000,
                "seed": 7,
            },
        )
    )
    assert result["ok"] and result["truncated"]
    assert leaves(result["result"]) <= _MAX_RESULT_LEAVES
    assert all(row == [100, 100] for row in result["result"])
    assert len(result["result"]) == _MAX_RESULT_LEAVES // 2


@pytest.mark.parametrize(
    "value",
    [
        list(range(6000)),
        np.arange(6000),
        {str(i): i for i in range(6000)},
        {"rows": [list(range(100)) for _ in range(100)]},
        pd.Series(range(6000)),
        pd.DataFrame({"a": range(6000), "b": range(6000)}),
    ],
)
def test_every_container_stops_at_the_shared_budget(value):
    budget = _Budget()
    encoded = _encode(value, budget)
    assert budget.truncated
    assert leaves(encoded) <= _MAX_RESULT_LEAVES
    assert budget.leaves == leaves(encoded)


@dataclass
class Summary:
    count: int
    values: list


@pytest.mark.parametrize(
    "value,expected",
    [
        ([1, 2, 3], [1, 2, 3]),
        (np.array([[1, 2], [3, 4]]), [[1, 2], [3, 4]]),
        (
            {"count": np.int64(2), "values": [np.float64(1.5), True]},
            {"count": 2, "values": [1.5, True]},
        ),
        (Summary(2, [1, 2]), {"count": 2, "values": [1, 2]}),
        (
            pd.Series([1, 2], index=["a", "b"]),
            {"__series__": {"index": ["a", "b"], "values": [1, 2]}},
        ),
        (
            pd.DataFrame([[1, 2]], index=["x"], columns=["a", "b"]),
            {
                "__dataframe__": {
                    "index": ["x"],
                    "columns": ["a", "b"],
                    "data": [[1, 2]],
                }
            },
        ),
    ],
)
def test_small_results_keep_their_json_contract(value, expected):
    budget = _Budget()
    assert _encode(value, budget) == expected
    assert not budget.truncated


def test_exact_budget_is_not_reported_as_truncated():
    budget = _Budget()
    assert _encode(list(range(_MAX_RESULT_LEAVES)), budget) == list(
        range(_MAX_RESULT_LEAVES)
    )
    assert not budget.truncated
