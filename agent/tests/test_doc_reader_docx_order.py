"""Physical Word reports retain the association of headings and table values."""

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json

import pytest

from src.tools.doc_reader_tool import DocReaderTool

docx = pytest.importorskip("docx")


@pytest.mark.parametrize(
    "nodes",
    [
        [
            ("p", "FY2023 revenue"),
            ("t", "$42m"),
            ("p", "FY2024 revenue"),
            ("t", "$84m"),
        ],
        [("t", "Opening balance"), ("p", "Closing summary")],
        [("p", "Before"), ("t", "Between"), ("p", "After")],
        [("p", "First\tparagraph"), ("p", "Second\nparagraph"), ("p", "")],
        [("t", "First\ncell"), ("t", "Second cell")],
        [],
    ],
    ids=[
        "heading-values",
        "table-first",
        "table-between",
        "paragraph-only",
        "table-only",
        "empty",
    ],
)
def test_shipping_reader_keeps_document_body_order(tmp_path, monkeypatch, nodes):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / "report.docx"
    document = docx.Document()
    expected = []
    paragraphs = tables = 0
    for kind, text in nodes:
        if kind == "p":
            paragraphs += 1
            document.add_paragraph(text)
            if text.strip():
                expected.append(text)
        else:
            tables += 1
            document.add_table(rows=1, cols=1).cell(0, 0).text = text
            expected.extend(
                [f"\n--- Table {tables} ---", text.strip().replace("\n", " ")]
            )
    document.save(path)
    # Direct physical XML order is independent of the extraction algorithm.
    reopened = docx.Document(path)
    assert [
        child.tag.rsplit("}", 1)[-1]
        for child in reopened.element.body
        if child.tag.rsplit("}", 1)[-1] in {"p", "tbl"}
    ] == ["p" if kind == "p" else "tbl" for kind, _ in nodes]
    result = json.loads(DocReaderTool(roots=FileRoots.from_config(get_env_config().api)).execute(file_path=str(path)))
    assert result["status"] == "ok", result
    assert result["text"] == "\n".join(expected)
    assert result["paragraphs"] == paragraphs and result["tables"] == tables
    assert result["char_count"] == len(result["text"])
    assert result["truncated"] is False
