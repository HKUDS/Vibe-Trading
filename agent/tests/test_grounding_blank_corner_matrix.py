"""Regression for square Markdown matrices with an empty header corner.

Synthetic tickers only; no external market data or provider dependencies.
"""

from __future__ import annotations

from evals.grounding.figures import parse_figures_block, scan_figures, table_rows


def _matrix(header: tuple[str, ...], rows: tuple[str, ...]) -> str:
    return (
        "\n".join(
            [
                "| | " + " | ".join(header) + " |",
                "| --- | " + " | ".join("---:" for _ in header) + " |",
                *[
                    "| **"
                    + symbol
                    + "** | "
                    + " | ".join(
                        "1.0000" if symbol == target else "0.2500" for target in header
                    )
                    + " |"
                    for symbol in rows
                ],
            ]
        )
        + "\n"
    )


def test_complete_13_by_13_matrix_binds_every_cell_to_its_row_symbol() -> None:
    names = tuple(f"STK{i}" for i in range(1, 14))
    source = _matrix(names, names)
    assert all(row.symbol_column == 0 for row in table_rows(source))
    figures = [
        f
        for f in scan_figures(source, parse_figures_block(source))
        if f.shape == "measured"
    ]
    assert len(figures) == 169
    assert [(f.symbol, f.value) for f in figures] == [
        (row, 1.0 if row == column else 0.25)
        for row in names
        for column in names
    ]


def test_incomplete_duplicate_and_mismatched_axes_stay_unscoped() -> None:
    names = ("STK1", "STK2", "STK3")
    for rows in (
        ("STK1", "STK2"),
        ("STK1", "STK1", "STK3"),
        ("STK1", "STK2", "OTHER"),
    ):
        source = _matrix(names, rows)
        assert all(row.symbol_column is None for row in table_rows(source))
        figs = [
            f
            for f in scan_figures(source, parse_figures_block(source))
            if f.shape == "measured"
        ]
        assert all(f.symbol is None for f in figs)


def test_explicit_symbol_header_still_works() -> None:
    source = "| Symbol | STK1 | STK2 |\n| --- | ---: | ---: |\n| STK1 | 1.0 | 0.2 |\n"
    figures = [
        f
        for f in scan_figures(source, parse_figures_block(source))
        if f.shape == "measured"
    ]
    assert all(f.symbol == "STK1" for f in figures)
