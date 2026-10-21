"""Regression: a tool hint delegated to send_delta must land on the same
streaming card the caller just confirmed is active, not an orphaned one.
"""

from __future__ import annotations

import asyncio

from src.channels.bus.events import OutboundMessage
from src.channels.feishu import FeishuChannel, _FeishuStreamBuf


def _make_channel() -> FeishuChannel:
    channel = FeishuChannel({}, bus=None)
    channel._client = object()
    channel._create_streaming_card_sync = lambda *args, **kwargs: "card_new"
    channel._stream_update_text_with_reopen_sync = lambda card_id, text, seq: (True, seq)
    return channel


class TestToolHintStreamKeyContinuity:
    def test_tool_hint_appends_to_the_active_card_instead_of_a_new_one(self) -> None:
        channel = _make_channel()
        chat_id = "oc_testchat"
        message_id = "om_original_msg"
        stream_key = FeishuChannel._stream_key(chat_id, {"message_id": message_id})
        channel._stream_bufs[stream_key] = _FeishuStreamBuf(
            text="Hello so far", card_id="card_main", sequence=3
        )

        asyncio.run(
            channel.send(
                OutboundMessage(
                    channel="feishu", chat_id=chat_id, content="Using calculator...",
                    metadata={"_tool_hint": True, "_progress": True, "message_id": message_id},
                )
            )
        )

        assert list(channel._stream_bufs.keys()) == [stream_key]
        buf = channel._stream_bufs[stream_key]
        assert buf.card_id == "card_main"
        assert "Hello so far" in buf.text
        assert "Using calculator..." in buf.text

    def test_finalizing_the_stream_leaves_no_stray_buffer(self) -> None:
        channel = _make_channel()
        chat_id = "oc_testchat"
        message_id = "om_original_msg"
        stream_key = FeishuChannel._stream_key(chat_id, {"message_id": message_id})
        channel._stream_bufs[stream_key] = _FeishuStreamBuf(
            text="Hello so far", card_id="card_main", sequence=3
        )
        channel._stream_update_text_with_reopen_sync = lambda card_id, text, seq: (True, seq)
        channel._close_streaming_mode_sync = lambda card_id, seq: True

        async def run() -> None:
            await channel.send(
                OutboundMessage(
                    channel="feishu", chat_id=chat_id, content="Using calculator...",
                    metadata={"_tool_hint": True, "_progress": True, "message_id": message_id},
                )
            )
            await channel.send_delta(
                chat_id, "", {"_stream_end": True, "message_id": message_id}
            )

        asyncio.run(run())

        assert channel._stream_bufs == {}
