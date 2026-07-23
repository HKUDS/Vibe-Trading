"""Internal account-qualified routing for the Weixin adapter."""

from __future__ import annotations

import base64
import re

PRIMARY_ACCOUNT_ID = "primary"
_ROUTE_PREFIX = "weixin-route:v1:"
_ACCOUNT_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def validate_account_alias(value: str) -> str:
    alias = str(value).strip()
    if alias == PRIMARY_ACCOUNT_ID or not _ACCOUNT_ALIAS_RE.fullmatch(alias):
        raise ValueError(
            "Weixin account aliases must match [a-z][a-z0-9_-]{0,31} "
            "and cannot be 'primary'"
        )
    return alias


def encode_aux_route(account_id: str, peer_id: str) -> str:
    alias = validate_account_alias(account_id)
    peer = str(peer_id)
    if not peer or "\x00" in peer:
        raise ValueError("Weixin peer ID must be non-empty and contain no NUL")
    encoded = base64.urlsafe_b64encode(peer.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_ROUTE_PREFIX}{alias}:{encoded}"


def decode_aux_route(value: str) -> tuple[str, str] | None:
    text = str(value)
    if not text.startswith(_ROUTE_PREFIX):
        return None
    remainder = text[len(_ROUTE_PREFIX):]
    alias, separator, encoded = remainder.partition(":")
    if not separator or not encoded:
        raise ValueError("Malformed Weixin auxiliary route")
    alias = validate_account_alias(alias)
    try:
        padding = "=" * (-len(encoded) % 4)
        peer = base64.b64decode(encoded + padding, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Malformed Weixin auxiliary route") from exc
    if not peer or "\x00" in peer:
        raise ValueError("Malformed Weixin auxiliary route")
    return alias, peer
