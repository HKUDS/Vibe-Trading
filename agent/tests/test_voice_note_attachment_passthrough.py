"""Regression: voice/audio messages must reach the agent as attachments.

Telegram, Feishu, Matrix and Weixin used to await ``self.transcribe_audio()``,
a method defined nowhere, so a voice note was dropped (or mislabelled as a
failed download) instead of being forwarded.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


from src.channels.feishu import FeishuChannel  # noqa: E402
from src.channels.weixin import ITEM_TEXT, ITEM_VOICE, WeixinChannel  # noqa: E402


async def _noop(*args, **kwargs) -> None:
    return None


def _capture_handle_message(channel) -> list[dict]:
    handled: list[dict] = []

    async def fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = fake_handle_message
    return handled


class TestTelegramVoiceNote:
    @pytest.mark.parametrize("attribute", ["voice", "audio"])
    def test_voice_note_is_forwarded_as_an_attachment(
        self, monkeypatch, tmp_path, attribute: str
    ) -> None:
        pytest.importorskip("telegram")
        import src.channels.telegram as telegram_mod
        from src.channels.telegram import TelegramChannel

        class _File:
            async def download_to_drive(self, path) -> None:
                pass

        class _Bot:
            async def get_file(self, file_id):
                assert file_id == "f1"
                return _File()

        channel = TelegramChannel({"token": "x"}, bus=None)
        channel._app = SimpleNamespace(bot=_Bot())
        monkeypatch.setattr(telegram_mod, "get_media_dir", lambda name: tmp_path)

        message = SimpleNamespace(photo=None, voice=None, audio=None)
        setattr(
            message,
            attribute,
            SimpleNamespace(
                file_id="f1",
                file_unique_id="v1",
                mime_type="audio/ogg",
                file_name=None,
            ),
        )

        media, parts = asyncio.run(
            channel._download_message_media(message, add_failure_content=True)
        )

        path = str(tmp_path / "v1.ogg")
        assert media == [path]
        assert parts == [f"[{attribute}: {path}]"]


class TestFeishuVoiceNote:
    def test_audio_message_is_forwarded_as_an_attachment(self, tmp_path) -> None:
        path = str(tmp_path / "feishu_voice.ogg")
        channel = FeishuChannel({}, bus=None)
        channel.is_allowed = lambda sender_id: True
        channel._add_reaction = _noop
        handled = _capture_handle_message(channel)

        async def fake_download_and_save_media(msg_type, content_json, message_id=None):
            return path, f"[{msg_type}: {path}]"

        channel._download_and_save_media = fake_download_and_save_media

        message = SimpleNamespace(
            message_id="om_1",
            chat_id="oc_1",
            chat_type="p2p",
            message_type="audio",
            content=json.dumps({"file_key": "fk1"}),
            mentions=None,
            parent_id=None,
            root_id=None,
            thread_id=None,
        )
        data = SimpleNamespace(
            event=SimpleNamespace(
                message=message,
                sender=SimpleNamespace(
                    sender_type="user",
                    sender_id=SimpleNamespace(open_id="ou_1"),
                ),
            )
        )

        asyncio.run(channel._on_message(data))

        assert [(h["media"], h["content"]) for h in handled] == [
            ([path], f"[audio: {path}]")
        ]


class TestMatrixVoiceNote:
    def test_audio_attachment_is_forwarded(self) -> None:
        pytest.importorskip("nio")
        pytest.importorskip("aiohttp")
        from src.channels.matrix import MatrixChannel

        path = "/tmp/matrix_voice.ogg"
        channel = MatrixChannel({}, bus=None)
        channel._is_pre_startup_event = lambda event: False
        channel._should_process_message = lambda room, event: True
        channel._is_direct_room = lambda room: True
        channel._start_typing_keepalive = _noop
        channel._base_metadata = lambda room, event: {}
        handled = _capture_handle_message(channel)

        async def fake_fetch_media_attachment(room, event):
            return (
                {
                    "type": "audio",
                    "path": path,
                    "filename": "voice.ogg",
                    "mime": "audio/ogg",
                },
                f"[attachment: {path}]",
            )

        channel._fetch_media_attachment = fake_fetch_media_attachment

        room = SimpleNamespace(room_id="!room:example.org")
        event = SimpleNamespace(sender="@alice:example.org", body="", event_id="$evt")

        asyncio.run(channel._on_media_message(room, event))

        assert [(h["media"], h["content"]) for h in handled] == [
            ([path], f"[attachment: {path}]")
        ]


class TestWeixinVoiceNote:
    def test_top_level_voice_item_is_forwarded(self) -> None:
        path = "/tmp/weixin_voice.silk"
        channel = WeixinChannel({}, bus=None)
        channel.is_allowed = lambda sender_id: True
        channel._start_typing = _noop
        handled = _capture_handle_message(channel)

        async def fake_download_media_item(typed_item, media_type, filename=None):
            return path

        channel._download_media_item = fake_download_media_item

        asyncio.run(
            channel._process_message(
                {
                    "message_type": 1,
                    "message_id": "m1",
                    "from_user_id": "u1",
                    "item_list": [
                        {
                            "type": ITEM_VOICE,
                            "voice_item": {
                                "text": "",
                                "media": {"encrypt_query_param": "q1"},
                            },
                        }
                    ],
                }
            )
        )

        assert [(h["media"], h["content"]) for h in handled] == [
            ([path], f"[voice]\n[Audio: source: {path}]")
        ]

    def test_quoted_voice_message_is_forwarded(self) -> None:
        path = "/tmp/weixin_quoted_voice.silk"
        channel = WeixinChannel({}, bus=None)
        channel.is_allowed = lambda sender_id: True
        channel._start_typing = _noop
        handled = _capture_handle_message(channel)

        async def fake_download_media_item(typed_item, media_type, filename=None):
            return path

        channel._download_media_item = fake_download_media_item

        asyncio.run(
            channel._process_message(
                {
                    "message_type": 1,
                    "message_id": "m2",
                    "from_user_id": "u2",
                    "item_list": [
                        {
                            "type": ITEM_TEXT,
                            "text_item": {"text": "what did they say?"},
                            "ref_msg": {
                                "message_item": {
                                    "type": ITEM_VOICE,
                                    "voice_item": {
                                        "media": {"encrypt_query_param": "q2"}
                                    },
                                }
                            },
                        }
                    ],
                }
            )
        )

        assert [(h["media"], h["content"]) for h in handled] == [
            ([path], f"what did they say?\n[voice]\n[Audio: source: {path}]")
        ]
