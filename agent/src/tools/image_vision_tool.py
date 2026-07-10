"""Vision analysis for local images via the configured multimodal LLM.

The document reader only OCRs images, which fails on charts, candlestick
screenshots and photos. This tool sends the image itself to the configured
chat model (providers that support multimodal input, e.g. the OpenAI Codex
adapter's ``input_image`` path) and returns the model's answer, so IM-channel
users can send a chart screenshot and ask about it.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import allowed_file_roots, resolve_safe_path

logger = logging.getLogger(__name__)

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_DEFAULT_QUESTION = (
    "Describe this image in detail. If it is a financial chart or screenshot, "
    "read out the instrument, timeframe, key price levels, indicators and the "
    "overall trend."
)
_VISION_TIMEOUT_S = 120


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


class AnalyzeImageTool(BaseTool):
    """Answer questions about a local image using the multimodal LLM."""

    name = "analyze_image"
    description = (
        "Look at a local image with the multimodal LLM and answer a question "
        "about it. Use this for charts, candlestick/K-line screenshots, "
        "account or app screenshots and photos - anything where reading the "
        "picture matters. (read_document only OCRs text and fails on charts.) "
        "Supported: jpg/png/gif/bmp/webp under the allowed file roots. "
        'Example: {"path": "/root/.vibe-trading/weixin/abc.jpg", '
        '"question": "解读这张K线图的走势"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the image file (must be inside the allowed file roots).",
            },
            "question": {
                "type": "string",
                "description": "What to ask about the image (default: describe it in detail, reading chart levels if applicable).",
            },
        },
        "required": ["path"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Validate the path, send the image to the LLM, return its answer.

        Args:
            **kwargs: ``path`` (str, required) and ``question`` (str, optional)
                as documented in :attr:`parameters`.

        Returns:
            ``{"ok": true, "data": {"path": ..., "question": ..., "answer": ...}}``
            on success, or ``{"ok": false, "error": ...}`` on invalid input,
            unreadable file or provider failure.
        """
        raw_path = kwargs.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return _error("path is required")

        question = kwargs.get("question") or _DEFAULT_QUESTION
        if not isinstance(question, str):
            return _error("question must be a string")

        try:
            path = resolve_safe_path(raw_path.strip(), None, allowed_file_roots(), purpose="file")
        except ValueError as exc:
            return _error(str(exc))
        if not path.is_file():
            return _error(f"file not found: {path}")

        mime = _MIME_BY_EXT.get(path.suffix.lower())
        if not mime:
            return _error(f"unsupported image type {path.suffix!r}; supported: {sorted(_MIME_BY_EXT)}")

        data = path.read_bytes()
        if len(data) > _MAX_IMAGE_BYTES:
            return _error(f"image too large ({len(data)} bytes > {_MAX_IMAGE_BYTES})")

        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]

        try:
            from src.providers.chat import ChatLLM

            response = ChatLLM().chat(messages, timeout=_VISION_TIMEOUT_S)
            answer = (response.content or "").strip()
        except Exception as exc:  # noqa: BLE001 - provider errors go back to the agent
            logger.warning("analyze_image failed for %s: %s", path, exc)
            return _error(f"vision call failed: {type(exc).__name__}: {exc}")

        if not answer:
            return _error("the model returned an empty answer (provider may not support image input)")

        return json.dumps(
            {"ok": True, "data": {"path": str(path), "question": question, "answer": answer}},
            ensure_ascii=False,
        )
