"""Raw-request identity: the deterministic input hash and safe echo helpers.

The error envelope echoes ``account_id`` and appends ``input_sha256=<digest>``
to every detail; this module owns that identity so a failure can be
correlated with the exact raw request without publishing a fabricated ledger.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..state_hash import canonicalize
from .models import JsonValue
from .wire_contract import INPUT_HASH_MARKER, _INPUT_HASH_SUFFIX
from .wire_errors import _fallback_json


# The raw-input hash deliberately hashes the wire spelling for bytes/str and
# the JCS spelling for parsed JSON values: the first is the actual request an
# auditor received, the second is order-independent so a dict-built test
# fixture and its reordered twin still identify the same payload.


def compute_raw_input_hash(raw_input: JsonValue | str | bytes | Any) -> str:
    """Return a stable SHA-256 identity for the raw request.

    ``bytes``/``str`` are hashed exactly as received (the auditor's raw wire
    text); every other value is hashed through RFC 8785 JCS. Values JCS cannot
    represent (NaN/Infinity, ``Decimal``, lone surrogates) fall back to a
    deterministic tagged normalization so an invalid request still has a
    stable identity for the error envelope.
    """
    if isinstance(raw_input, (bytes, bytearray, memoryview)):
        payload = bytes(raw_input)
    elif isinstance(raw_input, str):
        payload = raw_input.encode("utf-8", "surrogatepass")
    else:
        try:
            payload = canonicalize(raw_input).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError):
            normalized = json.dumps(
                _fallback_json(raw_input),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            payload = normalized.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _raw_account_id(raw_input: Any) -> str:
    """Echo ``account_id`` only when the raw request actually carries a string."""
    raw: Any = raw_input
    if isinstance(raw_input, (bytes, bytearray, memoryview, str)):
        try:
            raw = json.loads(raw_input)
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
    if isinstance(raw, Mapping):
        account_id = raw.get("account_id")
        if isinstance(account_id, str):
            return account_id
    return ""


def _wire_text(value: str) -> str:
    """Replace lone surrogates so an echoed error field stays valid UTF-8."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    return value


def _strip_input_hash_suffix(detail: str) -> str:
    """Remove any trailing hash markers before appending the current one."""
    while True:
        stripped = _INPUT_HASH_SUFFIX.sub("", detail)
        if stripped == detail:
            return detail
        detail = stripped


def _with_input_hash(detail: str, raw_input: Any) -> str:
    digest = compute_raw_input_hash(raw_input)
    marker = f"{INPUT_HASH_MARKER}={digest}"
    stable = _strip_input_hash_suffix(_wire_text(detail))
    return f"{stable}; {marker}" if stable else marker
