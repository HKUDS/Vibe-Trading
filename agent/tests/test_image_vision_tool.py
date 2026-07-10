"""Tests for image_vision_tool: path safety, input validation, LLM plumbing.

The LLM call is mocked; the only real I/O is a tiny PNG written to tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.image_vision_tool import AnalyzeImageTool

# 1x1 transparent PNG
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


@pytest.fixture()
def tool() -> AnalyzeImageTool:
    return AnalyzeImageTool()


@pytest.fixture()
def png_in_allowed_root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    p = tmp_path / "chart.png"
    p.write_bytes(_PNG_BYTES)
    return p


def test_rejects_path_outside_allowed_roots(tool):
    result = json.loads(tool.execute(path="/etc/passwd"))
    assert result["ok"] is False


def test_rejects_missing_and_unsupported_files(tool, png_in_allowed_root, tmp_path):
    missing = json.loads(tool.execute(path=str(tmp_path / "nope.png")))
    assert missing["ok"] is False and "not found" in missing["error"]

    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    unsupported = json.loads(tool.execute(path=str(txt)))
    assert unsupported["ok"] is False and "unsupported" in unsupported["error"]


def test_happy_path_sends_data_url_and_returns_answer(tool, png_in_allowed_root):
    response = MagicMock()
    response.content = "A tiny transparent pixel."

    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.return_value = response
        result = json.loads(
            tool.execute(path=str(png_in_allowed_root), question="What is this?")
        )

    assert result["ok"] is True
    assert result["data"]["answer"] == "A tiny transparent pixel."
    messages = chat_cls.return_value.chat.call_args.args[0]
    content = messages[0]["content"]
    assert content[0] == {"type": "text", "text": "What is this?"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_empty_model_answer_is_an_error(tool, png_in_allowed_root):
    result = None
    response = MagicMock()
    response.content = ""
    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.return_value = response
        result = json.loads(tool.execute(path=str(png_in_allowed_root)))
    assert result["ok"] is False
