"""Accounting-parentheses negatives in report_audit extraction.

Financial reports write negatives as ``(25.3)`` / ``（25.3）``. The extractor
used to read the bare digits out of the parentheses, so a loss came out
positive and the closing paren swallowed the unit. Issue #1660.
"""

import json

import pytest

from src.tools.report_audit_tool import ReportAuditTool, extract_data_points


def _by_label(points, label_part):
    return [p for p in points if label_part in p["label"]]


def test_table_parenthesized_negative_keeps_sign_and_unit():
    md = (
        "| 项目 | 2024 |\n"
        "|---|---|\n"
        "| 净利润 | (25.3)亿 |\n"
    )
    pts = extract_data_points(md)
    hits = _by_label(pts, "净利润")
    assert len(hits) == 1
    assert hits[0]["reported_value"] == -25.3
    assert hits[0]["unit"] == "亿"


def test_table_fullwidth_parens_negative():
    md = (
        "| 项目 | 2024 |\n"
        "|---|---|\n"
        "| 归母净利润 | （3.20）亿元 |\n"
    )
    pts = extract_data_points(md)
    hits = _by_label(pts, "归母净利润")
    assert len(hits) == 1
    assert hits[0]["reported_value"] == -3.2
    assert hits[0]["unit"] == "亿元"


def test_table_positive_control_unchanged():
    md = (
        "| 项目 | 2024 |\n"
        "|---|---|\n"
        "| 营收 | 100.5亿 |\n"
    )
    pts = extract_data_points(md)
    hits = _by_label(pts, "营收")
    assert len(hits) == 1
    assert hits[0]["reported_value"] == 100.5
    assert hits[0]["unit"] == "亿"


def test_table_placeholder_cell_still_skipped():
    md = (
        "| 项目 | 2024 |\n"
        "|---|---|\n"
        "| 净利润 | (-) |\n"
    )
    assert extract_data_points(md) == []


def test_kv_line_parenthesized_negative_with_unit():
    pts = extract_data_points("净利润：(25.3)亿元，同比转亏")
    hits = _by_label(pts, "净利润")
    assert len(hits) == 1
    assert hits[0]["reported_value"] == -25.3
    assert hits[0]["unit"] == "亿元"


def test_kv_line_bare_paren_year_stays_dropped():
    # "(2024)" in prose is a year, not a negative; main drops it and the
    # fix must not start extracting it.
    assert extract_data_points("规划：(2024) 年投产") == []


def test_kv_line_positive_control_unchanged():
    pts = extract_data_points("营收：100.5亿元")
    hits = _by_label(pts, "营收")
    assert len(hits) == 1
    assert hits[0]["reported_value"] == 100.5
    assert hits[0]["unit"] == "亿元"


@pytest.mark.parametrize(
    "cell,unit",
    [
        ("(25.3亿)", "亿"),
        ("(25.3%)", "%"),
        ("$(25.3)M", "M"),
        ("($25.3)M", "M"),
        ("($25.3M)", "M"),
        ("( 25.3 )亿元", "亿元"),
        ("（ 25.3 亿元 ）", "亿元"),
        ("($25.3)", ""),
    ],
)
@pytest.mark.parametrize("table", [False, True])
def test_accounting_variants_keep_the_sign_and_unit(cell, unit, table):
    report = (
        f"| 净利润 | FY2025 |\n|---|---|\n| 归母净利润 | {cell} |"
        if table
        else f"净利润：{cell}"
    )
    points = extract_data_points(report)
    assert len(points) == 1
    assert points[0]["reported_value"] == -25.3
    assert points[0]["unit"] == unit


@pytest.mark.parametrize(
    "cell",
    [
        "(25.3）亿",
        "（25.3)亿",
        "(25.3亿",
        "25.3)亿",
        "((25.3))亿",
        "(25.3亿)M",
    ],
)
@pytest.mark.parametrize("table", [False, True])
def test_malformed_accounting_is_not_rescued_as_a_positive(cell, table):
    report = (
        f"| 指标 | FY2025 |\n|---|---|\n| 净利润 | {cell} |"
        if table
        else f"净利润：{cell}"
    )
    assert extract_data_points(report) == []


@pytest.mark.parametrize(
    "text",
    [
        "规划：(2024) May",
        "规划：(2024) Million",
        "规划：(2024) Times",
        "估值：(25.3)xylophone",
    ],
)
def test_latin_word_is_not_an_accounting_unit(text):
    assert extract_data_points(text) == []


@pytest.mark.parametrize("number", ["1000000000000001", "9" * 310])
@pytest.mark.parametrize("table", [False, True])
def test_accounting_magnitude_guard_and_strict_json(number, table):
    report = (
        f"| 指标 | FY2025 |\n|---|---|\n| 净利润 | ({number})亿 |"
        if table
        else f"净利润：({number})亿"
    )
    assert extract_data_points(report) == []
    result = json.loads(
        ReportAuditTool().execute(command="extract", report_text=report)
    )
    assert result["status"] == "ok"
    assert result["total_extracted"] == 0


@pytest.mark.parametrize("wrapped", [False, True])
def test_magnitude_boundary_keeps_the_existing_table_and_prose_conventions(wrapped):
    value = "1000000000000000"
    if wrapped:
        value = f"({value})"
    assert (
        extract_data_points(f"| 指标 | FY2025 |\n|---|---|\n| 净利润 | {value}亿 |")
        == []
    )
    points = extract_data_points(f"净利润：{value}亿")
    assert points[0]["reported_value"] == (-1e15 if wrapped else 1e15)


@pytest.mark.parametrize(
    "report,labels,values",
    [
        ("收入：100亿元，净利润：20亿元", ["收入", "净利润"], [100, 20]),
        ("Revenue: 100M; Profit: 20M", ["Revenue", "Profit"], [100, 20]),
        ("收入：100亿元 收入：100亿元", ["收入"], [100]),
        ("Revenue: 100M; Profit: ($20M)", ["Revenue", "Profit"], [100, -20]),
    ],
)
def test_multiple_prose_values_do_not_become_the_next_label(report, labels, values):
    points = extract_data_points(report)
    assert [point["label"] for point in points] == labels
    assert [point["reported_value"] for point in points] == values
