"""Cancellation cleanup for the registered upload route, without server I/O."""

from __future__ import annotations

import asyncio
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, UploadFile

from src.api import uploads_routes


def test_cancelled_upload_removes_unpublished_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel a real route task after a chunk was written and a read suspended."""

    async def exercise() -> None:
        app = FastAPI()
        # The module's compatibility host lookup stays isolated from api_server
        # and any operator runtime state.
        host = SimpleNamespace(
            UPLOADS_DIR=tmp_path, MAX_UPLOAD_SIZE=1024, _UPLOAD_CHUNK_SIZE=4
        )
        monkeypatch.setitem(sys.modules, "api_server", host)
        uploads_routes.register_uploads_routes(app, require_auth=lambda: None)
        endpoint = next(
            route.endpoint for route in app.routes if route.path == "/upload"
        )
        upload = UploadFile(file=BytesIO(b"part"), filename="note.txt")
        read_started = asyncio.Event()
        original_read = upload.read

        async def interrupted_read(size: int = -1) -> bytes:
            if upload.file.tell() == 0:
                return await original_read(size)
            read_started.set()
            await asyncio.Future()
            raise AssertionError("cancelled read resumed")

        upload.read = interrupted_read
        upload.close = AsyncMock(wraps=upload.close)
        task = asyncio.create_task(endpoint(upload))
        await asyncio.wait_for(read_started.wait(), timeout=2)
        assert len(list(tmp_path.iterdir())) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        upload.close.assert_awaited_once()
        assert upload.file.closed
        assert list(tmp_path.iterdir()) == []

    asyncio.run(exercise())
