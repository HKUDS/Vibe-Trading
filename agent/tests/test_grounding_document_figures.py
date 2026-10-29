"""Figures a document states ground the report written from that document.

Regression history (2026-10-26, #2050): a user uploaded an annual report, the
agent read it with ``read_document``, and the report quoted the document's own
revenue, margin and EPS — every one of which the gate redacted as unsourced. The
reader answers with one prose blob, so the numeric-leaf walk every other tool
goes through found nothing to record, and a figure quoted from the file had no
evidence behind it.

What stays closed is pinned beside each change: only numbers carrying a mark of
measurement count (a page number, a section number or a year in running text is
not a finding, and admitting bare integers would let an invented small figure
match by chance), a document this run wrote is never evidence, and nothing under
the run directory counts as a document — the ledger's own artifacts must not
launder themselves through the reader.

Every value here is synthetic; no market data lives in the repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger

REPORT = """第一节 经营回顾

公司本年度毛利率 41.2%，每股收益 2.87 元，营收增速 12.4%。
员工总数 3400 人，报告日期 2025 年 3 月 18 日，第 12 页。
"""


def _document_envelope(path: Path, text: str) -> str:
    return json.dumps(
        {
            "status": "ok",
            "file": path.name,
            "format": path.suffix.lstrip(".") or "txt",
            "char_count": len(text),
            "truncated": False,
            "text": text,
        },
        ensure_ascii=False,
    )


def _read_document(
    ledger: GroundingLedger,
    path: Path,
    call_id: str,
    text: str = REPORT,
) -> None:
    ledger.ingest_tool_result(
        tool_name="read_document",
        arguments={"file_path": str(path)},
        result=_document_envelope(path, text),
        call_id=call_id,
        success=True,
    )


def _ledger_with_upload(tmp_path: Path) -> tuple[GroundingLedger, Path]:
    """A ledger whose run directory sits beside, not above, the upload."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    document = uploads / "ar2025.pdf"
    document.write_text(REPORT, encoding="utf-8")
    return GroundingLedger(run_dir=run_dir, user_message="读一下这份年报，总结经营情况"), document


def _declared(prose: str, *lines: str) -> str:
    return prose + "\n\n```figures\n" + "\n".join(lines) + "\n```"


def test_a_document_figure_grounds_the_answer_that_quotes_it(tmp_path: Path) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1")

    result = ledger.validate_final_answer(
        _declared(
            "年报显示毛利率 41.2%，每股收益 2.87 元，营收增速 12.4%。",
            "41.2% | observed | 毛利率 | ar2025.pdf",
            "2.87 | observed | 每股收益 | ar2025.pdf",
            "12.4% | observed | 营收增速 | ar2025.pdf",
        )
    )

    assert result.valid, result.issues


def test_a_document_figure_is_not_evidence_before_the_document_is_read(
    tmp_path: Path,
) -> None:
    """The document exists on disk but the model never saw it."""
    ledger, _ = _ledger_with_upload(tmp_path)

    result = ledger.validate_final_answer(
        _declared("年报显示毛利率 41.2%。", "41.2% | observed | 毛利率 | ar2025.pdf")
    )

    assert not result.valid


def test_a_page_number_and_a_year_are_not_findings(tmp_path: Path) -> None:
    """Page 12 and the year 2025 are layout, not facts about the company."""
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1")

    values = {record.value for record in ledger._evidence}

    assert 41.2 in values and 2.87 in values and 12.4 in values
    assert 12 not in values, "页码进了账本"
    assert 2025 not in values, "年份进了账本"
    assert 3400 not in values, "人数这类无计量标记的整数不该进账本"


def test_a_document_this_run_wrote_is_not_evidence(tmp_path: Path) -> None:
    """Reading back the run's own draft is not observation."""
    ledger, document = _ledger_with_upload(tmp_path)
    ledger.ingest_tool_result(
        tool_name="write_file",
        arguments={"path": str(document)},
        result=json.dumps({"status": "ok", "path": str(document)}),
        call_id="model-write-doc",
        success=True,
    )
    _read_document(ledger, document, "doc-1")

    result = ledger.validate_final_answer(
        _declared("年报显示毛利率 41.2%。", "41.2% | observed | 毛利率 | ar2025.pdf")
    )

    assert not result.valid


def test_a_document_inside_the_run_directory_is_not_evidence(tmp_path: Path) -> None:
    """The ledger's own artifacts must not launder themselves through the reader."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="读一下这份年报")
    document = tmp_path / "report.md"
    document.write_text(REPORT, encoding="utf-8")
    _read_document(ledger, document, "doc-1")

    result = ledger.validate_final_answer(
        _declared("报告显示毛利率 41.2%。", "41.2% | observed | 毛利率 | report.md")
    )

    assert not result.valid


def test_an_error_envelope_records_nothing(tmp_path: Path) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    ledger.ingest_tool_result(
        tool_name="read_document",
        arguments={"file_path": str(document)},
        result=json.dumps({"status": "error", "error": "unsupported format"}),
        call_id="doc-1",
        success=False,
    )

    result = ledger.validate_final_answer(
        _declared("年报显示毛利率 41.2%。", "41.2% | observed | 毛利率 | ar2025.pdf")
    )

    assert not result.valid


@pytest.mark.parametrize("ref", ["doc-1", "read_document", "ar2025.pdf", "doc-1::document.figure"])
@pytest.mark.parametrize(
    ("value", "written"),
    [("763,154,445.01", "763,154,445.01 元"), ("191,586,814.48", "1.92亿元")],
)
def test_document_table_amount_can_be_restated_with_a_unit(
    tmp_path: Path, ref: str, value: str, written: str,
) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", f"单位：元\n| 项目 | 金额 |\n| 营业收入 | {value} |")
    result = ledger.validate_final_answer(
        _declared(f"营业收入为 {written}。", f"{written} | observed | 营业收入 | {ref}")
    )
    assert result.valid, result.issues


@pytest.mark.parametrize("written", ["863,154,445.01 元", "763,154,445.01 USD", "763,154,445.01%"])
def test_document_unit_restatement_does_not_invent_value_currency_or_ratio(
    tmp_path: Path, written: str,
) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", "| 营业收入 | 763,154,445.01 |")
    result = ledger.validate_final_answer(
        _declared(f"营业收入为 {written}。", f"{written} | observed | 营业收入 | doc-1")
    )
    assert not result.valid


def test_document_unit_restatement_keeps_exact_source_binding(tmp_path: Path) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", "| 营业收入 | 763,154,445.01 |")
    _read_document(ledger, document.with_name("other.pdf"), "doc-2", "| 营业收入 | 863,154,445.01 |")
    result = ledger.validate_final_answer(
        _declared("营业收入为 863,154,445.01 元。", "863,154,445.01 元 | observed | 营业收入 | doc-1")
    )
    assert not result.valid


@pytest.mark.parametrize("formula", ["39.66% - 38.96%", "39.66 - 38.96"])
def test_document_percentage_points_can_be_declared_as_written(tmp_path: Path, formula: str) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", "毛利率分别为 39.66% 和 38.96%。")
    result = ledger.validate_final_answer(
        _declared("毛利率上升 0.70个百分点。", f"0.70个百分点 | derived | {formula} | doc-1")
    )
    assert result.valid, result.issues


def test_document_percentage_point_derivation_still_needs_both_operands(tmp_path: Path) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", "毛利率为 39.66%。")
    result = ledger.validate_final_answer(
        _declared("毛利率上升 0.70个百分点。", "0.70个百分点 | derived | 39.66% - 38.96% | doc-1")
    )
    assert not result.valid


def test_money_can_be_derived_from_explicitly_referenced_document_cells(tmp_path: Path) -> None:
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", "| 本期 | 上期 |\n| 763,154,445.01 | 663,154,445.01 |")
    result = ledger.validate_final_answer(
        _declared("营业收入增加 1.00亿元。", "1.00亿元 | derived | 763154445.01 - 663154445.01 | doc-1")
    )
    assert result.valid, result.issues
