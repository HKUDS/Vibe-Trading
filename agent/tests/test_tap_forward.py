"""Direct unit tests for ``src.trading.tap_forward``.

The connector tests (test_alpaca_tap_routing.py) mock ``tap_forward.forward``
wholesale, so this file exercises the module itself with ``urllib`` mocked:
the fail-closed error paths, the 202 → poll → decision loop, and the
poll-URL exfiltration guard (the agent key must never be sent to a URL taken
from a response body unless it is a relative path re-rooted on the configured
base). No network, no TAP instance needed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from src.trading import tap_forward as tf

pytestmark = pytest.mark.unit

_BASE = "https://tap.test.local"
_CRED = {"APCA-API-KEY-ID": "<CREDENTIAL:alpaca.key_id>"}


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture()
def tap_env(monkeypatch):
    """Configure TAP purely via the environment (no .env scanning)."""
    monkeypatch.setenv("TAP_PROXY_URL", _BASE)
    monkeypatch.setenv("TAP_AGENT_KEY", "tap-agent-key-under-test")
    monkeypatch.setattr(tf.time, "sleep", lambda s: None)  # poll loop: no real waiting


def _install_urlopen(monkeypatch, handler):
    """Route ``urllib.request.urlopen`` to ``handler(req)`` and record calls.

    Returns the call log: a list of ``(method, url, header_names)`` tuples.
    ``header_names`` uses the original casing so the exfil tests can assert on
    whether X-TAP-Key was attached to a given URL.
    """
    calls: list[tuple[str, str, list[str]]] = []

    def fake_urlopen(req, timeout=None):
        assert isinstance(req, urllib.request.Request)
        calls.append((req.get_method(), req.full_url, list(req.headers)))
        return handler(req)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


# --------------------------------------------------------------------------- #
# Fail-closed basics
# --------------------------------------------------------------------------- #


def test_connection_error_fails_closed(tap_env, monkeypatch) -> None:
    def handler(req):
        raise urllib.error.URLError("connection refused")

    _install_urlopen(monkeypatch, handler)
    result = tf.forward(f"{_BASE}/v2/orders", "POST", "{}", _CRED)

    assert result["ok"] is False
    assert "connection failed" in (result["error"] or "")


def test_unconfigured_tap_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("TAP_PROXY_URL", raising=False)
    monkeypatch.delenv("TAP_AGENT_KEY", raising=False)
    monkeypatch.setattr(tf, "_load_env_into_environ", lambda: None)  # skip .env scan

    def handler(req):  # pragma: no cover - must never be reached
        raise AssertionError("no HTTP call may happen without TAP config")

    _install_urlopen(monkeypatch, handler)
    result = tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED)

    assert result["ok"] is False
    assert result["error"] == "TAP not configured"


def test_immediate_read_success(tap_env, monkeypatch) -> None:
    _install_urlopen(
        monkeypatch, lambda req: _FakeResponse(200, json.dumps({"cash": "1000"}))
    )
    result = tf.forward("https://api.example/v2/account", "GET", None, _CRED)

    assert result["ok"] is True
    assert result["decision"] == "immediate"
    assert result["status"] == 200
    assert result["body"] == {"cash": "1000"}


# --------------------------------------------------------------------------- #
# 202 → poll → terminal decision
# --------------------------------------------------------------------------- #


def _write_then_poll(monkeypatch, poll_bodies: list[str]):
    """First call: 202 with a txn_id. Subsequent calls: pop from poll_bodies."""
    state = {"first": True}

    def handler(req):
        if state["first"]:
            state["first"] = False
            return _FakeResponse(202, json.dumps({"txn_id": "txn-1"}))
        return _FakeResponse(200, poll_bodies.pop(0))

    return _install_urlopen(monkeypatch, handler)


def test_approved_write_polls_until_forwarded(tap_env, monkeypatch) -> None:
    calls = _write_then_poll(monkeypatch, [
        json.dumps({"status": "pending"}),
        json.dumps({"status": "forwarded",
                    "response": {"status": 200, "body": '{"id": "ord-1"}'}}),
    ])
    result = tf.forward(f"https://api.example/v2/orders", "POST", "{}", _CRED, timeout=30)

    assert result["ok"] is True
    assert result["decision"] == "forwarded"
    assert result["status"] == 200
    assert result["body"] == '{"id": "ord-1"}'
    # The poll went to the CONFIGURED base, derived from the txn_id.
    poll_calls = [c for c in calls if c[0] == "GET"]
    assert all(url == f"{_BASE}/agent/approvals/txn-1" for _, url, _ in poll_calls)


def test_forwarded_with_upstream_error_is_not_ok(tap_env, monkeypatch) -> None:
    _write_then_poll(monkeypatch, [
        json.dumps({"status": "forwarded",
                    "response": {"status": 422, "body": '{"message": "rejected"}'}}),
    ])
    result = tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED, timeout=30)

    assert result["ok"] is False  # forwarded but upstream refused → still fail-closed
    assert result["decision"] == "forwarded"
    assert result["status"] == 422


@pytest.mark.parametrize("decision", ["denied", "timed_out", "error"])
def test_terminal_refusals_fail_closed(tap_env, monkeypatch, decision) -> None:
    _write_then_poll(monkeypatch, [json.dumps({"status": decision})])
    result = tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED, timeout=30)

    assert result["ok"] is False
    assert result["decision"] == decision


def test_no_decision_within_timeout_fails_closed(tap_env, monkeypatch) -> None:
    # timeout=0 → the poll loop never runs; the deadline path must fail closed.
    _install_urlopen(
        monkeypatch, lambda req: _FakeResponse(202, json.dumps({"txn_id": "txn-1"}))
    )
    result = tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED, timeout=0)

    assert result["ok"] is False
    assert result["decision"] == "timeout"


# --------------------------------------------------------------------------- #
# Poll-URL exfiltration guard: X-TAP-Key must never travel to a URL taken from
# a response body — only a relative path re-rooted on the configured base.
# --------------------------------------------------------------------------- #


def _respond_202(monkeypatch, payload: dict):
    """202 with an attacker-controlled body; any later GET returns 'forwarded'."""
    state = {"first": True}

    def handler(req):
        if state["first"]:
            state["first"] = False
            return _FakeResponse(202, json.dumps(payload))
        return _FakeResponse(200, json.dumps(
            {"status": "forwarded", "response": {"status": 200, "body": "{}"}}))

    return _install_urlopen(monkeypatch, handler)


@pytest.mark.parametrize("poll_url", [
    "https://evil.example/steal",   # absolute URL → refused
    "//evil.example/steal",         # protocol-relative → refused (no leading single "/")
    "agent/approvals/txn-1",        # not "/"-prefixed → refused
])
def test_tampered_poll_url_is_rejected_and_never_contacted(tap_env, monkeypatch, poll_url) -> None:
    calls = _respond_202(monkeypatch, {"poll_url": poll_url})
    result = tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED, timeout=30)

    assert result["ok"] is False
    assert "txn_id" in (result["error"] or "")
    # Only the initial POST happened — the key was never sent anywhere else.
    assert len(calls) == 1
    assert calls[0][0] == "POST" and calls[0][1] == f"{_BASE}/forward"


def test_protocol_relative_poll_url_is_refused_specifically(tap_env, monkeypatch) -> None:
    # "//evil.example/x" starts with "/" per a naive check; base + "//host/x"
    # would resolve to the attacker's host. It must not be polled.
    calls = _respond_202(monkeypatch, {"poll_url": "//evil.example/x"})
    tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED, timeout=30)

    assert all("evil.example" not in url for _, url, _ in calls)


def test_relative_poll_url_is_rerooted_on_configured_base(tap_env, monkeypatch) -> None:
    calls = _respond_202(monkeypatch, {"poll_url": "/agent/approvals/txn-9"})
    result = tf.forward("https://api.example/v2/orders", "POST", "{}", _CRED, timeout=30)

    assert result["ok"] is True
    get_calls = [c for c in calls if c[0] == "GET"]
    assert get_calls and all(url == f"{_BASE}/agent/approvals/txn-9" for _, url, _ in get_calls)


# --------------------------------------------------------------------------- #
# .env loader robustness (review item: a non-UTF-8 .env must not break calls)
# --------------------------------------------------------------------------- #


def test_non_utf8_env_file_is_skipped(tmp_path, monkeypatch) -> None:
    bad = tmp_path / ".env"
    bad.write_bytes(b"TAP_PROXY_URL=\xff\xfe broken \x80\n")
    monkeypatch.setattr(tf, "_ENV_CANDIDATES", (bad,))
    monkeypatch.delenv("TAP_PROXY_URL", raising=False)
    monkeypatch.delenv("TAP_AGENT_KEY", raising=False)

    tf._load_env_into_environ()  # must not raise UnicodeDecodeError

    assert tf.tap_enabled() is False  # unreadable file ≡ missing file
