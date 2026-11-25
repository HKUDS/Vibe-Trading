"""Tests for image_vision_tool: path safety, input validation, LLM plumbing.

The LLM call is mocked; the only real I/O is a tiny PNG written to tmp_path.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config.paths import get_uploads_dir
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
    chat_cls.return_value.close.assert_called_once_with()


def test_empty_model_answer_is_an_error(tool, png_in_allowed_root):
    response = MagicMock()
    response.content = ""
    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.return_value = response
        result = json.loads(tool.execute(path=str(png_in_allowed_root)))
    assert result["ok"] is False
    chat_cls.return_value.close.assert_called_once_with()


def test_provider_failure_closes_chat_client(tool, png_in_allowed_root):
    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.side_effect = RuntimeError("provider unavailable")
        result = json.loads(tool.execute(path=str(png_in_allowed_root)))

    assert result["ok"] is False
    chat_cls.return_value.close.assert_called_once_with()


@pytest.mark.parametrize("handle", ["uploads/chart.png", "agent/uploads/chart.png", "uploads/chat/chart.png"])
@pytest.mark.parametrize("custom_home", [False, True])
@pytest.mark.parametrize("stale_copy", [False, True])
def test_browser_upload_handle_uses_runtime_root(tool, tmp_path, monkeypatch, handle, custom_home, stale_copy):
    """Browser attachment handles must not depend on the service working directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    if custom_home:
        monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "custom-runtime"))
    else:
        monkeypatch.delenv("VIBE_TRADING_HOME", raising=False)
    relative_name = handle.split("uploads/", 1)[1]
    image = get_uploads_dir() / relative_name
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(_PNG_BYTES)
    service_dir = tmp_path / "service"
    service_dir.mkdir()
    monkeypatch.chdir(service_dir)
    # A stale same-named file under cwd must not override the uploaded image.
    if stale_copy:
        stale = service_dir / handle
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"stale image")
    response = MagicMock(content="Uploaded image.")
    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.return_value = response
        result = json.loads(tool.execute(path=handle))

    assert result["ok"] is True
    assert result["data"]["path"] == str(image.resolve())
    messages = chat_cls.return_value.chat.call_args.args[0]
    assert messages[0]["content"][1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode("ascii")
    )


@pytest.mark.parametrize("escape", ["traversal", "symlink"])
def test_upload_handle_cannot_escape_allowed_roots(tool, tmp_path, monkeypatch, escape):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))
    uploads = tmp_path / "runtime" / "uploads"
    uploads.mkdir(parents=True)
    outside = tmp_path / "private.png"
    outside.write_bytes(_PNG_BYTES)
    if escape == "symlink":
        (uploads / "link.png").symlink_to(outside)
        handle = "uploads/link.png"
    else:
        handle = "uploads/../../private.png"
    with patch("src.providers.chat.ChatLLM") as chat_cls:
        result = json.loads(tool.execute(path=handle))
    assert result["ok"] is False
    chat_cls.assert_not_called()
