"""CLI formatters must switch unit when rounding reaches the next unit."""

from __future__ import annotations

import pytest

from cli.utils.format import abbreviate_num, format_duration, format_tokens


@pytest.mark.parametrize(
    "count, expected",
    [(999_950, "1.0M tokens"), (999_949, "999.9k tokens"), (1_200, "1.2k tokens"),
     (999_950_000, "1.0B tokens"), (452, "452 tokens")],
)
def test_format_tokens_unit_boundary(count: int, expected: str) -> None:
    assert format_tokens(count) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(999_960, "1.0M"), (999_940, "999.9k"), (12_400, "12.4k"), (-999_960, "-1.0M"),
     (999_960_000, "1.0B")],
)
def test_abbreviate_num_unit_boundary(value: float, expected: str) -> None:
    assert abbreviate_num(value) == expected


@pytest.mark.parametrize(
    "ms, expected",
    [(999.6, "1.0s"), (999.4, "999ms"), (59_960, "1m 00s"), (59_940, "59.9s"),
     (1_400, "1.4s"), (230, "230ms"), (252_000, "4m 12s")],
)
def test_format_duration_unit_boundary(ms: float, expected: str) -> None:
    assert format_duration(ms) == expected
