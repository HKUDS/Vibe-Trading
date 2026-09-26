"""A run's final positions row is its liquidation, not its book.

Every run exits on the last bar (``end_of_backtest``), so ``positions.csv``
ends with an all-zero row. Reading only that row made Brinson report a
portfolio that had been invested for years as having "all position weights
zero" -- a one-row problem that nulled the whole section.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.api.attribution_core import _attribution_load_position_weights

SYMBOLS = ["AAA.HK", "BBB.HK"]


def _write_positions(run_dir: Path, rows: list[list[Any]]) -> None:
    """Write ``timestamp`` + per-symbol weight columns, the real artifact layout."""
    path = run_dir / "artifacts" / "positions.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp," + ",".join(SYMBOLS)]
    lines += [",".join(str(cell) for cell in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_end_of_backtest_flat_row_is_skipped(tmp_path: Path) -> None:
    """The held row before the liquidation is the one that describes the book."""
    _write_positions(
        tmp_path,
        [
            ["2026-09-23", 0.40, 0.35],
            ["2026-09-24", 0.42, 0.33],
            ["2026-09-25", 0.0, 0.0],  # end-of-backtest liquidation
        ],
    )
    notes: list[str] = []

    weights = _attribution_load_position_weights(tmp_path, notes)

    assert weights == {"AAA.HK": 0.42, "BBB.HK": 0.33}
    assert any("end-of-backtest liquidation (2026-09-24)" in note for note in notes)


def test_a_held_final_row_is_used_unchanged(tmp_path: Path) -> None:
    """A run still holding on its final bar must read exactly that row."""
    _write_positions(
        tmp_path,
        [
            ["2026-09-24", 0.42, 0.33],
            ["2026-09-25", 0.50, 0.20],
        ],
    )
    notes: list[str] = []

    weights = _attribution_load_position_weights(tmp_path, notes)

    assert weights == {"AAA.HK": 0.50, "BBB.HK": 0.20}
    assert notes == []


def test_a_book_that_never_held_still_reads_flat(tmp_path: Path) -> None:
    """True negative: all-zero throughout must stay all-zero.

    This is the case the downstream zero-check was written for, and the fix
    must not paper over it.
    """
    _write_positions(
        tmp_path,
        [
            ["2026-09-23", 0.0, 0.0],
            ["2026-09-24", 0.0, 0.0],
            ["2026-09-25", 0.0, 0.0],
        ],
    )
    notes: list[str] = []

    weights = _attribution_load_position_weights(tmp_path, notes)

    assert weights == {"AAA.HK": 0.0, "BBB.HK": 0.0}
    assert not any("end-of-backtest" in note for note in notes)


def test_a_book_flat_before_the_close_is_not_replaced_by_an_older_one(
    tmp_path: Path,
) -> None:
    """Only the liquidation row is stepped over, never an earlier exit."""
    _write_positions(
        tmp_path,
        [
            ["2026-09-22", 0.40, 0.35],
            ["2026-09-23", 0.0, 0.0],  # the strategy itself exited here
            ["2026-09-24", 0.0, 0.0],
            ["2026-09-25", 0.0, 0.0],  # end-of-backtest liquidation
        ],
    )
    notes: list[str] = []

    weights = _attribution_load_position_weights(tmp_path, notes)

    assert weights == {"AAA.HK": 0.0, "BBB.HK": 0.0}
    assert not any("end-of-backtest" in note for note in notes)


def test_missing_artifact_still_reports_not_found(tmp_path: Path) -> None:
    """The other skip reasons must keep their own wording."""
    notes: list[str] = []

    weights = _attribution_load_position_weights(tmp_path, notes)

    assert weights is None
    assert notes == ["brinson attribution skipped: positions.csv not found"]
