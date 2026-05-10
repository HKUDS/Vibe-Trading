"""Vietnam broker journal parser registry.

5 brokers: SSI, HSC, VNDirect, TCBS, DNSE. Each is a sibling module that
self-registers when imported. The dispatcher in trade_journal_parsers.py
delegates to detect_vn_format()/parse_vn() when no existing format matches.

Pattern mirrors backtest.loaders.registry: lazy auto-import on first
detect/parse call, parsers register via register_vn_parser() at import time.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Protocol

import pandas as pd

# Forward-import-safe alias — TradeRecord lives in the parent module.
# We avoid a circular import by deferring to a TYPE_CHECKING block.
if TYPE_CHECKING:
    from src.tools.trade_journal_parsers import TradeRecord  # noqa: F401

logger = logging.getLogger(__name__)


class BrokerParser(Protocol):
    """Contract every VN broker parser module must implement."""

    name: str

    def detect(self, df: pd.DataFrame) -> bool: ...

    def parse(self, df: pd.DataFrame) -> list:  # list[TradeRecord]
        ...


VN_PARSER_REGISTRY: dict[str, BrokerParser] = {}

_registered = False
_BROKER_MODULES = ("ssi", "hsc", "vndirect", "tcbs", "dnse")


def register_vn_parser(parser: BrokerParser) -> None:
    """Called by each broker module at import time."""
    VN_PARSER_REGISTRY[parser.name] = parser


def _ensure_registered() -> None:
    """Lazy-import all broker modules to trigger registration."""
    global _registered
    if _registered:
        return
    _registered = True
    for mod in _BROKER_MODULES:
        try:
            importlib.import_module(f"src.tools.journal_parsers_vn.{mod}")
        except Exception as exc:
            logger.warning("Failed to import VN broker parser %s: %s", mod, exc)


def detect_vn_format(df: pd.DataFrame) -> str | None:
    """Return the broker name whose detect() matches, or None."""
    _ensure_registered()
    for name, parser in VN_PARSER_REGISTRY.items():
        try:
            if parser.detect(df):
                return name
        except Exception as exc:
            logger.debug("Parser %s detect() raised: %s", name, exc)
    return None


def parse_vn(format_name: str, df: pd.DataFrame) -> list:
    """Dispatch to the registered parser for format_name."""
    _ensure_registered()
    if format_name not in VN_PARSER_REGISTRY:
        raise ValueError(f"Unknown VN broker format: {format_name}")
    return VN_PARSER_REGISTRY[format_name].parse(df)


__all__ = [
    "BrokerParser",
    "VN_PARSER_REGISTRY",
    "register_vn_parser",
    "detect_vn_format",
    "parse_vn",
]
