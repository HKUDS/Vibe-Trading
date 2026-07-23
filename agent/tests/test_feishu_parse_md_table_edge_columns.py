"""Feishu markdown tables must keep empty leading/trailing columns."""

from __future__ import annotations

from src.channels.feishu import FeishuChannel


def test_parse_md_table_keeps_trailing_empty_header_column() -> None:
    table = "|Name|Qty||\n|---|---|---|\n|a|1|note|\n|b|2|other|\n"
    parsed = FeishuChannel._parse_md_table(table)
    assert parsed is not None
    assert [c["display_name"] for c in parsed["columns"]] == ["Name", "Qty", ""]
    assert parsed["rows"] == [
        {"c0": "a", "c1": "1", "c2": "note"},
        {"c0": "b", "c1": "2", "c2": "other"},
    ]


def test_parse_md_table_keeps_leading_empty_header_with_row_labels() -> None:
    table = "||Name|Qty|\n|---|---|---|\n|row1|a|1|\n|row2|b|2|\n"
    parsed = FeishuChannel._parse_md_table(table)
    assert parsed is not None
    assert [c["display_name"] for c in parsed["columns"]] == ["", "Name", "Qty"]
    assert parsed["rows"] == [
        {"c0": "row1", "c1": "a", "c2": "1"},
        {"c0": "row2", "c1": "b", "c2": "2"},
    ]
