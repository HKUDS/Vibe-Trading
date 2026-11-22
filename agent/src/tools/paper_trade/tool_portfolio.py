"""Stack-owned pt-v2.0 contract and mode-gate helpers for ``paper_trade_step``.

The published discriminated Agent schema (legacy single-market envelope plus
the inlined pt-v2.0 request), the raw ``mode``/``schema_version`` pre-parse
gate, and the pure portfolio document/error serializers live here, split out
of ``tool.py`` to keep each module within the contribution line cap.

Seam discipline: every monkeypatched seam (``parse_request``,
``run_portfolio_step``, ``_default_cn_a_connector``, ``_resolve_clients``,
``run_paper_trade_step``) stays in ``tool.py``, whose dispatch resolves them
as tool-module globals at call time. This module never imports ``tool`` and
calls no patched seam, so the import graph stays acyclic and test patches on
the tool module keep intercepting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .portfolio import wire as portfolio_wire
from .portfolio.orchestrator import OrchestrationCode
from .portfolio.schema import load_portfolio_contract_schema

#: Canonical markets the internal portfolio step can dispatch.
_PORTFOLIO_MARKETS = ("cn_a", "hk", "us")

#: Fields that belong to the legacy single-market request envelope.  The
#: portfolio parser owns the same list, but the tool gate rejects them before
#: any portfolio parser sees a single raw value.
_LEGACY_ONLY_FIELDS = (
    "market",
    "account_state",
    "from_date",
    "to_date",
    "strategy_path",
    "volume_share",
    "order_volume_ratio",
    "path_model",
    "session",
    "fee_model",
)

#: Fields that belong only to the pt-v2.0 portfolio request envelope.  They are
#: rejected when an omitted/``single`` mode call still carries one, while every
#: other unknown key keeps the legacy parser's ignore behavior.
_PORTFOLIO_ONLY_FIELDS = (
    "tool",
    "schema_version",
    "base_currency",
    "trade_date",
    "planning_at",
    "valuation_at",
    "portfolio_state",
    "sessions",
    "fx_snapshots",
    "fx_conversions",
    "target_weights",
    "rebalance_band",
    "benchmark",
    "sectors",
)


#: The legacy single-market request keeps this exact required list.  The
#: portfolio branch below must never inherit it: its own envelope carries the
#: pt-v2.0 required fields instead.
_LEGACY_REQUIRED = (
    "account_id",
    "market",
    "account_state",
    "from_date",
    "to_date",
)

#: Legacy single-market properties, published unchanged since pt-v1.1 except
#: for the optional explicit ``mode=single`` discriminator added by the oneOf.
_LEGACY_PROPERTIES: dict[str, Any] = {
    "account_id": {
        "type": "string",
        "description": "Account identifier, echoed verbatim (R4).",
    },
    "market": {
        "type": "string",
        "enum": ["cn_a", "hk", "us"],
        "description": "Market whose frozen rules govern matching.",
    },
    "account_state": {
        "type": "object",
        "description": (
            "RM-injected ledger snapshot {cash, positions:[{symbol, qty, "
            "avg_cost}]}. Hashed raw for received_state_hash (AM-4-1)."
        ),
        "properties": {
            "cash": {"type": "number"},
            "positions": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["cash"],
    },
    "from_date": {
        "type": "string",
        "description": "Inclusive range start YYYY-MM-DD (orders mode: == to_date, AM-3).",
    },
    "to_date": {
        "type": "string",
        "description": "Inclusive range end YYYY-MM-DD (the target trading day).",
    },
    "orders": {
        "type": "array",
        "description": (
            "Orders mode: array of {symbol, side, qty, limit?}. XOR with "
            "strategy_path; an empty array is the pure-valuation path."
        ),
        "items": {"type": "object"},
    },
    "strategy_path": {
        "type": "string",
        "description": (
            "Strategy mode (Step 7): path to an AST-hardened strategy whose "
            "per-day orders are matched. XOR with orders."
        ),
    },
    "fee_model": {
        "type": "object",
        "description": (
            "Optional per-key fee overrides merged over the market defaults "
            "(AM-4-3: RM always injects it explicitly)."
        ),
    },
    "interval": {
        "type": "string",
        "enum": ["1d", "5m"],
        "default": "1d",
        "description": (
            "Optional pt-v1.2 bar interval. '1d' (default) keeps the pt-v1.1 "
            "daily close-price path; '5m' is cn_a-only and matches the whole "
            "continuous session as one bar (D1)."
        ),
    },
    "session": {
        "type": "string",
        "enum": ["auto", "cn_a"],
        "default": "auto",
        "description": (
            "Optional pt-v1.2 session selector. 'auto' resolves to cn_a for "
            "market=cn_a and is inert for hk/us; 'cn_a' requires market=cn_a (D5)."
        ),
    },
    "path_model": {
        "type": "string",
        "enum": ["bar_median", "bar_close"],
        "default": "bar_median",
        "description": (
            "Optional pt-v1.2 reference-price model for interval='5m': "
            "median(open, high, low, close) or the bar close (D1). Ignored for '1d'."
        ),
    },
    "fill_model": {
        "type": "string",
        "enum": ["all_or_none", "volume_share"],
        "default": "all_or_none",
        "description": (
            "Optional fill model: 'all_or_none' (the default) fills every "
            "order whole or not at all. 'volume_share' opts into pt-v1.3 "
            "per-order partial fills capped by each order's own share of "
            "the matched volume; it requires interval='5m' and market='cn_a'."
        ),
    },
    "order_volume_ratio": {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 1,
        "default": 1.0,
        "description": (
            "Optional pt-v1.3 per-order share of available volume, 0 < r <= 1. "
            "Accepted only together with fill_model='volume_share' (a ratio "
            "without it is INVALID_REQUEST); omitted or null means 1.0, which "
            "does not reduce fills. Each order is capped independently."
        ),
    },
}


def _published_parameters() -> dict[str, Any]:
    """Build the self-contained discriminated Agent schema for one step.

    The legacy branch is the pt-v1.1/v1.2/v1.3 single-market envelope with the
    optional ``mode=single`` discriminator.  The portfolio branch is the
    packaged pt-v2.0 request schema inlined from the single contract source;
    its ``$defs`` are hoisted to this document's root so every local
    ``#/$defs/...`` reference resolves without an external file reference.
    """
    portfolio_request = load_portfolio_contract_schema("request")
    definitions = portfolio_request.pop("$defs", {})
    portfolio_request.pop("$id", None)
    portfolio_request.pop("$schema", None)

    legacy_request = {
        "title": "paper_trade_step legacy single-market request",
        "type": "object",
        "properties": {
            **_LEGACY_PROPERTIES,
            "mode": {
                "type": "string",
                "const": "single",
                "description": (
                    "Optional explicit legacy single-market discriminator; "
                    "omission keeps the legacy default. Portfolio mode selects "
                    "the other oneOf branch."
                ),
            },
        },
        "required": list(_LEGACY_REQUIRED),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "oneOf": [legacy_request, portfolio_request],
        "$defs": definitions,
    }


def _dumps_document(payload: Any) -> str:
    """Serialize one portfolio document/error with the canonical byte spelling."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class _ModeGateError:
    """One stable pre-parse mode rejection."""

    reason: str
    path: str
    detail: str


def _portfolio_error_document(
    code: OrchestrationCode,
    raw_payload: Any,
    *,
    reason: str,
    path: str,
    detail: str,
    bucket_id: str | None = None,
) -> str:
    """Build the structured pt-v2.0 error through the public wire serializer.

    The serializer owns the stable envelope shape and appends the raw-request
    ``input_sha256`` suffix to ``detail``; it also refuses ``INTERNAL`` so an
    engine fault can never become an in-band public code.
    """
    return portfolio_wire.serialize_error(
        raw_payload,
        code=code,
        reason=reason or "invalid_request",
        path=path or "$",
        detail=detail or reason or "invalid request",
        bucket_id=bucket_id,
    )


def _preparse_mode(payload: Any) -> tuple[str, _ModeGateError | None]:
    """Classify one raw payload before either parser runs.

    Returns ``("legacy", None)`` for omitted/``single`` mode,
    ``("portfolio", None)`` for the exact pt-v2.0 pair, or
    ``("error", error)`` for every unsupported combination.
    """
    if not isinstance(payload, dict):
        return "legacy", None
    mode = payload.get("mode")
    schema_version = payload.get("schema_version")
    if mode is None or mode == "single":
        if schema_version == "pt-v2.0":
            return "error", _ModeGateError(
                reason="missing_mode" if mode is None else "invalid_mode",
                path="mode",
                detail="schema_version 'pt-v2.0' requires mode 'portfolio'",
            )
        for field in _PORTFOLIO_ONLY_FIELDS:
            if field in payload:
                return "error", _ModeGateError(
                    reason="portfolio_field_forbidden",
                    path=field,
                    detail=f"portfolio-only field {field!r} is not allowed when mode is 'single'",
                )
        return "legacy", None
    if mode == "portfolio":
        if schema_version != "pt-v2.0":
            return "error", _ModeGateError(
                reason=(
                    "missing_schema_version"
                    if schema_version is None
                    else "invalid_schema_version"
                ),
                path="schema_version",
                detail="mode 'portfolio' requires schema_version 'pt-v2.0'",
            )
        for field in _LEGACY_ONLY_FIELDS:
            if field in payload:
                return "error", _ModeGateError(
                    reason="legacy_field_forbidden",
                    path=field,
                    detail=f"legacy field {field!r} is not allowed in portfolio mode",
                )
        return "portfolio", None
    return "error", _ModeGateError(
        reason="invalid_mode",
        path="mode",
        detail="mode must be 'single' or 'portfolio'",
    )


def _portfolio_markets(raw_payload: Any) -> tuple[str, ...]:
    """Read only the canonical bucket markets a valid request can dispatch."""
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    state = raw.get("portfolio_state")
    buckets = state.get("buckets") if isinstance(state, dict) else None
    markets: list[str] = []
    for bucket in buckets if isinstance(buckets, list) else ():
        market = bucket.get("market") if isinstance(bucket, dict) else None
        if isinstance(market, str) and market in _PORTFOLIO_MARKETS:
            markets.append(market)
    return tuple(dict.fromkeys(markets))
