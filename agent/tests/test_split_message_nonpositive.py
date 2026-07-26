"""Regression: split_message must not hang on non-positive max_len."""

from __future__ import annotations

from src.channels.utils import split_message


def test_split_message_nonpositive_max_len_returns_unsplit() -> None:
    content = "hello world"
    assert split_message(content, max_len=0) == [content]
    assert split_message(content, max_len=-1) == [content]


def test_split_message_normal_path() -> None:
    chunks = split_message("aaa\nbbb\nccc", max_len=5)
    assert chunks
    assert all(len(c) <= 5 for c in chunks)


def test_split_message_preserves_indent_after_newline_cut() -> None:
    # Long first line forces a cut; the following indented code line must keep
    # its leading spaces (Discord/Slack/Telegram all share this helper).
    text = ("word " * 8) + "\n    def foo():\n        return 1\n" + ("tail " * 8)
    chunks = split_message(text, max_len=40)
    assert any("    def foo():" in c for c in chunks)
    assert any("        return 1" in c for c in chunks)
    assert all(len(c) <= 40 for c in chunks)
