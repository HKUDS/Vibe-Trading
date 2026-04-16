"""Web search tool: search the web via DuckDuckGo (free, no API key)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool


class WebSearchTool(BaseTool):
    """Search the web via DuckDuckGo and return top results."""

    name = "web_search"

    @classmethod
    def check_available(cls) -> bool:
        """Available only if ddgs or duckduckgo_search is installed."""
        try:
            try:
                import ddgs  # noqa: F401
            except ImportError:
                import duckduckgo_search  # noqa: F401
            return True
        except ImportError:
            return False
    description = (
        "Search the web via DuckDuckGo. Returns top results with title, URL, "
        "and snippet. Use this to find information, news, or URLs before "
        "reading them with read_url."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Run a DuckDuckGo search.

        Args:
            **kwargs: Must include query; optionally max_results.

        Returns:
            JSON with search results or error.
        """
        query = kwargs["query"]
        max_results = min(int(kwargs.get("max_results", 5)), 10)

        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))

            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]
            return json.dumps(
                {"status": "ok", "query": query, "results": results},
                ensure_ascii=False,
            )
        except ImportError:
            return json.dumps(
                {
                    "status": "error",
                    "error": "DuckDuckGo search package not installed. Run: pip install ddgs",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
            )
