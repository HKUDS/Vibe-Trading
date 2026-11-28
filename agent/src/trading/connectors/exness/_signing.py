"""Exness Trader API request signing (Ed25519, sign version 1).

Every request carries ``EXN-DATA`` — unpadded base64url of a compact UTF-8
JSON object — and ``EXN-SIGN``, the Ed25519 signature over those exact JSON
bytes. The key order, compact separators and integer ``timestamp`` /
``sign_version`` are part of the contract: they reproduce the official vector
in the developer portal byte-for-byte (see ``tests/test_exness_signing.py``).

Pure module: no network, no config, no logging. Key material never appears in
exception messages.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SIGN_VERSION = 1

_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{128}$")


class ExnessKeyError(ValueError):
    """The configured signing key is missing, malformed or not Ed25519."""


def b64url(raw: bytes) -> str:
    """Return unpadded base64url text for ``raw``."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def body_hash(body: bytes) -> str:
    """Return the unpadded base64url SHA-256 of the exact request body bytes."""
    return b64url(hashlib.sha256(body).digest())


EMPTY_BODY_HASH = body_hash(b"")


def load_private_key(text: str) -> Ed25519PrivateKey:
    """Parse an Exness signing key.

    Accepts the Exness-generated form (128 hex characters: 32-byte seed then
    32-byte public key, whose public half is verified against the seed) or an
    unencrypted PKCS#8 PEM.

    Args:
        text: Key text from config / env / keyring.

    Returns:
        The Ed25519 private key.

    Raises:
        ExnessKeyError: If the key is empty, malformed, encrypted, not Ed25519,
            or its public half does not match the seed. The message never
            includes key material.
    """
    clean = (text or "").strip()
    if not clean:
        raise ExnessKeyError("Exness private_key is empty")
    if "-----BEGIN" in clean:
        try:
            key = serialization.load_pem_private_key(clean.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            raise ExnessKeyError(f"Exness private_key PEM could not be loaded ({type(exc).__name__})") from None
        if not isinstance(key, Ed25519PrivateKey):
            raise ExnessKeyError("Exness private_key PEM is not an Ed25519 key")
        return key
    if not _HEX_KEY_RE.match(clean):
        raise ExnessKeyError(
            "Exness private_key must be 128 hex characters (seed + public key) or an unencrypted PKCS#8 PEM"
        )
    raw = bytes.fromhex(clean)
    key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if public != raw[32:]:
        raise ExnessKeyError("Exness private_key public key half does not match its seed")
    return key


def build_headers(
    *,
    method: str,
    path: str,
    body: bytes,
    api_key: str,
    private_key: Ed25519PrivateKey,
    idempotency_key: str,
    timestamp_ms: int,
) -> dict[str, str]:
    """Build the signed ``EXN-*`` headers for one request.

    Args:
        method: HTTP method (normalized to upper case).
        path: Path plus query exactly as sent (no scheme/host).
        body: Exact request body bytes (``b""`` for none).
        api_key: The ``exnsk-…`` key id.
        private_key: Loaded Ed25519 signing key.
        idempotency_key: ``""`` for reads; a fresh unique key for mutations.
        timestamp_ms: Unix time in milliseconds.

    Returns:
        Header dict ready to send (adds ``Content-Type`` when ``body`` is set).
    """
    payload = {
        "api_key": api_key,
        "idempotency_key": idempotency_key,
        "timestamp": int(timestamp_ms),
        "sign_version": SIGN_VERSION,
        "method": method.upper(),
        "path": path,
        "body_hash": body_hash(body),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "EXN-API-KEY": api_key,
        "EXN-IDEMPOTENCY-KEY": idempotency_key,
        "EXN-TIMESTAMP": str(int(timestamp_ms)),
        "EXN-SIGN-VERSION": str(SIGN_VERSION),
        "EXN-DATA": b64url(raw),
        "EXN-SIGN": b64url(private_key.sign(raw)),
    }
    if body:
        headers["Content-Type"] = "application/json"
    return headers
