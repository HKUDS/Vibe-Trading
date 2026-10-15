"""PEM and PGP private-key blocks are scrubbed from free-form text."""

from __future__ import annotations

import pytest

from src.tools.redaction import redact_text

_BODY = "MIIEowIBAAKCAQEAx1Zq9f+/abc123XYZ=\nQmFzZTY0Qm9keUxpbmUyLy8vPT0=\n"


@pytest.mark.parametrize(
    "label",
    ["RSA PRIVATE KEY", "PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY",
     "ENCRYPTED PRIVATE KEY", "PGP PRIVATE KEY BLOCK"],
)
def test_private_key_block_is_redacted(label: str) -> None:
    block = f"-----BEGIN {label}-----\n{_BODY}-----END {label}-----"
    out = redact_text(f"key file:\n{block}\nend of file")
    assert "MIIEow" not in out and "QmFzZTY0" not in out
    assert out == "key file:\n[redacted]\nend of file"
    assert redact_text(out) == out


def test_encrypted_pem_headers_are_part_of_the_block() -> None:
    block = (
        "-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\n"
        "DEK-Info: AES-128-CBC,0123456789ABCDEF\n\n" + _BODY
        + "-----END RSA PRIVATE KEY-----"
    )
    assert redact_text(block) == "[redacted]"


def test_truncated_block_is_redacted_to_the_end() -> None:
    out = redact_text(f"head\n-----BEGIN PRIVATE KEY-----\n{_BODY}")
    assert out == "head\n[redacted]"


def test_two_blocks_are_redacted_independently() -> None:
    one = f"-----BEGIN PRIVATE KEY-----\n{_BODY}-----END PRIVATE KEY-----"
    out = redact_text(f"{one} and {one}")
    assert out == "[redacted] and [redacted]"


def test_public_material_is_left_alone() -> None:
    text = (
        "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQ==\n-----END PUBLIC KEY-----\n"
        "-----BEGIN CERTIFICATE-----\nMIIDdzCCAl+gAw==\n-----END CERTIFICATE-----"
    )
    assert redact_text(text) == text
