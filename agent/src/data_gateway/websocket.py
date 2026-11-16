"""Public WebSocket lifetime adapter; no market or trading behavior changes."""

import logging
from websockets.asyncio.client import ClientConnection


def release_error_frames(error):
    """Drop closed transport frames while preserving error type, text and causes."""
    pending, seen = [error], set()
    while pending and len(seen) < 32:
        item = pending.pop()
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        item.__traceback__ = None
        pending.extend((item.__cause__, item.__context__))


class PublicConnection(ClientConnection):
    """Release SDK logging/exception cycles as soon as a transport closes."""

    def __init__(self, protocol, **kwargs):
        logger = protocol.logger
        super().__init__(protocol, **kwargs)
        self.logger = protocol.logger = logging.LoggerAdapter(logger, {"websocket_id": str(self.id)})

    def connection_lost(self, exc):
        # The SDK records parser EOFError with a traceback whose f_back points
        # at this callback. That retains connection -> TLS transport -> buffers
        # after an abort. Preserve its diagnostic identity, not its dead frames.
        try:
            super().connection_lost(exc)
        finally:
            # websockets 17 renamed recv_exc to connection_exc.
            for error in (
                self.protocol.parser_exc,
                self.protocol.handshake_exc,
                getattr(self, "recv_exc", None),
                getattr(self, "connection_exc", None),
            ):
                release_error_frames(error)
