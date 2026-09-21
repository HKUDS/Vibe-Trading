"""Slack markdown tables must keep empty leading/trailing columns."""

from __future__ import annotations

import re

from tests.slack_stubs import install_slack_stubs

install_slack_stubs()

from src.channels.slack import SlackChannel  # noqa: E402


def test_split_md_row_keeps_empty_edge_cells() -> None:
    assert SlackChannel._split_md_row("|Name|Qty||") == ["Name", "Qty", ""]
    assert SlackChannel._split_md_row("||Name|Qty|") == ["", "Name", "Qty"]
    assert SlackChannel._split_md_row("|a|1|note|") == ["a", "1", "note"]


def test_convert_table_keeps_leading_empty_header_row_labels() -> None:
    md = "||Name|Qty|\n|---|---|---|\n|row1|a|1|\n|row2|b|2|\n"
    match = SlackChannel._TABLE_RE.search(md)
    assert match is not None
    out = SlackChannel._convert_table(match)
    assert out == (
        "****: row1 · **Name**: a · **Qty**: 1\n"
        "****: row2 · **Name**: b · **Qty**: 2"
    )


def test_convert_table_keeps_trailing_empty_header_slot() -> None:
    md = "|Name|Qty||\n|---|---|---|\n|a|1|note|\n|b|2|other|\n"
    match = SlackChannel._TABLE_RE.search(md)
    assert match is not None
    out = SlackChannel._convert_table(match)
    assert out == (
        "**Name**: a · **Qty**: 1 · ****: note\n"
        "**Name**: b · **Qty**: 2 · ****: other"
    )
