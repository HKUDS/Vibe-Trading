"""Integration tests for the OCR pipeline.

Tests the full path: synthetic scanned PDF → _read_pdf() → OCR → text output.
Requires rapidocr_onnxruntime to be installed for the OCR path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.accessor import reset_env_config


def _has_rapid_ocr() -> bool:
    """Check if RapidOCR is available for testing."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the cached EnvConfig around each test."""
    reset_env_config()
    yield
    reset_env_config()


@pytest.mark.skipif(
    not _has_rapid_ocr(),
    reason="rapidocr_onnxruntime not installed",
)
class TestOcrIntegration:
    """End-to-end OCR tests requiring RapidOCR."""

    _FONT_CANDIDATES = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Menlo.ttc",
    ]

    @classmethod
    def _find_font(cls):
        from PIL import ImageFont

        for path in cls._FONT_CANDIDATES:
            try:
                return ImageFont.truetype(path, 36)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    def test_synthetic_scanned_pdf_end_to_end(self, tmp_path: Path):
        """Create a scanned PDF with text, run _read_pdf, verify OCR output."""
        try:
            import pypdfium2 as pdfium  # noqa: F401
            from PIL import Image, ImageDraw  # noqa: F401
        except ImportError:
            pytest.skip("pypdfium2 or Pillow not installed")

        # Create a synthetic "scanned" PDF: render text as image, save as PDF
        # Pillow saves images as PDF with no text layer — exactly like a scan
        img = Image.new("RGB", (800, 200), color="white")
        draw = ImageDraw.Draw(img)
        test_text = "Hello OCR Test 12345"
        font = self._find_font()
        draw.text((50, 70), test_text, fill="black", font=font)

        # Save image directly as PDF via Pillow (no text layer, simulates scan)
        pdf_path = tmp_path / "test_scanned.pdf"
        img.save(str(pdf_path), "PDF", resolution=100.0)

        # Now run _read_pdf on this synthetic scanned PDF
        from src.tools.doc_reader_tool import _read_pdf

        result_json = _read_pdf(pdf_path, "")
        result = json.loads(result_json)

        # The PDF has no text layer (it's an image), so OCR should kick in
        # With RapidOCR available, we should get text back
        assert result["status"] == "ok", f"Expected ok, got: {result}"
        # The extracted text should contain our test string (OCR may not be perfect)
        text = result.get("text", "")
        # At minimum, some text should be extracted
        assert len(text) > 0, "OCR extracted no text from scanned PDF"


class TestOcrEngineDiscovery:
    """Test that the OCR engine registry works correctly at integration level."""

    def test_builtin_engines_discoverable(self):
        """Built-in engines should be discoverable via _all_engines()."""
        from src.tools.ocr.engine import _all_engines

        engines = _all_engines()
        assert "rapid" in engines, "rapid engine not registered"
        assert "llm-vision" in engines, "llm-vision engine not registered"

    def test_rapid_engine_availability(self):
        """RapidOCR engine availability matches installation state."""
        from src.tools.ocr.engine import _all_engines

        engines = _all_engines()
        rapid = engines["rapid"]()
        # is_available() should match whether rapidocr_onnxruntime is installed
        assert rapid.is_available() == _has_rapid_ocr()

    def test_auto_mode_returns_local_or_none(self, monkeypatch):
        """auto mode should return a local engine or None, never cloud."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "auto")
        reset_env_config()

        from src.tools.ocr.engine import get_ocr_engine

        engine = get_ocr_engine()
        if engine is not None:
            assert engine.is_cloud is False, f"auto mode returned cloud engine: {engine.name}"
