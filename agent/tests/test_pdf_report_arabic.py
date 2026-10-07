"""Portable Arabic report rendering through real fonts, layout, and PDF bytes."""

from __future__ import annotations

import unicodedata
import base64
import re
import zlib

import pypdfium2 as pdfium
import pytest
from reportlab.pdfbase import pdfmetrics

from src.shadow_account.pdf_fallback import _ensure_font
from src.tools import pdf_report


def _text(path):
    with pdfium.PdfDocument(path) as document:
        return "\n".join(document[index].get_textpage().get_text_range() for index in range(len(document)))


def _decoded_streams(path):
    """Read the ASCII85/Flate streams this ReportLab renderer writes."""
    streams = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", path.read_bytes(), re.S):
        try:
            streams.append(zlib.decompress(base64.a85decode(stream.strip(), adobe=True)))
        except (ValueError, zlib.error):
            continue
    return b"\n".join(streams)


def test_arabic_shapes_and_preserves_latin_numbers_and_diacritics():
    logical = "تقرير مُهِمّ: AAPL 123.45 USD و BTC-USDT 67,890.12"
    visual = pdf_report._visual_line(logical, "R")
    assert "AAPL 123.45 USD" in visual
    assert "BTC-USDT 67,890.12" in visual
    assert any(0xFE70 <= ord(char) <= 0xFEFF for char in visual)
    assert {char for char in logical if unicodedata.combining(char)} <= set(visual)
    assert visual != logical and visual != logical[::-1]


def test_every_mixed_script_glyph_has_a_real_embedded_font():
    cjk, arabic = _ensure_font(), pdf_report._arabic_font()
    assert pdfmetrics.getFont(cjk).face.charToGlyph.get(ord("ت"), 0) == 0
    visual = pdf_report._visual_line("تقرير عربي 中国股票 AAPL 123.45 ١٢٣", "R")
    runs = pdf_report._font_runs(visual, cjk, arabic)
    assert {font for font, _ in runs} == {cjk, arabic}
    for font, text in runs:
        cmap = pdfmetrics.getFont(font).face.charToGlyph
        assert all(cmap.get(ord(char), 0) > 0 for char in text)


def test_wrapping_keeps_logical_paragraph_order_and_column_width():
    from bidi.algorithm import get_display

    cjk, arabic = _ensure_font(), pdf_report._arabic_font()
    source = "البداية " + "تقرير الأسواق العربية والمخاطر " * 8 + "النهاية"
    lines, direction = pdf_report._rtl_lines(source, 140, 10, cjk, arabic)
    assert direction == "R" and len(lines) > 3
    restored = [unicodedata.normalize("NFKC", get_display(visual, base_dir="R")) for _, visual in lines]
    assert " ".join(restored) == source
    assert restored[0].startswith("البداية")
    assert restored[-1].endswith("النهاية")
    for _, line in lines:
        width = sum(pdfmetrics.stringWidth(text, font, 10) for font, text in pdf_report._font_runs(line, cjk, arabic))
        assert width <= 140


def test_real_mixed_arabic_markdown_table_pdf(tmp_path):
    target = tmp_path / "report.pdf"
    pdf_report.render_markdown_pdf(
        "# تقرير الأسواق\n\nتحليل AAPL 123.45 USD و ١٢٣\n\n"
        "| السوق | السعر | Notes |\n| --- | --- | --- |\n"
        "| الصين 中国 | 600519.SH | تقرير عربي |\n"
        "| AAPL | 123.45 USD | 中文报告 |\n\n"
        "## English / 中文\n\nA **bold** report with < & > and [source](https://example.com).\n"
        "```\nprice = 123.45\n```\n",
        target,
    )
    data = target.read_bytes()
    assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/FontFile2") >= 2 and b"/ToUnicode" in data
    text = _text(target)
    for value in ["AAPL", "123.45 USD", "600519", "SH", "中国", "中文报告", "English", "price = 123.45"]:
        assert value in text
    assert "\x00" not in text and "\ufffd" not in text
    # PDFium applies its own bidi heuristic across an entire table row; it
    # may reorder 600519.SH into SH600519. ActualText is checked independently.
    decoded = _decoded_streams(target)
    canonical = ("\ufeff" + "تحليل AAPL 123.45 USD و ١٢٣").encode("utf-16-be").hex().encode()
    assert b"/ActualText <" + canonical + b">" in decoded
    normalized = unicodedata.normalize("NFKC", text)
    assert any(unicodedata.bidirectional(char) == "AL" for char in normalized)
    assert not list(tmp_path.glob(".report-*.pdf"))


def test_arabic_paragraph_and_tall_table_cell_paginate(tmp_path):
    target = tmp_path / "long.pdf"
    text = "البداية " + "تقرير الأسواق العربية AAPL 123.45 والمخاطر. " * 160 + " النهاية"
    pdf_report.render_markdown_pdf(
        "# تقرير طويل\n\n" + text + "\n\n| الوصف | القيمة |\n| --- | --- |\n| " + text + " | 123.45 |\n",
        target,
    )
    with pdfium.PdfDocument(target) as document:
        assert len(document) >= 3
    # PDFium 156 reverses LTR runs when extracting a long Arabic paragraph
    # (AAPL 123.45 becomes LPAA 54.321). Check the PDF's logical and drawn
    # content independently of that extractor's paragraph bidi heuristic.
    decoded = _decoded_streams(target)
    logical = [
        bytes.fromhex(value.decode()).decode("utf-16-be").lstrip("\ufeff")
        for value in re.findall(rb"/ActualText <([0-9a-f]+)>", decoded)
    ]
    body = " ".join(part for part in logical if part not in {"تقرير طويل", "الوصف", "القيمة"})
    expected = " ".join(text.split())
    assert body == expected + " " + expected
    # ActualText alone could conceal a missing drawing. Both the paragraph
    # and tall cell must paint every Latin run, plus the standalone value.
    drawn = b"\n".join(re.findall(rb"\((.*?)\)\s*Tj", decoded, re.S))
    assert drawn.count(b"AAPL") == 320
    assert drawn.count(b"123.45") == 321


@pytest.mark.parametrize("failure", ["missing_glyph", "replace"])
def test_arabic_render_failure_retains_old_target_and_cleans_temporary(tmp_path, monkeypatch, failure):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"previous PDF")
    content = "تقرير عربي"
    if failure == "missing_glyph":
        content += " \U0001fae0"  # Absent from both packaged report fonts.
    else:
        def denied(*args):
            raise OSError("replace denied")
        from tests.module_os_helpers import patch_module_os

        patch_module_os(monkeypatch, pdf_report, replace=denied)
    with pytest.raises((ValueError, OSError)):
        pdf_report.render_markdown_pdf(content, target)
    assert target.read_bytes() == b"previous PDF"
    assert not list(tmp_path.glob(".report-*.pdf"))



def test_tall_mixed_table_keeps_every_glyph_on_its_page(tmp_path):
    target = tmp_path / "mixed-pages.pdf"
    content = ("هذا تقرير للأسواق مع AAPL 123.45 USD و 中文报告 والعائد +5.25%. " * 90)
    content += "\n\n| وصف | قيمة |\n| --- | --- |\n| "
    content += "تقرير طويل 中文 123.45 USD. " * 160
    content += " | 123.45 |\n"
    pdf_report.render_markdown_pdf(content, target)
    with pdfium.PdfDocument(target) as document:
        assert len(document) >= 3
        for page_number, page in enumerate(document):
            width, height = page.get_size()
            text = page.get_textpage()
            for index in range(text.count_chars()):
                left, bottom, right, top = text.get_charbox(index)
                assert left >= -1 and bottom >= -1 and right <= width + 1 and top <= height + 1, (
                    page_number, index, (left, bottom, right, top), (width, height)
                )
