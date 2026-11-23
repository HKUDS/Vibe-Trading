"""Pure instrument authorization against an execution segment's identity snapshot."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.product.identity.normalize import _normalize_symbol


_SYMBOL_ARGUMENT_KEYS = {
    "code",
    "codes",
    "symbol",
    "symbols",
    "ticker",
    "tickers",
    "underlying",
    "underlyings",
}


@dataclass(frozen=True)
class ToolAuthorization:
    """Deterministic decision made before a tool starts."""

    allowed: bool
    error_code: str | None = None
    message: str | None = None
    symbols: tuple[str, ...] = ()

    def error_payload(self, tool_name: str, identity: Mapping[str, Any]) -> str:
        """Render a blocked tool call as a normal structured error result."""
        return json.dumps(
            {
                "status": "error",
                "error_code": self.error_code or "identity_gate_blocked",
                "tool": tool_name,
                "message": self.message or "Tool call blocked by identity gate",
                "symbols": list(self.symbols),
                "identity": dict(identity),
                "required_action": (
                    "Call search_symbol first and wait for "
                    "its result, then reuse the exact locked symbol and venue. If the "
                    "resolver answers with a shortlist rather than one instrument, "
                    "show the candidates and ask the user which one to use — narrowing "
                    "the query again will not turn a genuine dual listing into one."
                ),
            },
            ensure_ascii=False,
        )


def venue_mismatch_hints(
    requested_symbol: str,
    authorized_symbols: Iterable[str],
) -> list[str]:
    """Turn a same-issuer venue mismatch into an actionable resolver hint.

    ``BLDP.US`` against a locked ``BLDP.TO`` is not a typo of one identity;
    it is a second listing of the same company that was never resolved.
    Naming the exact ``search_symbol`` query keeps the model from retrying
    the identical unauthorized call. A bare ticker that collides with
    several locked venues gets a "use the full suffix" hint instead.
    """
    requested = _normalize_symbol(requested_symbol)
    authorized = {_normalize_symbol(item) for item in authorized_symbols}
    if "." in requested:
        base = requested.rsplit(".", 1)[0]
        same_issuer = sorted(item for item in authorized if "." in item and item.rsplit(".", 1)[0] == base)
        if same_issuer:
            return [
                f"[{requested_symbol} is a second venue of {', '.join(same_issuer)}; "
                f"call search_symbol('{requested_symbol}') before this data call "
                f"before querying it.]"
            ]
        return []
    matches = sorted(item for item in authorized if "." in item and item.rsplit(".", 1)[0] == requested)
    if len(matches) > 1:
        return [
            f"[{requested_symbol} matches multiple locked identities "
            f"({', '.join(matches)}); use the full venue-suffixed symbol.]"
        ]
    return []


def match_authorized_symbol(
    requested_symbol: str,
    authorized_symbols: Iterable[str],
) -> str | None:
    """Map a consumer argument to one unique locked canonical symbol.

    Both sides are canonicalized first, so a provider alias (``600519.SS``),
    an exchange prefix (``sh600519``), an unpadded Hong Kong code
    (``700.HK``) or a slashed pair (``BTC/USDT``) addresses the instrument
    it names rather than being read as a silent venue rewrite.

    A bare code carries no venue, so it is accepted only when exactly one
    locked identity has it as its base. That uniqueness — not a list of
    which tools are allowed to use one — is what makes a bare ticker safe.
    The list this replaced named nine tools while eleven documented
    argument spellings across the registry were bare or prefixed, so the
    tools' own schema examples were being rejected.

    Args:
        requested_symbol: Model-supplied symbol argument.
        authorized_symbols: Symbols locked before the tool batch.

    Returns:
        The unique canonical identity consumed by the argument, or ``None``.
    """
    requested = _normalize_symbol(requested_symbol)
    authorized = {_normalize_symbol(item) for item in authorized_symbols}
    if requested in authorized:
        return requested
    if "." in requested:
        return None
    matches = [symbol for symbol in authorized if "." in symbol and symbol.rsplit(".", 1)[0] == requested]
    return matches[0] if len(matches) == 1 else None

def extract_symbol_arguments(arguments: Mapping[str, Any]) -> list[str]:
    """Extract model-selected identities from well-known argument keys."""
    symbols: list[str] = []
    for key, value in arguments.items():
        if str(key).casefold() not in _SYMBOL_ARGUMENT_KEYS:
            continue
        values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
        for item in values:
            if not isinstance(item, (str, int)):
                continue
            symbol = _normalize_symbol(item)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def authorize_symbols(
    symbols: tuple[str, ...],
    authorized: set[str],
    identity_status: str,
) -> ToolAuthorization:
    """Authorize model-selected symbols using the pre-segment snapshot."""
    if identity_status != "locked" or not authorized:
        return ToolAuthorization(
            allowed=False,
            error_code=(
                "identity_conflict"
                if identity_status in {"ambiguous", "conflicting", "invalidated"}
                else "identity_required"
            ),
            message=(
                "A canonical, non-conflicting identity has not been resolved for this "
                "call. Resolve the instrument before requesting its data."
            ),
            symbols=symbols,
        )

    mismatched = tuple(symbol for symbol in symbols if match_authorized_symbol(symbol, authorized) is None)
    if mismatched:
        message = (
            "Consumer symbol/venue differs from the locked resolver identity; "
            "silent suffix or exchange rewrites are forbidden."
        )
        hints = [hint for symbol in mismatched for hint in venue_mismatch_hints(symbol, authorized)]
        if hints:
            message += " " + " ".join(hints)
        return ToolAuthorization(
            allowed=False,
            error_code="identity_mismatch",
            message=message,
            symbols=mismatched,
        )
    return ToolAuthorization(allowed=True, symbols=symbols)
