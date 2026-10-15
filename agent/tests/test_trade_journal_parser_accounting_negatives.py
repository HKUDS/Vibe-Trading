"""Accounting-style negatives such as ``(1,234.50)`` must not collapse to 0.0."""

from __future__ import annotations

import pytest

from src.tools.trade_journal_parsers import _to_float


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(1,234.50)", -1234.5),
        ("($5.00)", -5.0),
        ("$(5)", -5.0),
        (" ( 12 ) ", -12.0),
        ("(USD 7.25)", -7.25),
    ],
)
def test_parenthesised_numbers_are_negative(raw: str, expected: float) -> None:
    assert _to_float(raw) == expected


@pytest.mark.parametrize("raw", ["()", "(-5)", "(+5)", "(abc)", "(1", "1)", "(nan)", "(inf)"])
def test_malformed_parentheses_still_fall_back_to_default(raw: str) -> None:
    assert _to_float(raw) == 0.0
    assert _to_float(raw, default=-1.0) == -1.0


@pytest.mark.parametrize(("raw", "expected"), [("1,234.50", 1234.5), ("-5", -5.0), ("−5", -5.0), ("$12", 12.0)])
def test_plain_numbers_are_unchanged(raw: str, expected: float) -> None:
    assert _to_float(raw) == expected
