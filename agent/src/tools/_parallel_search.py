"""Optional hosted search through Parallel's anonymous MCP endpoint."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from src.security.scanner import with_security_warnings

_MCP_URL = "https://mcp.parallel.ai/mcp"
_INIT_TIMEOUT_SECONDS = 5
_TOOL_TIMEOUT_SECONDS = 10
_MAX_SNIPPET_CHARS = 300


def search_parallel(query: str, max_results: int) -> dict[str, Any]:
    """Search anonymously and return the existing web_search result envelope.

    Args:
        query: Validated search query.
        max_results: Validated result count, between one and ten.

    Returns:
        A success envelope, including security warnings on external content.

    Raises:
        RuntimeError: The MCP call failed or returned a tool error.
        ValueError: The response does not match the search result contract.
    """
    # Keep the MCP dependency and connection entirely off the default path.
    from src.config.schema import MCPServerConfig
    from src.tools.mcp import MCPServerAdapter

    adapter = MCPServerAdapter(
        "parallel",
        MCPServerConfig(
            type="streamableHttp",
            url=_MCP_URL,
            init_timeout=_INIT_TIMEOUT_SECONDS,
            tool_timeout=_TOOL_TIMEOUT_SECONDS,
            enabled_tools=["web_search"],
        ),
    )
    response = adapter.call_tool(
        "web_search", {"objective": query, "search_queries": [query]}
    )
    if response.get("status") != "ok":
        raise RuntimeError(response.get("error") or "Parallel MCP call failed")

    data = response.get("data")
    if data is None and response.get("text"):
        data = json.loads(response["text"])
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Parallel returned an invalid results envelope")

    results = []
    for item in data["results"][:max_results]:
        if not isinstance(item, dict):
            raise ValueError("Parallel returned an invalid search result")
        # The v1 search schema allows a missing or null title, but excerpts
        # are a required array. Keep these distinct from malformed values.
        title = item.get("title")
        if title is None:
            title = ""
        url = item.get("url")
        excerpts = item.get("excerpts")
        if (
            not isinstance(title, str)
            or not isinstance(url, str)
            or urlsplit(url).scheme not in {"http", "https"}
            or not urlsplit(url).hostname
            or not isinstance(excerpts, list)
            or not all(isinstance(excerpt, str) for excerpt in excerpts)
        ):
            raise ValueError("Parallel returned invalid title, URL, or excerpts")
        results.append({"title": title, "url": url, "snippet": "\n\n".join(excerpts)})

    payload = with_security_warnings(
        {"status": "ok", "query": query, "backends": "parallel", "results": results},
        fields=("results.*.title", "results.*.snippet"),
    )
    # Scan before truncation so warnings beyond the excerpt cutoff survive.
    for item in payload["results"]:
        item["snippet"] = item["snippet"][:_MAX_SNIPPET_CHARS]
    return payload
