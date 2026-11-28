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
        """Render a blocked tool call as a normal structured error result.

        Args:
            tool_name: Name of the blocked consumer tool.
            identity: Ledger summary to include in the error.

        Returns:
            A JSON error with the decision, affected symbols, and resolver guidance.
        """
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

    Args:
        requested_symbol: Model-supplied symbol to compare with the locked venues.
        authorized_symbols: Symbols already locked for use.

    Returns:
        Guidance to resolve a second listing or disambiguate a bare ticker, or an
        empty list when neither case applies.
    """
    requested = _normalize_symbol(requested_symbol)
    authorized = {_normalize_symbol(item) for item in authorized_symbols}
    base, separator, _ = requested.rpartition(".")
    matches = sorted(_matching_listings(base if separator else requested, authorized))
    if separator and matches:
        return [
            f"[{requested_symbol} is a second venue of {', '.join(matches)}; "
            f"call search_symbol('{requested_symbol}') before this data call "
            f"before querying it.]"
        ]
    if not separator and len(matches) > 1:
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

    Both sides are canonicalized first. A bare code carries no venue, so it
    is accepted only when exactly one locked identity has it as its base.

    Args:
        requested_symbol: Model-supplied symbol argument.
        authorized_symbols: Symbols locked before the tool batch.

    Returns:
        The unique canonical identity consumed by the argument, or None.
    """
    requested = _normalize_symbol(requested_symbol)
    authorized = {_normalize_symbol(item) for item in authorized_symbols}
    if requested in authorized:
        return requested
    if "." in requested:
        return None
    matches = _matching_listings(requested, authorized)
    return matches[0] if len(matches) == 1 else None


def _matching_listings(base: str, symbols: Iterable[str]) -> list[str]:
    return [symbol for symbol in symbols if "." in symbol and symbol.rsplit(".", 1)[0] == base]


def extract_symbol_arguments(arguments: Mapping[str, Any]) -> list[str]:
    """Extract model-selected identities from well-known argument keys.

    Args:
        arguments: Tool arguments whose recognized keys may hold symbols or collections.

    Returns:
        Deduplicated, normalized symbols in encounter order.
    """
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
    """Authorize model-selected symbols using the pre-segment snapshot.

    Args:
        symbols: Symbols requested in the consumer call.
        authorized: Canonical symbols locked before this execution segment.
        identity_status: Aggregate ledger status from the same snapshot.

    Returns:
        An allow decision when every symbol matches a lock, or a refusal explaining
        the missing, conflicting, or mismatched identity.
    """
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
