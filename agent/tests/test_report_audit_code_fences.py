"""Report examples inside fenced code are not auditable report facts."""

import mistune
import pytest

from src.tools.report_audit_tool import extract_data_points


@pytest.mark.parametrize(
    "opener,inner,closer",
    [
        ("```markdown", "", "```"),
        ("~~~markdown", "", "~~~"),
        ("````markdown", "```\n", "````"),
        ("```markdown", "~~~\n", "```"),
        ("```markdown", "", "`````"),
        ("   ```markdown", "", "   ```"),
    ],
)
def test_extract_only_visible_report_facts(opener, inner, closer):
    report = (
        "Actual revenue: 120M\n\n"
        + opener
        + "\n"
        + inner
        + "Example profit: 888M\n"
        + "| Metric | Example |\n| --- | --- |\n| Revenue | 999M |\n"
        + closer
        + "\n\nActual profit: 25M\n"
    )
    # An independent Markdown parser confirms the examples are one code block,
    # while the two actual facts remain ordinary rendered paragraphs.
    ast = mistune.create_markdown(renderer="ast", plugins=["table"])(report)
    blocks = [block for block in ast if block["type"] == "block_code"]
    assert len(blocks) == 1
    assert "999M" in blocks[0]["raw"]
    assert not any(block["type"] == "table" for block in ast)
    points = extract_data_points(report)
    assert [(p["label"], p["reported_value"]) for p in points] == [
        ("Actual revenue", 120.0),
        ("Actual profit", 25.0),
    ]
    assert points[-1]["line_number"] == len(report.splitlines())


def test_unclosed_fence_hides_remainder_but_keeps_earlier_fact():
    report = (
        "Actual revenue: 120M\n\n~~~markdown\n"
        "| Metric | Example |\n| --- | --- |\n| Revenue | 999M |\n"
        "Example profit: 888M\n"
    )
    points = extract_data_points(report)
    assert [(p["label"], p["reported_value"]) for p in points] == [
        ("Actual revenue", 120.0)
    ]


def test_real_table_and_inline_code_marker_remain_auditable():
    report = (
        "The inline marker `~~~` is not a fence.\n\n"
        "| Metric | 2025 |\n| --- | --- |\n| Revenue | 120M |\n"
    )
    points = extract_data_points(report)
    assert [(p["label"], p["reported_value"], p["line_number"]) for p in points] == [
        ("Revenue · 2025", 120.0, 5)
    ]
