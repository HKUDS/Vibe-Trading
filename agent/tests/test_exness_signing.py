"""Exness Trader API request-signing tests (pure crypto, no network).

The vector is the public example from the Exness developer portal
(request-signing page): RFC 8032 "Test 1" Ed25519 key, a synthetic API key and
a fixed timestamp. Matching it byte-for-byte pins the canonical JSON shape
(key order, compact separators, integer timestamp/sign_version).
"""

from __future__ import annotations

import base64
import json

import pytest

from src.trading.connectors.exness._signing import (
    EMPTY_BODY_HASH,
    ExnessKeyError,
    body_hash,
    build_headers,
    load_private_key,
)

pytestmark = pytest.mark.unit

_RFC8032_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_RFC8032_PUB = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_RFC8032_HEX = _RFC8032_SEED + _RFC8032_PUB


def _rfc8032_pem() -> str:
    """PKCS#8 PEM of the public RFC 8032 test seed, built at runtime.

    Serialized here rather than committed as a literal key block so secret
    scanners never see a ``PRIVATE KEY`` header in the repository.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_RFC8032_SEED))
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
_EXPECTED_SIGN = "l-H_Acia8YoTjKFMg-3fon3NOEX8TalNVA7c01DQ9dHb7pVBJC4y06qC-DbpETzh1KToiOprqEV6uzN3t69ICQ"


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _vector_headers(key_text: str) -> dict[str, str]:
    return build_headers(
        method="get",
        path="/v1/trading/access-point?account_id=123456",
        body=b"",
        api_key="exnsk-synthetic-example",
        private_key=load_private_key(key_text),
        idempotency_key="",
        timestamp_ms=1773656070123,
    )


def test_empty_body_hash_matches_documented_constant() -> None:
    assert EMPTY_BODY_HASH == "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"
    assert body_hash(b"") == EMPTY_BODY_HASH


def test_hex_key_reproduces_official_signature_vector() -> None:
    headers = _vector_headers(_RFC8032_HEX)
    assert headers["EXN-SIGN"] == _EXPECTED_SIGN


def test_pem_key_reproduces_official_signature_vector() -> None:
    headers = _vector_headers(_rfc8032_pem())
    assert headers["EXN-SIGN"] == _EXPECTED_SIGN


def test_exn_data_is_unpadded_base64url_of_compact_canonical_json() -> None:
    headers = _vector_headers(_RFC8032_HEX)
    assert "=" not in headers["EXN-DATA"]
    raw = _decode(headers["EXN-DATA"])
    payload = json.loads(raw)
    assert list(payload) == [
        "api_key",
        "idempotency_key",
        "timestamp",
        "sign_version",
        "method",
        "path",
        "body_hash",
    ]
    assert payload["method"] == "GET"
    assert payload["timestamp"] == 1773656070123
    assert payload["sign_version"] == 1
    assert b" " not in raw


def test_all_required_headers_are_present() -> None:
    headers = _vector_headers(_RFC8032_HEX)
    assert headers["EXN-API-KEY"] == "exnsk-synthetic-example"
    assert headers["EXN-IDEMPOTENCY-KEY"] == ""
    assert headers["EXN-TIMESTAMP"] == "1773656070123"
    assert headers["EXN-SIGN-VERSION"] == "1"


def test_post_body_hash_covers_exact_body_bytes() -> None:
    body = b'{"instrument":"EURUSD","side":"buy","volume":"0.01"}'
    headers = build_headers(
        method="POST",
        path="/v1/trading/accounts/1/positions",
        body=body,
        api_key="exnsk-synthetic-example",
        private_key=load_private_key(_RFC8032_HEX),
        idempotency_key="vt-abc123",
        timestamp_ms=1,
    )
    payload = json.loads(_decode(headers["EXN-DATA"]))
    assert payload["body_hash"] == body_hash(body)
    assert payload["body_hash"] != EMPTY_BODY_HASH
    assert payload["idempotency_key"] == "vt-abc123"
    assert headers["Content-Type"] == "application/json"


def test_hex_key_with_mismatched_public_half_is_rejected() -> None:
    tampered = _RFC8032_SEED + "00" * 32
    with pytest.raises(ExnessKeyError, match="public key"):
        load_private_key(tampered)


@pytest.mark.parametrize("bad", ["", "abc", "zz" * 64, _RFC8032_SEED, "exnsk-not-a-private-key"])
def test_malformed_keys_are_rejected_without_echoing_material(bad: str) -> None:
    with pytest.raises(ExnessKeyError) as excinfo:
        load_private_key(bad)
    if bad:
        assert bad not in str(excinfo.value)


def test_non_ed25519_pem_is_rejected() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    with pytest.raises(ExnessKeyError, match="Ed25519"):
        load_private_key(pem)
