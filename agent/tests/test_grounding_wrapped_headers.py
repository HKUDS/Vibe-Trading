"""Wrapped PDF headers must preserve amount columns and reject ambiguous layouts."""

import pytest

from tests.test_grounding_document_figures import (
    _declared,
    _ledger_with_upload,
    _read_document,
)


@pytest.mark.parametrize(
    "source",
    [
        "项目 本报告期 本报告期比上年 年初至报告期末\n同期增减变动\n幅度(%)\n"
        "营业收入 7,747,346,892 17.10 20,817,866,218",
        "项目 本报告期\n同比\n(%)\n营业收入 7,747,346,892 17.10\n"
        "净利润 1,092,847,713 20,817,866,218",
    ],
)
def test_wrapped_header_does_not_turn_grouped_amount_into_percent(tmp_path, source):
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", source)
    result = ledger.validate_final_answer(
        _declared(
            "累计收入 20,817,866,218。",
            "20,817,866,218 | observed | 累计收入 | doc-1",
        )
    )
    assert result.valid, result.issues
    assert not any(
        r.field == "document.ratio" for r in ledger._evidence if r.value == 20817866218
    )


@pytest.mark.parametrize(
    "source, valid",
    [
        (
            "项目 本报告期\n本报告期比\n上年同期增\n减变动幅度\n(%)\n"
            "营业收入 7,747,346,892 17.10\n净利润 1,092,847,713 4.18",
            True,
        ),
        # The amount may be decimal, so numeric magnitude cannot identify a column.
        ("项目 本期 同比 累计\n幅度(%)\n营业收入 100.50 6.21 17.10", False),
        # No surviving header width, so the marker cannot identify its column.
        ("(%)\n营业收入 100.50 17.10", False),
        ("项目 本报告期\n(%)\n\n营业收入 100.50 17.10", False),
        ("项目 本报告期\n(%)\n管理层讨论与分析如下。\n营业收入 100.50 17.10", False),
        # A later inconsistent row invalidates the inferred block, including its prefix.
        ("项目 本报告期\n(%)\n营业收入 100.50 17.10\n净利润 10.50 6.21 300", False),
    ],
)
def test_wrapped_header_requires_a_matching_contiguous_block(tmp_path, source, valid):
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", source)
    for value in ("17.10", "17.10%"):
        result = ledger.validate_final_answer(
            _declared(
                "营收同比 +17.10%。",
                f"{value} | observed | 营收同比 | doc-1",
            )
        )
        assert result.valid is valid, result.issues
