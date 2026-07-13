"""Integration test for the Vibe-Trading MCP server's Streamable HTTP transport.

Spawns the real ``mcp_server.py --transport http`` and verifies the single
``/mcp`` endpoint behaves per the MCP Streamable HTTP transport:

1. POST ``initialize`` returns a valid JSON-RPC InitializeResult with an
   ``MCP-Session-Id`` header.
2. The legacy ``/sse`` path is not mounted by this transport (it is only
   exposed by the separate ``--transport sse`` legacy mode).

This is intentionally scoped to the server-side transport; the client-side
adapter path is already covered by ``test_mcp_streamable_http_integration.py``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"

INIT_TIMEOUT = 60.0


def _wait_port(host: str, port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            if s.connect_ex((host, port)) == 0:
                s.close()
                return True
        finally:
            s.close()
        time.sleep(0.5)
    return False


@pytest.mark.integration
def test_mcp_server_http_transport() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AGENT_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    # Reserve an ephemeral loopback port for the server.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    proc = subprocess.Popen(
        [
            sys.executable,
            str(AGENT_DIR / "mcp_server.py"),
            "--transport",
            "http",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=str(AGENT_DIR),
    )
    try:
        assert _wait_port(
            "127.0.0.1", port, INIT_TIMEOUT
        ), f"HTTP MCP server did not bind 127.0.0.1:{port} within {INIT_TIMEOUT}s"

        ep = f"http://127.0.0.1:{port}/mcp"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        r = requests.post(
            ep,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-mcp-server-http", "version": "1"},
                },
            },
            timeout=15.0,
        )
        assert (
            r.status_code == 200
        ), f"POST /mcp initialize returned {r.status_code}: {r.text[:300]}"
        assert (
            "mcp-session-id" in r.headers
        ), "server did not return an MCP-Session-Id header"
        assert r.headers.get("content-type", "") in (
            "application/json",
            "text/event-stream",
        ), f"unexpected content-type: {r.headers.get('content-type')}"
        body = r.text
        if "text/event-stream" in r.headers.get("content-type", ""):
            for line in body.splitlines():
                if line.startswith("data:"):
                    body = line[5:].strip()
                    break
        data = json.loads(body)
        assert "result" in data, f"initialize response missing result: {data}"
        server_info = data["result"].get("serverInfo", {})
        assert server_info.get("name") == "Vibe-Trading", server_info

        # The legacy SSE path is not mounted by the streamable-http transport.
        legacy = requests.post(
            f"http://127.0.0.1:{port}/sse",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {}},
            timeout=5.0,
        )
        assert (
            legacy.status_code == 404
        ), f"legacy /sse path should not be mounted by streamable-http, got {legacy.status_code}"
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
