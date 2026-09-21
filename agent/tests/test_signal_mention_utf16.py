"""Signal mention start/length are UTF-16 code-unit offsets and must be
translated to Python (code-point) indices before slicing message text."""

from __future__ import annotations

from src.channels.signal import SignalChannel, _utf16_offset_to_index


def test_utf16_offset_to_index_accounts_for_supplementary_plane_chars() -> None:
    # U+1F600 (an emoji) is 1 Python index but 2 UTF-16 code units.
    text = "\U0001f600￼ hello"
    assert _utf16_offset_to_index(text, 0) == 0
    assert _utf16_offset_to_index(text, 2) == 1
    assert _utf16_offset_to_index(text, 3) == 2


def _channel_for(bot_number: str) -> SignalChannel:
    channel = object.__new__(SignalChannel)
    channel._account_id_aliases = set(SignalChannel._normalize_signal_id(bot_number))
    return channel


def test_strip_bot_mention_after_emoji_removes_placeholder_not_adjacent_text() -> None:
    channel = _channel_for("+15551234567")
    text = "\U0001f600￼ hello"
    mentions = [{"start": 2, "length": 1, "number": "+15551234567"}]

    result = channel._strip_bot_mention(text, mentions)

    assert result == "\U0001f600 hello"
