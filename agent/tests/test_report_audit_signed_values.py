"""Signed financial values must retain their sign through extraction and audit."""

from __future__ import annotations

import json

import pytest

from src.tools.report_audit_tool import ReportAuditTool, extract_data_points


@pytest.mark.parametrize("value", ["-$25M", "−$25M", "- $25M", "$-25M", "($-25M)"])
@pytest.mark.parametrize("table", [False, True])
def test_negative_currency_keeps_sign_on_either_side_of_symbol(value: str, table: bool) -> None:
    report = (
        f"| Metric | Value |\n|---|---|\n| Net income | {value} |"
        if table else f"Net income: {value}"
    )
    points = extract_data_points(report)
    assert len(points) == 1
    assert points[0]["reported_value"] == -25


@pytest.mark.parametrize("value", ["-25M", "−25M", "+25M", "25M", "-1,234.5M"])
@pytest.mark.parametrize("table", [False, True])
def test_extract_preserves_financial_value_sign(value: str, table: bool) -> None:
    expected = float(value[:-1].replace("−", "-").replace(",", ""))
    report = (
        f"| Metric | FY2025 |\n|---|---|\n| Net income | {value} |\n"
        if table
        else f"Net income: {value}\n"
    )
    points = extract_data_points(report)
    assert len(points) == 1
    assert points[0]["reported_value"] == expected
    assert points[0]["unit"] == "M"


@pytest.mark.parametrize(
    "reported,fetched,expected", [(-25, 25, "FAIL"), (-25, -25, "PASS")]
)
def test_extract_to_verdict_does_not_certify_a_sign_error(
    reported: int, fetched: int, expected: str
) -> None:
    tool = ReportAuditTool()
    extracted = json.loads(
        tool.execute(
            command="extract",
            report_text=f"| Metric | FY2025 |\n|---|---|\n| Net income | {reported}M |",
            seed=1,
        )
    )
    point = extracted["sample"][0]
    verdict = json.loads(
        tool.execute(
            command="verdict",
            results=[{**point, "fetched_value": fetched, "fetched_source": "fixture"}],
        )
    )
    assert verdict["verdict"] == expected
