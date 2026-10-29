"""Regression: an inbound WhatsApp voice note must reach the agent as a
media attachment, not be dropped on an undefined transcription call.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.channels.whatsapp import WhatsAppChannel


def _make_voice_note_event() -> SimpleNamespace:
    audio_message = SimpleNamespace(mimetype="audio/ogg", fileName="", PTT=True, ptt=True)
    message = SimpleNamespace(
        imageMessage=None, videoMessage=None, audioMessage=audio_message,
        documentMessage=None, stickerMessage=None, conversation="", extendedTextMessage=None,
    )
    source = SimpleNamespace(
        IsFromMe=False, Chat="123@s.whatsapp.net", IsGroup=False,
        Sender="123@s.whatsapp.net", SenderAlt=None,
    )
    info = SimpleNamespace(MessageSource=source, Timestamp=0, ID="msg1")
    return SimpleNamespace(Info=info, Message=message)


class TestVoiceNoteHandling:
    def test_voice_note_reaches_the_agent_as_an_audio_attachment(self) -> None:
        channel = WhatsAppChannel({}, bus=None)
        channel.is_allowed = lambda sender_id: True

        async def fake_download_media(client, event, media):
            return "/tmp/voice_note.ogg"

        channel._download_media = fake_download_media

        handled: dict = {}

        async def fake_handle_message(**kwargs):
            handled.update(kwargs)

        channel._handle_message = fake_handle_message

        asyncio.run(
            channel._handle_neonize_message(client=None, event=_make_voice_note_event())
        )

        assert handled.get("media") == ["/tmp/voice_note.ogg"]
        assert handled.get("content") == "[audio: /tmp/voice_note.ogg]"
