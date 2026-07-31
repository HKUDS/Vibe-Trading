"""Regression test for benford_check handling infinite values in financial_rigor_tool.

Locks out a bug where benford_check crashed with OverflowError: cannot convert float infinity
to integer when input values list contained inf or -inf.
"""

from src.tools.financial_rigor_tool import benford_check


def test_benford_check_handles_infinite_values():
    """Prove that benford_check safely skips inf/-inf values without raising OverflowError."""
    # Values containing infinity
    values = [10.0, 20.0, 30.0, float("inf"), float("-inf")]
    
    # On un-fixed code, math.floor(math.log10(inf)) raised OverflowError.
    # On fixed code, non-finite values are safely skipped.
    res = benford_check(values)
    assert isinstance(res, dict)
    assert res["sample_size"] == 3
