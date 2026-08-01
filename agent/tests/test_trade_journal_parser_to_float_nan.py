"""Regression test for _to_float handling of NaN strings in trade journal parsers.

Locks out a bug where _to_float returned float("nan") (where math.isnan is True)
when parsing "nan" or "NaN" cell strings instead of returning the specified default float.
"""

import math
from src.tools.trade_journal_parsers import _to_float


def test_to_float_nan_string_returns_default():
    """Prove that _to_float returns default when given 'nan' or non-finite values."""
    res_nan = _to_float("nan", default=0.0)
    assert not math.isnan(res_nan), f"Expected 0.0 for 'nan', got {res_nan}"
    assert res_nan == 0.0

    res_upper_nan = _to_float("NaN", default=0.0)
    assert not math.isnan(res_upper_nan), f"Expected 0.0 for 'NaN', got {res_upper_nan}"
    assert res_upper_nan == 0.0

    res_inf = _to_float("inf", default=0.0)
    assert res_inf == 0.0
