"""Optional hosted search through the SpecStream Search API."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from src.security.scanner import with_security_warnings

_API_URL = "https://api.specstream.ai/v1/web-search"
_TIMEOUT_SECONDS = 10
_MAX_SNIPPET_CHARS = 300
_MAX_QUERY_CHARS = 2000


def search_specstream(query: str, max_results: int, api_key: str) -> dict[str, Any]:
    """Search with the SpecStream Search API and return the web_search envelope.

    Args:
        query: Validated search query.
        max_results: Validated result count, between one and ten.
        api_key: SpecStream API key, sent as a bearer token.

    Returns:
        A success envelope, including security warnings on external content.

    Raises:
        RuntimeError: The request failed or the API returned an error status.
        ValueError: The response does not match the search result contract.
    """
    params = urllib.parse.urlencode({"q": query[:_MAX_QUERY_CHARS], "num": max_results})
    request = urllib.request.Request(
        f"{_API_URL}?{params}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Report the status only; the key never appears in an error message.
        raise RuntimeError(f"SpecStream API returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SpecStream API unreachable: {exc.reason}") from None

    # The API wraps the reply as {"data": {...}}.
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("SpecStream returned an invalid results envelope")

    results = []
    for item in data["sources"][:max_results]:
        if not isinstance(item, dict):
            raise ValueError("SpecStream returned an invalid search result")
        title = item.get("title") or ""
        snippet = item.get("snippet") or ""
        url = item.get("url")
        if (
            not isinstance(title, str)
            or not isinstance(snippet, str)
            or not isinstance(url, str)
            or urlsplit(url).scheme not in {"http", "https"}
            or not urlsplit(url).hostname
        ):
            raise ValueError("SpecStream returned an invalid title, URL, or snippet")
        results.append({"title": title, "url": url, "snippet": snippet})

    payload = with_security_warnings(
        {"status": "ok", "query": query, "backends": "specstream", "results": results},
        fields=("results.*.title", "results.*.snippet"),
    )
    # Scan before truncation so warnings beyond the snippet cutoff survive.
    for item in payload["results"]:
        item["snippet"] = item["snippet"][:_MAX_SNIPPET_CHARS]
    return payload
