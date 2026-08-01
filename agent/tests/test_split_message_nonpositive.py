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


def test_signal_partition_styles_keeps_indent_chunk_aligned() -> None:
    # Signal rebases UTF-16 styles onto split_message chunks; must not skip
    # indent spaces the way the old blanket lstrip mirror did.
    from src.channels.signal import _partition_styles, _utf16_len

    text = ("word " * 8) + "\n    def foo():\n        return 1\n" + ("tail " * 8)
    chunks = split_message(text, max_len=40)
    idx = text.index("def")
    styles = [f"{_utf16_len(text[:idx])}:{_utf16_len('def')}:BOLD"]
    parts = _partition_styles(text, chunks, styles)
    assert any("BOLD" in entry for group in parts for entry in group)
def test_signal_partition_styles_handles_space_separator_with_indented_next_chunk() -> None:
    # When split_message cuts at a space separator and the next chunk is also
    # indented with spaces, _partition_styles must still advance the cursor
    # over the dropped separator space.
    from src.channels.signal import _partition_styles, _utf16_len

    # "12345 78" with max_len=5 cuts into "12345" and "78", dropping the space.
    text = "12345   abc"
    chunks = split_message(text, max_len=5)
    # text is ["12345", "  abc"] — separator space at index 5 was dropped
    idx = text.index("abc")
    styles = [f"{_utf16_len(text[:idx])}:{_utf16_len('abc')}:BOLD"]
    parts = _partition_styles(text, chunks, styles)
    # "abc" is at offset 2 in the second chunk "  abc"
    assert parts[1] == ["2:3:BOLD"]
