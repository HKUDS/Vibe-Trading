"""MCP web, document, and sandboxed file-I/O tools."""

from __future__ import annotations

from fastmcp import FastMCP

from src.mcp_tools._shared import get_registry


def read_url(url: str) -> str:
    """Fetch a web page and convert it to clean Markdown text.

    Strips ads, navigation, and styling. Useful for reading API docs,
    financial articles, research reports, and GitHub READMEs.

    Args:
        url: Target URL to read.
    """
    from src.tools.web_reader_tool import read_url as _read_url

    return _read_url(url)


def read_document(file_path: str) -> str:
    """Extract text from a PDF document with OCR fallback for scanned pages.

    Supports text-based and image-based PDFs. Automatically uses OCR
    for pages with insufficient extractable text.

    Args:
        file_path: Absolute path to the PDF file.
    """
    registry = get_registry()
    return registry.execute("read_document", {"file_path": file_path})


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo and return top results.

    Returns titles, URLs, and snippets. Use read_url() to fetch full content
    from any result URL. Free, no API key required.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default 5, max 10).
    """
    registry = get_registry()
    return registry.execute(
        "web_search",
        {
            "query": query,
            "max_results": min(max_results, 10),
        },
    )


def write_file(path: str, content: str) -> str:
    """Write content to a file. Used to create config.json and signal_engine.py
    for backtesting workflows.

    Args:
        path: File path (relative to workspace or absolute).
        content: File content to write.
    """
    registry = get_registry()
    return registry.execute("write_file", {"path": path, "content": content})


def read_file(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: File path to read.
    """
    registry = get_registry()
    return registry.execute("read_file", {"path": path})


def register(mcp: FastMCP) -> None:
    """Register the web / document / file tools with the FastMCP instance."""
    mcp.tool()(read_url)
    mcp.tool()(read_document)
    mcp.tool()(web_search)
    mcp.tool()(write_file)
    mcp.tool()(read_file)
