"""Raw integers can be quoted without becoming fungible numeric evidence."""

import json

import pytest

from tests.test_grounding_document_figures import (
    _declared,
    _ledger_with_upload,
    _read_document,
)


@pytest.mark.parametrize(
    "label,value",
    [
        ("股东总数", "76175"),
        ("员工总数", "3400"),
        ("Shareholders", "76175"),
        ("库存变动", "-76175"),
    ],
)
def test_literal_integer_quote_preserves_label_and_number(tmp_path, label, value):
    ledger, document = _ledger_with_upload(tmp_path)
    source = f"{label} {value}"
    _read_document(ledger, document, "doc-1", source)
    result = ledger.validate_final_answer(
        _declared(
            f"| 项目 | 数量 |\n|---|---|\n| {label} | {int(value):,} |",
            f"{value} | observed | quote: {source} | doc-1",
        )
    )
    assert result.valid, result.issues
    assert not ledger._evidence
    assert ledger.should_buffer_output
    persisted = json.loads(
        (ledger.run_dir / "artifacts" / "grounding_evidence.json").read_text()
    )
    assert persisted["document_integer_quotes"][0]["text"] == source


@pytest.mark.parametrize(
    "source,answer,note,ref",
    [
        ("股东总数 76175", "| 股东总数 | 76,175 |", "股东总数", "doc-1"),
        (
            "股东总数 76175",
            "| 股东总数 | 76,175 |",
            "quote: 股东总数 76175",
            "read_document",
        ),
        ("股东总数 76175", "| 股东总数 | 76,175 |", "quote: 股东总数 76175", "doc-2"),
        ("证券代码 600519", "| 收入 | 600,519 |", "quote: 证券代码 600519", "doc-1"),
        ("证券代码 600519", "| 收入 | 600,519 |", "quote: 收入 600519", "doc-1"),
        ("股东总数 76175", "| 股东总数 | 76,176 |", "quote: 股东总数 76175", "doc-1"),
        ("股东总数 76175", "| 股东总数 | 76,175元 |", "quote: 股东总数 76175", "doc-1"),
        ("股东总数 76175", "| 股东总数 | 76,175% |", "quote: 股东总数 76175", "doc-1"),
        ("股东总数 76175", "| 股东总数 | 76.175千 |", "quote: 股东总数 76175", "doc-1"),
        ("约 1万 户", "| 户 | 10,000 |", "quote: 约 1万 户", "doc-1"),
        ("2M shares", "| shares | 2,000,000 |", "quote: 2M shares", "doc-1"),
    ],
)
def test_integer_quote_cannot_change_identity_or_units(
    tmp_path, source, answer, note, ref
):
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", source)
    from src.agent.grounding.figures import parse_figures_block, scan_figures

    figure = scan_figures(answer, parse_figures_block(answer))[0]
    value = figure.text
    result = ledger.validate_final_answer(
        _declared(
            "| 项目 | 数量 |\n|---|---|\n" + answer,
            f"{value} | observed | {note} | {ref}",
        )
    )
    assert not result.valid


def test_integer_quotes_never_supply_derived_operands(tmp_path):
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(ledger, document, "doc-1", "股东总数 76175\n新增股东 10.0")
    result = ledger.validate_final_answer(
        _declared(
            "调整后 76,185。",
            "76185 | derived | 76175 + 10.0 | doc-1",
        )
    )
    assert not result.valid


@pytest.mark.parametrize("kind", ["generated", "run_artifact", "failed_read"])
def test_integer_quote_keeps_document_provenance_boundary(tmp_path, kind):
    ledger, document = _ledger_with_upload(tmp_path)
    if kind == "generated":
        ledger._model_written.add(str(document.resolve()))
    elif kind == "run_artifact":
        document = ledger.run_dir / "draft.txt"
    if kind == "failed_read":
        from tests.test_grounding_document_figures import _document_envelope

        ledger.ingest_tool_result(
            tool_name="read_document",
            arguments={"file_path": str(document)},
            result=_document_envelope(document, "股东总数 76175"),
            call_id="doc-1",
            success=False,
        )
    else:
        _read_document(ledger, document, "doc-1", "股东总数 76175")
    assert not ledger._document_integer_quotes
    result = ledger.validate_final_answer(
        _declared(
            "| 项目 | 数量 |\n|---|---|\n| 股东总数 | 76,175 |",
            "76175 | observed | quote: 股东总数 76175 | doc-1",
        )
    )
    assert not result.valid


def test_integer_quotes_are_bounded_and_exclude_structure(tmp_path):
    ledger, document = _ledger_with_upload(tmp_path)
    _read_document(
        ledger,
        document,
        "doc-1",
        "日期 20261111\n年份 2026\n股票 600519.SH\n"
        + "\n".join(f"计数 {10000 + i}" for i in range(500)),
    )
    assert len(ledger._document_integer_quotes) == 400
    assert {q.digits for q in ledger._document_integer_quotes}.isdisjoint(
        {"20261111", "2026", "600519"}
    )
    _read_document(ledger, document, "doc-2", "计数 76175")
    assert len(ledger._document_integer_quotes) == 400


def test_real_document_reader_to_literal_quote(tmp_path, monkeypatch):
    from src.tools.doc_reader_tool import read_document

    ledger, document = _ledger_with_upload(tmp_path)
    document = document.with_suffix(".txt")
    document.write_text("股东总数 76175", encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(document.parent))
    envelope = read_document(str(document))
    assert json.loads(envelope)["status"] == "ok"
    ledger.ingest_tool_result(
        tool_name="read_document",
        arguments={"file_path": str(document)},
        result=envelope,
        call_id="doc-1",
        success=True,
    )
    result = ledger.validate_final_answer(
        _declared(
            "| 项目 | 数量 |\n|---|---|\n| 股东总数 | 76,175 |",
            "76175 | observed | quote: 股东总数 76175 | doc-1",
        )
    )
    assert result.valid, result.issues
