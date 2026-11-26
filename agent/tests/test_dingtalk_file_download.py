"""A remote fileName must not escape the per-sender download directory, and
two downloads that land on the same filename must not overwrite each other.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.channels.dingtalk import DingTalkChannel


def _channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_bytes: bytes
) -> DingTalkChannel:
    channel = object.__new__(DingTalkChannel)
    channel.logger = logging.getLogger("test.dingtalk")
    channel.config = type("Config", (), {"client_id": "test-client"})()
    channel._access_token = "test-token"
    channel._token_expiry = float("inf")

    token_response = type(
        "Resp",
        (),
        {
            "status_code": 200,
            "json": lambda self: {"downloadUrl": "https://example.invalid/f"},
        },
    )()
    file_response = type("Resp", (), {"status_code": 200, "content": file_bytes})()
    http = AsyncMock()
    http.post = AsyncMock(return_value=token_response)
    http.get = AsyncMock(return_value=file_response)
    channel._http = http

    monkeypatch.setattr(
        "src.channels.utils.get_media_dir", lambda name: tmp_path / name
    )
    return channel


def test_path_traversal_filename_stays_inside_download_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        channel = _channel(tmp_path, monkeypatch, b"attacker content")

        result = await channel._download_dingtalk_file(
            "download-code", "../../../../../../tmp/evil.txt", "sender123"
        )

        assert result is not None
        result_path = Path(result).resolve()
        download_root = (tmp_path / "dingtalk" / "sender123").resolve()
        assert download_root in result_path.parents
        assert not (Path("/tmp") / "evil.txt").exists()

    asyncio.run(scenario())


def test_absolute_path_filename_stays_inside_download_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        channel = _channel(tmp_path, monkeypatch, b"attacker content")

        result = await channel._download_dingtalk_file(
            "download-code", "/tmp/evil_absolute.txt", "sender123"
        )

        assert result is not None
        result_path = Path(result).resolve()
        download_root = (tmp_path / "dingtalk" / "sender123").resolve()
        assert download_root in result_path.parents
        assert not Path("/tmp/evil_absolute.txt").exists()

    asyncio.run(scenario())


def test_two_downloads_with_the_same_filename_do_not_overwrite_each_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every picture message calls this with the literal "image.jpg", and a
    same-named attachment can repeat too -- the second download must not
    silently destroy the first one's bytes on disk.
    """
    channel = object.__new__(DingTalkChannel)
    channel.logger = logging.getLogger("test.dingtalk")
    channel.config = type("Config", (), {"client_id": "test-client"})()
    channel._access_token = "test-token"
    channel._token_expiry = float("inf")

    token_response = type(
        "Resp", (), {"status_code": 200, "json": lambda self: {"downloadUrl": "https://example.invalid/f"}}
    )()
    contents = iter([b"IMAGE_CONTENT_1", b"IMAGE_CONTENT_2"])

    def _next_file_response(*args, **kwargs):
        return type("Resp", (), {"status_code": 200, "content": next(contents)})()

    http = AsyncMock()
    http.post = AsyncMock(return_value=token_response)
    http.get = AsyncMock(side_effect=_next_file_response)
    channel._http = http

    monkeypatch.setattr("src.channels.utils.get_media_dir", lambda name: tmp_path / name)

    async def scenario() -> None:
        path1 = await channel._download_dingtalk_file("code-AAA", "image.jpg", "sender123")
        path2 = await channel._download_dingtalk_file("code-BBB", "image.jpg", "sender123")

        assert path1 is not None and path2 is not None
        assert path1 != path2
        assert Path(path1).read_bytes() == b"IMAGE_CONTENT_1"
        assert Path(path2).read_bytes() == b"IMAGE_CONTENT_2"

    asyncio.run(scenario())
