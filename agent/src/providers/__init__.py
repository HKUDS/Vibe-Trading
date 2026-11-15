"""LLM gateway with lazy SDK loading for metadata-only callers."""
from __future__ import annotations

from typing import Any

__all__ = ["build_llm"]


def __getattr__(name: str) -> Any:
    """Preserve the public factory import without loading SDKs for the catalog."""
    if name == "build_llm":
        from src.providers.llm import build_llm

        return build_llm
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
