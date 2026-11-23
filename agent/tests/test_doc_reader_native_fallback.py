"""Accepted mixed PDFs retain text while OCR-only selections stay refused."""

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json

import pytest

from src.config.accessor import reset_env_config
from src.tools import doc_reader_tool

pdfium = pytest.importorskip("pypdfium2")
canvas = pytest.importorskip("reportlab.pdfgen.canvas")


@pytest.fixture(autouse=True)
def disable_ocr(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "none")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(doc_reader_tool, "_cached_ocr_checked", False)
    monkeypatch.setattr(doc_reader_tool, "_cached_ocr_engine", None)
    reset_env_config()
    yield
    reset_env_config()


def read_pdf(tmp_path, texts, **kwargs):
    path = tmp_path / "report.pdf"
    writer = canvas.Canvas(str(path))
    for text in texts:
        if text:
            writer.drawString(50, 750, text)
        writer.showPage()
    writer.save()
    # Independent native extractor verifies these are real text pages, rather
    # than OCR mocks or fixtures that accidentally contain only raster images.
    document = pdfium.PdfDocument(str(path))
    try:
        assert [
            document[i].get_textpage().get_text_range().strip()
            for i in range(len(document))
        ] == texts
    finally:
        document.close()
    return json.loads(
        doc_reader_tool.DocReaderTool(roots=FileRoots.from_config(get_env_config().api)).execute(file_path=str(path), **kwargs)
    )


LONG = "A native summary longer than fifty characters is ordinarily readable."


@pytest.mark.parametrize(
    "texts,pages,expected,skipped",
    [
        (["Revenue: $42m", LONG], "", ["Revenue: $42m", LONG], 0),
        ([LONG, "Revenue: $42m", ""], "", [LONG, "Revenue: $42m"], 1),
        (["Unselected note", "Revenue: $42m", LONG], "2-3", ["Revenue: $42m", LONG], 0),
    ],
)
def test_accepted_mixed_pdf_retains_short_native_text(
    tmp_path, texts, pages, expected, skipped
):
    result = read_pdf(tmp_path, texts, pages=pages)
    assert result["status"] == "ok", result
    positions = [result["text"].index(text) for text in expected]
    assert positions == sorted(positions)
    assert result["skipped_pages"] == skipped
    assert result["ocr_pages"] == 0 and result["ocr_engine"] is None
    assert result["ocr_quality"]["quality_flag"] == "no_ocr_engine"
    if pages:
        assert "Unselected note" not in result["text"]
        assert result["pages_read"] == 2


@pytest.mark.parametrize(
    "texts,pages,threshold",
    [
        (["Revenue: $42m"], "", 50),
        (["Revenue: $42m", "Another note"], "", 50),
        (["Revenue: $42m", LONG], "1", 50),
        ([LONG], "", 200),
    ],
)
def test_below_threshold_only_selection_keeps_ocr_refusal(
    tmp_path, texts, pages, threshold
):
    result = read_pdf(tmp_path, texts, pages=pages, min_text_per_page=threshold)
    assert result["status"] == "error"
    assert "OCR" in result["error"]


def test_long_native_page_keeps_no_ocr_needed_control(tmp_path):
    result = read_pdf(tmp_path, [LONG])
    assert result["status"] == "ok" and LONG in result["text"]
    assert result["skipped_pages"] == 0
    assert result["ocr_quality"]["quality_flag"] == "no_ocr_needed"


def test_explicit_lower_threshold_keeps_existing_opt_out(tmp_path):
    result = read_pdf(tmp_path, ["Revenue: $42m"], min_text_per_page=10)
    assert result["status"] == "ok" and "Revenue: $42m" in result["text"]
    assert result["ocr_quality"]["quality_flag"] == "no_ocr_needed"


def test_blank_pdf_still_requires_ocr(tmp_path):
    result = read_pdf(tmp_path, [""])
    assert result["status"] == "error"
    assert "no extractable text" in result["error"]
