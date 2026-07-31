"""Regression test for _coerce_ids handling non-iterable inputs in alpha_compare_tool.

Locks out a bug where _coerce_ids raised TypeError: 'int' object is not iterable
when alpha_ids parameter was passed a non-string non-sequence (e.g. 123, True).
"""

from src.tools.alpha_compare_tool import _coerce_ids


def test_coerce_ids_handles_non_iterable_raw_input():
    """Prove that _coerce_ids returns an empty list for non-iterable input types without raising TypeError."""
    assert _coerce_ids(123) == []
    assert _coerce_ids(True) == []
    assert _coerce_ids(None) == []
    assert _coerce_ids("alpha1, alpha2") == ["alpha1", "alpha2"]
    assert _coerce_ids(["alpha1", "alpha2"]) == ["alpha1", "alpha2"]
