"""Shared client for the Gildata (恒生聚源) srv-tool MCP endpoint.

The vendor's 标准版 server (``aidata-assistant-srv-tool``) exposes ten
natural-language research tools — macro/industry EDB series, announcement
retrieval, broker-research search, screening and the like. Unlike the raw-api
endpoint the loaders use, every tool takes a free-form ``query`` string the
*agent* authors, which makes these a natural fit for the agent tool layer:
the LLM writes the question, the server routes it, and this client returns
the structured rows plus the ``api_name`` the server actually routed to —
so a mis-routed question is visible to the agent and it can re-ask.

Transport is identical to the loader's raw-api path (JSON-RPC POST, token in
the Authorization header, ``format=json`` for structured rows, the MCP dual
Accept header) but goes through its own throttle bucket: these calls cost
~5s each and belong to research flows, not price fetching.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from backtest.loaders.gildata_loader import _response_results
from backtest.loaders._http import resolve_min_interval, throttled_post_json
from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)

DEFAULT_SRV_TOOL_URL = "https://api.gildata.com/mcp-servers/aidata-assistant-srv-tool"

_HOST_KEY = "gildata-srv"
_MIN_INTERVAL_ENV = "VIBE_TRADING_GILDATA_SRV_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 0.5
_TIMEOUT_S = 60.0


def _url() -> str:
    base = (get_env_config().data.gildata_srv_tool_url or DEFAULT_SRV_TOOL_URL).strip()
    return f"{base}{'&' if '?' in base else '?'}format=json"


def call_srv_tool_results(name: str, query: str, *, timeout: float = _TIMEOUT_S,
                          topk: int | None = None) -> list[dict[str, Any]]:
    """Invoke one srv-tool query, preserving each result table and its metadata.

    Args:
        name: Tool name, e.g. ``"MacroIndustryData"``.
        query: Natural-language question (authored by the agent).
        timeout: Per-request socket timeout; NL research calls are slow.
        topk: Optional vendor-side screening result count.

    Returns:
        The vendor's result tables, without flattening their columns or rows.

    Raises:
        RuntimeError: Token missing, or the vendor answered a non-zero
            business code.
        requests.RequestException: Propagated from the HTTP layer.
        ValueError: Unrecognizable response shape.
    """
    arguments = {"query": query}
    if topk is not None:
        arguments["topk"] = topk
    return _response_results(_call_srv(name, arguments, timeout=timeout))


def _call_srv(name: str, arguments: dict[str, Any], *, timeout: float) -> Any:
    """Share authenticated MCP transport without changing existing table callers."""
    token = get_env_config().data.gildata_token
    if not token:
        raise RuntimeError("GILDATA_TOKEN is not configured")

    # Token rides the Authorization header, never the URL — request
    # exceptions embed the full URL in their message (review of #1474).
    url = _url()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    outer = throttled_post_json(
        url,
        host_key=_HOST_KEY,
        min_interval=resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S),
        json_body=payload,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
        timeout=timeout,
    )

    return outer


def call_srv_arguments(name: str, arguments: dict[str, Any], *, timeout: float = _TIMEOUT_S) -> dict[str, Any]:
    """Preserve analysis status, metadata and asynchronous job IDs."""
    outer = _call_srv(name, arguments, timeout=timeout)
    result = outer.get("result") if isinstance(outer, dict) else None
    if not isinstance(result, dict) or result.get("isError"):
        raise RuntimeError("Gildata analysis failed; check access and parameters")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        raise ValueError("Unsupported analysis envelope")

    def invalid_constant(value):
        raise ValueError("Non-finite analysis data")

    inner = json.loads(content[0].get("text", ""), parse_constant=invalid_constant)
    if not isinstance(inner, dict) or inner.get("error") or inner.get("status") not in {
        "completed", "queued", "pending", "running", "submitted",
    }:
        raise RuntimeError("Gildata analysis unavailable; check access and parameters")
    return inner


def call_srv_tool(name: str, query: str, *, timeout: float = _TIMEOUT_S) -> dict[str, Any]:
    """Return merged rows for the existing macro, announcement and report tools."""
    results = call_srv_tool_results(name, query, timeout=timeout)

    api_names: list[str] = []
    rows: list[dict[str, Any]] = []
    for entry in results:
        if entry.get("api_name"):
            api_names.append(str(entry["api_name"]))
        entry_rows = entry.get("rows")
        if not isinstance(entry_rows, list) or any(not isinstance(row, dict) for row in entry_rows):
            raise ValueError("gildata research response has an unsupported rows shape")
        rows.extend(entry_rows)
    _coerce_numeric_strings(rows)
    return {"api_names": api_names, "rows": rows}


def _coerce_numeric_strings(rows: list[dict[str, Any]]) -> None:
    """Convert numeric-looking ``value`` strings to floats, in place.

    The EDB rows carry their measurement as a string (``"value": "5.4"``).
    The grounding evidence extractor indexes only numeric leaves, so a string
    value never enters the verification pool while the same row's numeric
    ``indicatorcode`` does — every macro figure was then unverifiable
    (measured live: numeric_claim_conflict against the code, degraded release
    with all figures redacted). Coercing the measurement field fixes the pool.
    """
    for row in rows:
        value = row.get("value")
        if isinstance(value, str):
            try:
                number = float(value)
                if math.isfinite(number):
                    row["value"] = number
            except ValueError:
                pass
