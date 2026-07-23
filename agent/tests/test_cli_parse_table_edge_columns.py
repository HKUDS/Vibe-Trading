"""CLI transcript tables must keep empty leading/trailing columns."""

from __future__ import annotations

from cli.ui.transcript import _parse_table, _split_row


def test_split_row_keeps_empty_edge_cells() -> None:
    assert _split_row("|Name|Qty||") == ["Name", "Qty", ""]
    assert _split_row("||Name|Qty|") == ["", "Name", "Qty"]
    assert _split_row("|a|1|note|") == ["a", "1", "note"]


def test_parse_table_keeps_trailing_empty_header_column() -> None:
    lines = [
        "|Name|Qty||",
        "|---|---|---|",
        "|a|1|note|",
        "|b|2|other|",
    ]
    table = _parse_table(lines)
    assert table is not None
    assert [col.header for col in table.columns] == ["Name", "Qty", ""]
    assert [col._cells for col in table.columns] == [
        ["a", "b"],
        ["1", "2"],
        ["note", "other"],
    ]


def test_parse_table_keeps_leading_empty_header_with_row_labels() -> None:
    lines = [
        "||Name|Qty|",
        "|---|---|---|",
        "|row1|a|1|",
        "|row2|b|2|",
    ]
    table = _parse_table(lines)
    assert table is not None
    assert [col.header for col in table.columns] == ["", "Name", "Qty"]
    assert [col._cells for col in table.columns] == [
        ["row1", "row2"],
        ["a", "b"],
        ["1", "2"],
    ]
