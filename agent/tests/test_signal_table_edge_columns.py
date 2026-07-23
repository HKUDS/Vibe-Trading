"""Signal markdown tables must keep empty leading/trailing columns."""

from __future__ import annotations

from src.channels.signal import _sig_render_table


def test_sig_render_table_keeps_trailing_empty_column() -> None:
    box = _sig_render_table(
        [
            "|Name|Qty||",
            "|---|---|---|",
            "|a|1||",
            "|b|2||",
        ]
    )
    rule = box.split("\n")[1]
    assert rule.count("  ") == 2


def test_sig_render_table_keeps_leading_empty_header_with_row_labels() -> None:
    box = _sig_render_table(
        [
            "||Name|Qty|",
            "|---|---|---|",
            "|row1|a|1|",
            "|row2|b|2|",
        ]
    )
    header, _rule, data_row = box.split("\n")[:3]
    assert data_row.startswith("row1")
    # Empty leading header must keep Name aligned over the second data cell.
    assert header.index("Name") == data_row.index("a")
    assert "1" in data_row
