"""Web search tool: search the web via Tavily (API key required)."""

from __future__ import annotations

import json
import os
from typing import Any

from src.agent.tools import BaseTool


class TavilySearchTool(BaseTool):
    """Search the web via the Tavily search API."""

    name = "web_search_tavily"

    @classmethod
    def check_available(cls) -> bool:
        """Available only if the tavily package is installed and an API key is set."""
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return False
        try:
            import tavily  # noqa: F401
            return True
        except ImportError:
            return False

    description = (
        "Search the web via Tavily. Returns top results with title, URL, "
        "snippet, and content. Use this to find information, news, or "
        "research topics. Falls back to web_search (DuckDuckGo) when Tavily "
        "is not configured."
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
        """Run a Tavily search.

        Args:
            **kwargs: Must include query; optionally max_results.

        Returns:
            JSON with search results or error.
        """
        query = kwargs["query"]
        max_results = min(int(kwargs.get("max_results", 5)), 10)
        api_key = os.environ.get("TAVILY_API_KEY", "")

        if not api_key:
            return json.dumps(
                {
                    "status": "error",
                    "error": "TAVILY_API_KEY not set. Add it to agent/.env or your environment.",
                },
                ensure_ascii=False,
            )

        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key)
            response = client.search(query=query, max_results=max_results)

            results = []
            for r in response.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                })

            return json.dumps(
                {"status": "ok", "query": query, "results": results},
                ensure_ascii=False,
            )
        except ImportError:
            return json.dumps(
                {
                    "status": "error",
                    "error": "Tavily package not installed. Run: pip install tavily",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
            )
