"""Regression: when OCR succeeds on some pages but silently fails on others
(no usable text, no native fallback), quality_flag must report "degraded",
not "good" — "good" gives the caller no signal that a page's content never
made it into the returned text at all.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.config.accessor import reset_env_config
from src.tools import doc_reader_tool

pdfium = pytest.importorskip("pypdfium2")
canvas = pytest.importorskip("reportlab.pdfgen.canvas")


@pytest.fixture(autouse=True)
def fake_ocr_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(doc_reader_tool, "_cached_ocr_checked", True)
    monkeypatch.setattr(doc_reader_tool, "_cached_ocr_engine", SimpleNamespace(name="fake-ocr"))
    reset_env_config()
    yield
    reset_env_config()


def _blank_pdf(tmp_path, n_pages: int):
    path = tmp_path / "scanned.pdf"
    writer = canvas.Canvas(str(path))
    for _ in range(n_pages):
        writer.showPage()
    writer.save()
    return path


def test_one_page_ocr_success_one_page_ocr_failure_reports_degraded(tmp_path, monkeypatch):
    path = _blank_pdf(tmp_path, 2)
    calls = {"n": 0}

    def fake_ocr(img):
        calls["n"] += 1
        return "Page one OCR text" if calls["n"] == 1 else ""

    monkeypatch.setattr(doc_reader_tool, "_ocr_image_array", fake_ocr)

    result = json.loads(
        doc_reader_tool.DocReaderTool().execute(file_path=str(path), min_text_per_page=5000)
    )

    assert result["status"] == "ok"
    assert result["pages_read"] == 2
    assert result["ocr_pages"] == 1
    assert result["skipped_pages"] == 0
    # Page 2's content never made it into the output -- quality_flag must
    # say so instead of reporting "good".
    assert result["ocr_quality"]["quality_flag"] == "degraded"


def test_all_pages_ocr_success_still_reports_good(tmp_path, monkeypatch):
    path = _blank_pdf(tmp_path, 2)
    monkeypatch.setattr(doc_reader_tool, "_ocr_image_array", lambda img: "Recognized text")

    result = json.loads(
        doc_reader_tool.DocReaderTool().execute(file_path=str(path), min_text_per_page=5000)
    )

    assert result["status"] == "ok"
    assert result["ocr_pages"] == 2
    assert result["ocr_quality"]["quality_flag"] == "good"
