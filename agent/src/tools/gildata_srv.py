"""Shared client for the Gildata (恒生聚源) srv-tool MCP endpoint.

The vendor's 标准版 server (``aidata-assistant-srv-tool``) exposes ten
natural-language research tools — macro/industry EDB series, announcement
retrieval, broker-research search, screening and the like. Unlike the raw-api
endpoint the loaders use, every tool takes a free-form ``query`` string the
*agent* authors, which makes these a natural fit for the agent tool layer:
the LLM writes the question, the server routes it, and this client returns
the structured rows plus the ``api_name`` the server actually routed to —
so a mis-routed question is visible to the agent and it can re-ask.

Transport is identical to the loader's raw-api path (JSON-RPC POST, token on
the URL query string, ``format=json`` for structured rows, the MCP dual
Accept header) but goes through its own throttle bucket: these calls cost
~5s each and belong to research flows, not price fetching.
"""

from __future__ import annotations

import logging
from typing import Any

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


def call_srv_tool(
    name: str, query: str, *, timeout: float = _TIMEOUT_S
) -> dict[str, Any]:
    """Invoke one srv-tool NL tool and return its merged structured payload.

    Args:
        name: Tool name, e.g. ``"MacroIndustryData"``.
        query: Natural-language question (authored by the agent).
        timeout: Per-request socket timeout; NL research calls are slow.

    Returns:
        ``{"api_names": [...], "rows": [...]}`` — rows of every result entry
        concatenated, with the routed ``api_names`` surfaced for the agent.

    Raises:
        RuntimeError: Token missing, or the vendor answered a non-zero
            business code.
        requests.RequestException: Propagated from the HTTP layer.
        ValueError: Unrecognizable response shape.
    """
    token = get_env_config().data.gildata_token
    if not token:
        raise RuntimeError("GILDATA_TOKEN is not configured")

    url = f"{_url()}&token={token}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": {"query": query}},
    }
    outer = throttled_post_json(
        url,
        host_key=_HOST_KEY,
        min_interval=resolve_min_interval(
            _MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S
        ),
        json_body=payload,
        headers={"Accept": "application/json, text/event-stream"},
        timeout=timeout,
    )

    result = outer.get("result") if isinstance(outer, dict) else None
    if result is None:
        message = outer.get("message") if isinstance(outer, dict) else None
        raise RuntimeError(f"gildata srv-tool call failed: {message or outer!r}")
    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        raise ValueError(f"gildata srv-tool response has no content: {outer!r}")
    text = content[0].get("text")
    if not isinstance(text, str):
        raise ValueError(f"gildata srv-tool content is not text: {content[0]!r}")

    import json

    inner = json.loads(text)
    if not isinstance(inner, dict) or inner.get("code") not in (0, "0"):
        raise RuntimeError(
            f"gildata srv-tool {name} returned error: {str(inner)[:200]}"
        )

    api_names: list[str] = []
    rows: list[dict[str, Any]] = []
    for entry in inner.get("results") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("api_name"):
            api_names.append(str(entry["api_name"]))
        entry_rows = entry.get("rows")
        if isinstance(entry_rows, list):
            rows.extend(r for r in entry_rows if isinstance(r, dict))
    return {"api_names": api_names, "rows": rows}
