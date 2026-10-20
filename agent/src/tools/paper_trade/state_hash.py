"""JCS canonicalization + state-integrity hashing for ``paper_trade_step``.

Implements R7 / AM-4 of the pt-v1.1 contract (``received_state_hash`` and the
``effective_fee_model`` echo).  Per VD-4 the canonical form is hand-rolled —
zero new runtime dependencies — and the frozen test vectors in
``agent/tests/fixtures/paper_trade/jcs_vectors.json`` are the SOLE
interpretation authority (AM-4-2): both the VT engine and the RM observer
assert their own implementations against the same vectors.

Canonicalization rules (RFC 8785 JCS as frozen by VD-4):

* Object keys are sorted by Unicode code point — the semantics of
  ``json.dumps(sort_keys=True)``.  RFC 8785 itself sorts by UTF-16 code
  unit; the two orders agree for BMP-only keys, which is all the frozen
  vectors and the wire contract use.
* Numbers use the ECMAScript shortest round-trip representation, so
  ``100000.0`` and ``100000`` canonicalize identically (``100000``),
  ``-0.0`` canonicalizes as ``0``, and the exponential thresholds match
  ``JSON.stringify`` (``1e21`` -> ``1e+21`` but ``1e16`` ->
  ``10000000000000000``).  Integers are serialized exactly (Python
  semantics); the frozen vectors stay within +/-2^53 where every
  double-based implementation agrees.
* Strings are escaped by ``json.dumps(..., ensure_ascii=False)`` — raw
  UTF-8 for non-ASCII, ``\\uXXXX`` (lowercase hex) for control characters,
  matching ``JSON.stringify`` for BMP text.
* Arrays keep their order: element order is semantic (positions ordered by
  the RM ledger) and is never sorted or shuffled.

Determinism: this module reads no clock, no environment, no network and
writes nothing — the same input always produces the same bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

__all__ = [
    "canonicalize",
    "compute_received_state_hash",
    "effective_fee_model",
    "state_hash",
]

# FROZEN terminal defaults (G1: RM written approval 2026-10-19; APPROVAL note 5
# + REQUIREMENTS §4 fee matrix).  Key names are the pt-v1.1 final set — cn_a
# verbatim from the AMENDMENT §2.2 out-param example, hk/us mapped item-by-item
# to the §4 matrix; they are registered in the delivery note (#7) so the RM
# dispatch injection (AM-4-3: fee_model is always injected explicitly) aligns.
# Any key/value change = major schema bump with RM written confirmation
# (REQUIREMENTS §9).  VD-9 numeric choices registered in the delivery note:
# hk stamp duty quantizes to whole HKD ROUND_HALF_UP (HKEX itself ceils) and
# the us SEC fee is simplified to 0.
_DEFAULT_FEE_MODELS: dict[str, dict[str, float]] = {
    "cn_a": {
        "commission_rate": 0.00025,  # 万2.5 bilateral
        "commission_min": 5.0,  # ¥5 minimum per order
        "stamp_tax_sell": 0.0005,  # 万5 sell-side only
        "transfer_fee": 0.00001,  # 万0.1 bilateral
    },
    "hk": {
        "commission_rate": 0.0003,  # 0.03%
        "commission_min": 3.0,  # HK$3 minimum
        "stamp_tax_rate": 0.001,  # 0.1% per side, whole HKD ROUND_HALF_UP (VD-9)
        "regulatory_levy_rate": 0.00003,  # ≈0.003% combined levies
    },
    "us": {
        "commission_per_share": 0.0049,  # $0.0049/share
        "commission_min": 0.99,  # $0.99 minimum
        "sec_fee_rate": 0.0,  # simplified to zero (§4, VD-9 registered)
    },
}

#: Markets whose fee defaults are known.  Mirrors the pt-v1.1 ``market`` enum.
FEE_MODEL_MARKETS: tuple[str, ...] = ("cn_a", "hk", "us")


def _ecmascript_number(value: Decimal) -> str:
    """Serialize a finite Decimal per ECMAScript ``Number::toString``.

    This is the number form RFC 8785 mandates: the shortest digit string that
    round-trips, rendered by the ECMA-262 §7.1.12.1 branch rules (plain
    integer/decimal forms inside their thresholds, ``e±X`` outside).
    """
    if value == 0:
        # Covers -0.0 too: JCS/ECMAScript render negative zero as "0".
        return "0"
    sign, digits, exponent = value.normalize().as_tuple()
    # normalize() strips trailing zeros; guard the "0E+2" style residue.
    digits = tuple(int(d) for d in digits)
    k = len(digits)
    n = exponent + k  # value = m * 10^(n-k), m has k digits
    prefix = "-" if sign else ""
    body = "".join(str(d) for d in digits)
    if k <= n <= 21:
        return prefix + body + "0" * (n - k)
    if 0 < n <= 21:
        return prefix + body[:n] + "." + body[n:]
    if -6 < n <= 0:
        return prefix + "0." + "0" * (-n) + body
    exp = n - 1
    exp_part = f"e{'+' if exp >= 0 else '-'}{abs(exp)}"
    if k == 1:
        return prefix + body + exp_part
    return prefix + body[0] + "." + body[1:] + exp_part


def _serialize_number(value: int | float) -> str:
    """Canonical number token for an int or float (bools never reach here)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float is not JSON-serializable: {value!r}")
        # repr() is the shortest round-trip decimal for IEEE-754 doubles.
        return _ecmascript_number(Decimal(repr(value)))
    return _ecmascript_number(Decimal(value))


def canonicalize(value: Any) -> str:
    """Return the JCS canonical form of a JSON-native value.

    Accepts exactly the JSON type lattice: ``None``, ``bool``, ``int``,
    ``float``, ``str``, ``list``, ``dict`` (str keys only).  Anything else —
    ``Decimal``, ``datetime``, custom objects — raises ``TypeError``: the
    hashed surface is the JSON-parsed tool input, and a silently coerced
    non-JSON type would make the hash implementation-defined.
    """
    # bool before int: bool is an int subclass and must serialize as a token.
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _serialize_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonicalize(item) for item in value) + "]"
    if isinstance(value, dict):
        items = []
        for key in sorted(value):
            if not isinstance(key, str):
                raise TypeError(f"JCS object keys must be str, got {type(key).__name__}")
            items.append(f"{json.dumps(key, ensure_ascii=False)}:{canonicalize(value[key])}")
        return "{" + ",".join(items) + "}"
    raise TypeError(f"value of type {type(value).__name__} is not JSON-native")


def state_hash(value: Any) -> str:
    """Return ``sha256(JCS(value))`` as lowercase hex (AM-4-1)."""
    return hashlib.sha256(canonicalize(value).encode("utf-8")).hexdigest()


def compute_received_state_hash(
    *,
    account_id: str,
    market: str,
    account_state: Any,
    fee_model: Any,
    from_date: str,
    to_date: str,
) -> str:
    """Hash the frozen AM-4-1 coverage object (non-order tool inputs).

    ``fee_model`` must be the EFFECTIVE value (see :func:`effective_fee_model`)
    — AM-4-3: the RM dispatch always injects fee_model explicitly, so the hash
    covers every non-order parameter.
    """
    coverage = {
        "account_id": account_id,
        "market": market,
        "account_state": account_state,
        "fee_model": fee_model,
        "from_date": from_date,
        "to_date": to_date,
    }
    return state_hash(coverage)


def effective_fee_model(market: str, fee_model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the fee parameters actually in effect for this run (R7-3 echo).

    Per-key merge of the caller-provided overrides over the market defaults:
    REQUIREMENTS §2.1 defines ``fee_model`` as "key = fee item name, value =
    rate/minimum" overrides.  Unknown markets fail closed — there is no
    silent default fee schedule.
    """
    if market not in _DEFAULT_FEE_MODELS:
        raise ValueError(f"unknown market for fee model: {market!r}")
    return {**_DEFAULT_FEE_MODELS[market], **(fee_model or {})}
