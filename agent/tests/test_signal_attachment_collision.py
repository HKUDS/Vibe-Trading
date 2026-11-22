"""Regression: two Signal attachments sharing a filename (routine -- multiple
photos are all commonly named "image.jpg") must not overwrite each other on
disk. dest_path was built from the filename alone; attachment_id, the one
field signal-cli guarantees is unique per attachment, was never part of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.channels.signal import SignalChannel, SignalConfig


def _make_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SignalChannel, Path]:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)
    attachments_dir = tmp_path / "signal-cli-attachments"
    attachments_dir.mkdir()

    config = SignalConfig(enabled=True, phone_number="+15551234567", attachments_dir=str(attachments_dir))
    channel = SignalChannel(config, bus=None)
    return channel, attachments_dir


class TestAttachmentFilenameCollision:
    def test_two_attachments_sharing_a_filename_get_distinct_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        channel, attachments_dir = _make_channel(tmp_path, monkeypatch)
        (attachments_dir / "att-id-1").write_bytes(b"FIRST-PHOTO-CONTENT")
        (attachments_dir / "att-id-2").write_bytes(b"SECOND-PHOTO-CONTENT")

        content, media_paths = channel._assemble_inbound_content(
            sender_name="Alice",
            sender_number="+15559876543",
            message_text="here are two photos",
            attachments=[
                {"id": "att-id-1", "filename": "image.jpg", "contentType": "image/jpeg"},
                {"id": "att-id-2", "filename": "image.jpg", "contentType": "image/jpeg"},
            ],
            mentions=[],
            is_group_message=False,
            chat_id="+15559876543",
        )

        assert len(media_paths) == 2
        assert len(set(media_paths)) == 2
        assert Path(media_paths[0]).read_bytes() == b"FIRST-PHOTO-CONTENT"
        assert Path(media_paths[1]).read_bytes() == b"SECOND-PHOTO-CONTENT"

    @pytest.mark.parametrize("filename", ["image.jpg", "photo" * 48 + ".jpg"])
    def test_single_attachment_still_downloads_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
    ) -> None:
        channel, attachments_dir = _make_channel(tmp_path, monkeypatch)
        attachment_id = "signal-attachment-0123456789"
        (attachments_dir / attachment_id).write_bytes(b"ONLY-PHOTO")

        content, media_paths = channel._assemble_inbound_content(
            sender_name="Alice",
            sender_number="+15559876543",
            message_text="one photo",
            attachments=[{"id": attachment_id, "filename": filename, "contentType": "image/jpeg"}],
            mentions=[],
            is_group_message=False,
            chat_id="+15559876543",
        )

        assert len(media_paths) == 1
        assert Path(media_paths[0]).read_bytes() == b"ONLY-PHOTO"
        assert Path(media_paths[0]).name == filename
        assert "[image:" in content
