"""Pluggable OCR engine interface and factory.

Allows users to swap between local OCR (RapidOCR) and cloud vision models
(any OpenAI-compatible provider) via environment variable VIBE_TRADING_OCR_ENGINE.

Third-party OCR engines can be installed as pip packages and are automatically
discovered via entry_points (group: vibe_trading.ocr_engines).
"""

from __future__ import annotations

import importlib.metadata
import logging
from functools import lru_cache
from typing import Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "vibe_trading.ocr_engines"

# Built-in engine registry
_BUILTIN_ENGINES: dict[str, type] = {}

# Backward compatibility aliases (Issue #547)
# Old engine names are mapped to new names with a deprecation warning.
# Entries are read from env before engine lookup so existing configs keep working.
_CHOICE_ALIASES: dict[str, str] = {
    "qwen-vl": "llm-vision",  # removed DashScope-locked engine
}


@runtime_checkable
class OcrEngine(Protocol):
    """Abstract OCR engine interface.

    All implementations must accept a numpy RGB image array and return
    extracted text (empty string if no text found).
    """

    name: str
    is_cloud: bool  # auto mode filters on this (privacy red line)
    install_hint: str  # shown when engine is unavailable

    def is_available(self) -> bool:
        """Check if this engine's dependencies are satisfied."""
        ...

    def recognize(self, image: np.ndarray) -> str:
        """Run OCR on a numpy RGB image array. Return extracted text."""
        ...

    def confidence(self, image: np.ndarray) -> float | None:
        """Return OCR confidence (0-1), or None if unsupported. Optional."""
        return None


def register_builtin(name: str, engine_class: type) -> None:
    """Register a built-in OCR engine class (shipped with core)."""
    _BUILTIN_ENGINES[name] = engine_class


@lru_cache(maxsize=1)
def _discover_plugins() -> dict[str, type]:
    """Discover OCR engines installed via pip entry_points.

    Cached per process (Dask pattern). Plugins override built-ins on
    name collision (MLflow pattern).
    """
    plugins: dict[str, type] = {}
    for ep in importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP):
        try:
            engine_class = ep.load()
            plugins[ep.name] = engine_class
        except Exception as exc:
            logger.warning("Failed to load OCR plugin '%s': %s", ep.name, exc)
    return plugins


def _reset_plugin_cache() -> None:
    """Reset the plugin discovery cache. For test isolation only."""
    _discover_plugins.cache_clear()


def _all_engines() -> dict[str, type]:
    """Merge built-in + plugins. Plugins override built-ins on name collision."""
    engines = dict(_BUILTIN_ENGINES)
    engines.update(_discover_plugins())
    return engines


def _get_ocr_choice() -> str:
    """Return the configured OCR engine choice (cached per process)."""
    from src.config.accessor import get_env_config

    return get_env_config().ocr.vibe_trading_ocr_engine.strip().lower()


def _select_first_local(engines: dict[str, type]) -> OcrEngine | None:
    """Return the first available local (non-cloud) engine, sorted by name.

    Instantiates every registered engine to probe :meth:`is_available`, so
    engine ``__init__`` must be cheap (attribute assignment only).  Expensive
    work belongs in :meth:`is_available` or :meth:`recognize` (lazy init).
    Cloud engines (``is_cloud=True``) are skipped — privacy red line.
    """
    for name, cls in sorted(engines.items()):
        try:
            engine = cls()
            if engine.is_available() and not engine.is_cloud:
                return engine
        except Exception:
            continue
    return None


def get_ocr_engine() -> OcrEngine | None:
    """Return the configured OCR engine, or None.

    Engine selection via VIBE_TRADING_OCR_ENGINE:
      - "auto" (default): try all LOCAL (is_cloud=False) engines
      - "<name>": try that specific engine (local or cloud)
      - "none": disable OCR entirely

    Cloud engines are NEVER auto-selected (privacy: pages leave the machine).
    Plugins override built-in engines on name collision.
    """
    choice = _get_ocr_choice()
    # Apply backward compat aliases (Issue #547)
    if choice in _CHOICE_ALIASES:
        new_name = _CHOICE_ALIASES[choice]
        # The qwen-vl → llm-vision rename is not credential-preserving: the old
        # DashScope-locked engine read DASHSCOPE_API_KEY + a fixed DashScope base
        # URL, whereas llm-vision resolves credentials from the configured
        # LANGCHAIN_PROVIDER. Call that out so DashScope users aren't surprised.
        migration = (
            " llm-vision now uses your configured LANGCHAIN_PROVIDER credentials"
            " instead of DASHSCOPE_API_KEY — set LANGCHAIN_PROVIDER/model to a"
            " vision-capable provider (e.g. dashscope) to keep the same backend."
            if choice == "qwen-vl"
            else ""
        )
        logger.warning(
            "OCR engine '%s' is deprecated; use '%s' instead. Alias will be removed in a future release.%s",
            choice,
            new_name,
            migration,
        )
        choice = new_name
    engines = _all_engines()

    if choice == "none":
        return None

    if choice == "auto":
        return _select_first_local(engines)

    # Explicit choice
    cls = engines.get(choice)
    if cls:
        try:
            engine = cls()
            if engine.is_available():
                return engine
        except Exception as exc:
            logger.warning("OCR engine '%s' failed: %s", choice, exc)

    # Unknown engine → fallback to auto
    logger.warning("Unknown OCR engine '%s', falling back to 'auto'", choice)
    return _select_first_local(engines)


def get_ocr_install_hint(engine: OcrEngine | None) -> str:
    """Return an actionable install message for available OCR engines."""
    if engine is not None:
        return ""

    choice = _get_ocr_choice()
    engines = _all_engines()

    # If user explicitly chose an engine but it's unavailable
    if choice != "auto" and choice in engines:
        try:
            e = engines[choice]()
            return e.install_hint
        except Exception:
            pass

    # Read engine metadata from class attributes — no instantiation — to
    # avoid triggering is_available() side effects (e.g. network calls).
    entries = []
    for name, cls in engines.items():
        tag = "[cloud]" if getattr(cls, "is_cloud", False) else "[local]"
        entries.append(f"  {tag:8s} {name}")

    lines = ["OCR engines status:"]
    lines.extend(entries if entries else ["  (no engines registered)"])
    lines.append("")
    lines.append("Install an OCR engine:")
    lines.append("  pip install rapidocr_onnxruntime   # local, no API key")
    lines.append("  # Cloud OCR: set VIBE_TRADING_OCR_ENGINE=llm-vision")
    lines.append("  # and configure a vision-capable LLM model")
    lines.append("")
    lines.append("Or set VIBE_TRADING_OCR_ENGINE=none to disable OCR.")
    return "\n".join(lines)


# Built-in engine self-registration — must stay after definitions above
# because each imported module calls register_builtin() at import time.
from src.tools.ocr import llm_vision_ocr as _llm_vision  # noqa: E402,F401
from src.tools.ocr import rapid_ocr as _rapid  # noqa: E402,F401
