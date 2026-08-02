"""RapidOCR engine — local, ONNX Runtime based, no API key needed."""

from __future__ import annotations

import numpy as np


class RapidOcrEngine:
    """Local OCR engine using RapidOCR (PaddleOCR-derived, ONNX Runtime)."""

    name = "rapid"
    is_cloud = False
    install_hint = "pip install rapidocr_onnxruntime"

    def __init__(self) -> None:
        # Lazy init: RapidOCR() loaded inside is_available() / recognize().
        # _select_first_local() probes every registered engine, so __init__
        # must stay cheap (attribute assignment only).
        self._engine = None

    def is_available(self) -> bool:
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            if self._engine is None:
                self._engine = RapidOCR()
            return True
        except ImportError:
            return False

    def recognize(self, image: np.ndarray) -> str:
        if not self.is_available():
            raise RuntimeError("RapidOCR not installed: pip install rapidocr_onnxruntime")
        result, _ = self._engine(image)
        if not result:
            return ""
        return "\n".join(item[1] for item in result)


# Self-register to built-in engine table
from src.tools.ocr.engine import register_builtin  # noqa: E402

register_builtin("rapid", RapidOcrEngine)
