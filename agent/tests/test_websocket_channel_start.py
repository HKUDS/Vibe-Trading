"""The WebSocket channel must start: its logger symbol is a Logger, not a factory."""

from __future__ import annotations

import asyncio
import logging

from src.channels.websocket import WebSocketChannel
from src.channelsui.websocket_logging import websockets_server_logger
from src.channelsui.gateway_services import build_gateway_services


def test_websockets_server_logger_is_a_logger_not_a_factory():
    # the channel passes this object straight to websockets' logger= kwarg;
    # calling it used to raise TypeError before start() bound anything
    assert isinstance(websockets_server_logger, logging.Logger)


def test_websocket_channel_starts_on_a_unix_socket():
    from src.channels.bus.queue import MessageBus

    # macOS caps unix socket paths at 104 chars, so keep it short
    import tempfile, uuid as _uuid

    sock = f"{tempfile.gettempdir()}/vt-{_uuid.uuid4().hex[:8]}.sock"
    channel = WebSocketChannel(
        {
            "enabled": True,
            "unix_socket_path": sock,
            "path": "/ws",
            "host": "127.0.0.1",
            "port": 0,
        },
        MessageBus(),
        gateway=build_gateway_services(),
    )

    async def run():
        task = asyncio.create_task(channel.start())
        await asyncio.sleep(0.5)
        # start() reaches the serve loop: no TypeError from the logger line,
        # the task is alive and the channel reports running
        assert not task.done() or task.exception() is None
        assert channel.is_running
        await channel.stop()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(run())
