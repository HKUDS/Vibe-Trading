"""``cookie`` and ``private_key`` payload fields are treated as credentials."""

from __future__ import annotations

import pytest

from src.tools.redaction import ARGUMENTS_SINK, RESULT_SINK, is_sensitive_arg, redact_payload


@pytest.mark.parametrize(
    "name",
    ["cookie", "Cookie", "cookies", "set-cookie", "Set-Cookie", "session_cookie",
     "sessionCookie", "private_key", "privateKey", "private-key", "Private Key",
     "ssh_private_key", "rsa_private_key_pem"],
)
@pytest.mark.parametrize("sink", [ARGUMENTS_SINK, RESULT_SINK])
def test_cookie_and_private_key_field_names_are_sensitive(name: str, sink: str) -> None:
    assert is_sensitive_arg(name, sink=sink)


@pytest.mark.parametrize("name", ["public_key", "key_id", "cooking_time", "credential_status", "account_ref"])
def test_unrelated_field_names_stay_readable(name: str) -> None:
    assert not is_sensitive_arg(name)


def test_payload_walk_redacts_cookie_and_private_key_values() -> None:
    payload = {
        "headers_seen": {"Set-Cookie": "sid=abc123", "Cookie": "sid=abc123"},
        "wallet": {"private_key": "0xdeadbeef", "public_key": "0xpub"},
        "items": [{"cookies": {"sid": "abc123"}}],
        "symbol": "AAPL",
    }
    out = redact_payload(payload)
    assert out["headers_seen"] == {"Set-Cookie": "[redacted]", "Cookie": "[redacted]"}
    assert out["wallet"] == {"private_key": "[redacted]", "public_key": "0xpub"}
    assert out["items"] == [{"cookies": "[redacted]"}]
    assert out["symbol"] == "AAPL"
