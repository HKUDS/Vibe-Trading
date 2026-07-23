"""report_audit must keep empty table cells so values stay under the right header."""

from __future__ import annotations

from src.tools.report_audit_tool import _parse_md_tables, extract_data_points


def test_parse_md_tables_keeps_empty_mid_cell_alignment() -> None:
    lines = [
        "| Metric | Q1 | Q2 |",
        "|---|---|---|",
        "| Revenue | 100M |  |",
        "| Net Income |  | 25M |",
    ]
    rows = _parse_md_tables(lines)
    by_label = {r[0]: (r[1], r[2]) for r in rows}
    assert by_label["Revenue"] == ("Q1", 100.0)
    assert by_label["Net Income"] == ("Q2", 25.0)


def test_extract_data_points_empty_mid_cell_uses_correct_quarter() -> None:
    md = """
| Metric | Q1 | Q2 |
|---|---|---|
| Revenue | 100M |  |
| Net Income |  | 25M |
"""
    points = {p["label"]: p["reported_value"] for p in extract_data_points(md)}
    assert points["Revenue · Q1"] == 100.0
    assert points["Net Income · Q2"] == 25.0
    assert "Net Income · Q1" not in points
