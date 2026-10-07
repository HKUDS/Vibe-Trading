"""Regression tests for #1492: baostock socket IO must stay bounded.

baostock 0.9.3's send_msg reads with no timeout and spins at 100% CPU when
the peer closes the connection. The loader swaps in a bounded send_msg and a
connect with a deadline for the duration of every fetch.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from backtest.loaders.baostock_loader import (
    _DEFAULT_READ_TIMEOUT,
    _READ_TIMEOUT_ENV,
    _baostock_socket_guard,
    _bounded_send_msg,
    _connect_with_timeout,
    _read_timeout,
)

bs = pytest.importorskip("baostock")
import baostock.common.contants as cons  # noqa: E402
import baostock.common.context as context  # noqa: E402

_TERMINATOR = b"<![CDATA[]]>\n"


def _serve_once(handler):
    """Run handler(client_sock) on one accepted connection; returns the port."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        conn, _ = srv.accept()
        with conn:
            handler(conn)
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port


def _connect(port: int) -> socket.socket:
    return socket.create_connection(("127.0.0.1", port), timeout=2)


@pytest.fixture(autouse=True)
def _clean_default_socket():
    yield
    sock = getattr(context, "default_socket", None)
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
        setattr(context, "default_socket", None)


def test_silent_server_times_out() -> None:
    port = _serve_once(lambda conn: time.sleep(5))
    setattr(context, "default_socket", _connect(port))
    started = time.monotonic()
    assert _bounded_send_msg("login\1anonymous", timeout=0.3) is None
    assert time.monotonic() - started < 3


def test_closed_connection_returns_none_instead_of_spinning() -> None:
    # recv() returns b"" forever here; stock baostock spins on this at 100% CPU.
    port = _serve_once(lambda conn: None)
    setattr(context, "default_socket", _connect(port))
    started = time.monotonic()
    assert _bounded_send_msg("login\1anonymous", timeout=5) is None
    assert time.monotonic() - started < 3


def test_healthy_reply_roundtrip_unchanged() -> None:
    body = "hello"
    header = (
        cons.BAOSTOCK_CLIENT_VERSION
        + cons.MESSAGE_SPLIT
        + "00"  # any type outside COMPRESSED_MESSAGE_TYPE_TUPLE
        + cons.MESSAGE_SPLIT
        + str(len(body)).zfill(10)
    )
    assert len(header) == cons.MESSAGE_HEADER_LENGTH
    reply = (header + body).encode() + _TERMINATOR

    def handler(conn: socket.socket) -> None:
        conn.recv(4096)
        conn.sendall(reply)

    port = _serve_once(handler)
    setattr(context, "default_socket", _connect(port))
    assert _bounded_send_msg("login\1anonymous", timeout=2) == reply.decode()


def test_malformed_reply_returns_none() -> None:
    def handler(conn: socket.socket) -> None:
        conn.recv(4096)
        conn.sendall(b"garbage" + _TERMINATOR)

    port = _serve_once(handler)
    setattr(context, "default_socket", _connect(port))
    assert _bounded_send_msg("login\1anonymous", timeout=2) is None


def test_connect_failure_degrades_to_none(monkeypatch) -> None:
    # Closed loopback port: refused fast. Stock 0.9.3 raises NameError here via
    # the unbound socket in SocketUtil.connect.
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(cons, "BAOSTOCK_SERVER_IP", "127.0.0.1")
    monkeypatch.setattr(cons, "BAOSTOCK_SERVER_PORT", closed_port)
    _connect_with_timeout(None, timeout=0.5)
    assert getattr(context, "default_socket", None) is None
    assert _bounded_send_msg("login\1anonymous", timeout=0.5) is None


def test_guard_patches_and_restores() -> None:
    socketutil = bs.util.socketutil
    original_send = socketutil.send_msg
    original_connect = socketutil.SocketUtil.connect
    with _baostock_socket_guard(0.5):
        assert socketutil.send_msg is not original_send
        assert socketutil.SocketUtil.connect is not original_connect
    assert socketutil.send_msg is original_send
    assert socketutil.SocketUtil.connect is original_connect


def test_read_timeout_env(monkeypatch) -> None:
    assert _read_timeout() == _DEFAULT_READ_TIMEOUT
    monkeypatch.setenv(_READ_TIMEOUT_ENV, "0.7")
    assert _read_timeout() == 0.7
    monkeypatch.setenv(_READ_TIMEOUT_ENV, "not-a-number")
    assert _read_timeout() == _DEFAULT_READ_TIMEOUT
    monkeypatch.setenv(_READ_TIMEOUT_ENV, "-3")
    assert _read_timeout() == _DEFAULT_READ_TIMEOUT


@pytest.mark.parametrize("value", ["inf", "-inf", "nan", "0", "-0.1"])
def test_timeout_must_be_finite_and_positive(monkeypatch, value) -> None:
    monkeypatch.setenv(_READ_TIMEOUT_ENV, value)
    assert _read_timeout() == _DEFAULT_READ_TIMEOUT


def test_slow_trickle_cannot_extend_message_deadline() -> None:
    stopped = threading.Event()

    def handler(conn):
        conn.recv(4096)
        try:
            for _ in range(30):
                conn.sendall(b"x")
                if stopped.wait(0.03):
                    break
        except OSError:
            pass

    port = _serve_once(handler)
    sock = _connect(port)
    context.default_socket = sock
    try:
        started = time.monotonic()
        assert _bounded_send_msg("request", timeout=0.15) is None
        assert time.monotonic() - started < 0.75
        assert context.default_socket is None
        assert sock.fileno() == -1
    finally:
        stopped.set()


def test_compressed_reply_and_full_request_over_real_socket() -> None:
    import zlib

    body = "0\1success\1测试行情\n"
    compressed = zlib.compress(body.encode())
    header = (
        cons.BAOSTOCK_CLIENT_VERSION + cons.MESSAGE_SPLIT + "96" + cons.MESSAGE_SPLIT + str(len(compressed)).zfill(10)
    )
    request = "query" * 100_000
    received = []

    def handler(conn):
        data = bytearray()
        while not data.endswith(b"\n"):
            data.extend(conn.recv(1024))
        received.append(bytes(data))
        reply = header.encode() + compressed + _TERMINATOR
        for offset in range(0, len(reply), 7):
            conn.sendall(reply[offset : offset + 7])

    port = _serve_once(handler)
    sock = _connect(port)

    class PartialSendSocket:
        """A real socket with send() capped, as permitted by the socket API."""

        def send(self, data):
            return sock.send(data[:1])

        def __getattr__(self, name):
            return getattr(sock, name)

    sock.settimeout(0.9)
    context.default_socket = PartialSendSocket()
    assert _bounded_send_msg(request, timeout=2) == header + body
    assert received == [(request + "\n").encode()]
    assert sock.gettimeout() == 0.9


def test_guard_serializes_sessions_and_restores_socket_and_patch() -> None:
    entered = threading.Event()
    release = threading.Event()
    second_attempt = threading.Event()
    second_entered = threading.Event()
    errors = []
    socketutil = bs.util.socketutil
    original_send = socketutil.send_msg
    original_connect = socketutil.SocketUtil.connect
    previous, peer = socket.socketpair()
    context.default_socket = previous
    owned_sockets = []

    def run(first):
        try:
            if not first:
                second_attempt.set()
            with _baostock_socket_guard(2) as acquired:
                assert acquired
                assert context.default_socket is None
                local, remote = socket.socketpair()
                owned_sockets.append(local)
                context.default_socket = local
                with remote:
                    if first:
                        entered.set()
                        assert release.wait(2)
                    else:
                        second_entered.set()
                    assert context.default_socket is local
                    assert socketutil.send_msg is not original_send
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=(True,))
    second = threading.Thread(target=run, args=(False,))
    try:
        first.start()
        assert entered.wait(2)
        second.start()
        assert second_attempt.wait(2)
        assert not second_entered.wait(0.1)
        release.set()
        first.join(3)
        second.join(3)
        assert not first.is_alive() and not second.is_alive()
        assert not errors
        assert second_entered.is_set()
        assert context.default_socket is previous
        assert previous.fileno() != -1
        assert all(sock.fileno() == -1 for sock in owned_sockets)
        assert socketutil.send_msg is original_send
        assert socketutil.SocketUtil.connect is original_connect
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
        peer.close()
        previous.close()


def test_guard_contention_is_bounded_and_does_not_change_active_session() -> None:
    from backtest.loaders.baostock_loader import _BAOSTOCK_LOCK

    original_send = bs.util.socketutil.send_msg
    with _BAOSTOCK_LOCK:
        started = time.monotonic()
        with _baostock_socket_guard(0.05) as acquired:
            assert acquired is False
        assert time.monotonic() - started < 1
        assert bs.util.socketutil.send_msg is original_send


@pytest.mark.parametrize("mode", ["silent", "closed"])
def test_real_sdk_login_failure_reaches_market_data_fallback(monkeypatch, mode):
    import pandas as pd
    from backtest.loaders.baostock_loader import DataLoader
    from src.market_data import fetch_market_data

    finished = threading.Event()

    def handler(conn):
        conn.recv(4096)
        if mode == "silent":
            finished.wait(2)

    port = _serve_once(handler)
    monkeypatch.setattr(cons, "BAOSTOCK_SERVER_IP", "127.0.0.1")
    monkeypatch.setattr(cons, "BAOSTOCK_SERVER_PORT", port)
    monkeypatch.setenv(_READ_TIMEOUT_ENV, "0.1")
    called = []

    class FallbackLoader:
        def fetch(self, codes, *args, **kwargs):
            called.extend(codes)
            return {
                codes[0]: pd.DataFrame(
                    {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                    index=pd.to_datetime(["2024-01-02"]),
                )
            }

    try:
        result = fetch_market_data(
            codes=["601398.SH"],
            start_date="2024-01-01",
            end_date="2024-01-03",
            source="baostock",
            max_fallback_attempts=2,
            loader_resolver=lambda source: DataLoader if source == "baostock" else FallbackLoader,
            fallback_chain_provider=lambda source: ["baostock", "fallback"],
        )
        assert called == ["601398.SH"]
        assert result["601398.SH"]
        assert context.default_socket is None
    finally:
        finished.set()


def test_blocked_send_is_bounded_and_discards_connection():
    finished = threading.Event()
    port = _serve_once(lambda conn: finished.wait(2))
    sock = _connect(port)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    context.default_socket = sock
    try:
        started = time.monotonic()
        assert _bounded_send_msg("x" * 8_000_000, timeout=0.1) is None
        assert time.monotonic() - started < 1
        assert context.default_socket is None
        assert sock.fileno() == -1
    finally:
        finished.set()


def test_guard_restores_after_failed_session():
    original_send = bs.util.socketutil.send_msg
    original_connect = bs.util.socketutil.SocketUtil.connect
    owned, peer = socket.socketpair()
    try:
        with pytest.raises(RuntimeError, match="failed session"):
            with _baostock_socket_guard(0.1) as acquired:
                assert acquired
                context.default_socket = owned
                raise RuntimeError("failed session")
        assert owned.fileno() == -1
        assert context.default_socket is None
        assert bs.util.socketutil.send_msg is original_send
        assert bs.util.socketutil.SocketUtil.connect is original_connect
        with _baostock_socket_guard(0.1) as acquired:
            assert acquired
    finally:
        owned.close()
        peer.close()
