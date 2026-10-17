"""Gildata internal-code resolution: recall + exact ref_code match + disk cache.

The vendor's non-A-share quote tools take a 聚源内码 (internal numeric code)
rather than a market symbol, so every HK / CN-index request must first resolve
its symbol through the ``ParamCandidateRecall`` meta-tool. That tool answers a
fuzzy candidate list; this module turns it into a deterministic mapping:

* the candidate whose ``ref_code`` equals the project symbol (normalized,
  ``.SS`` → ``.SH``) is the match — a fuzzy ``caption`` is never trusted;
* successful mappings persist to ``~/.vibe-trading/cache/gildata-codes.json``
  so a symbol costs one recall round-trip per machine, not per fetch;
* an unresolved symbol returns ``None`` so the loader drops it and the
  fallback chain serves it from another source.

The MCP transport is injected (``call_tool``) so this module stays free of
loader imports and unit tests can stub the network entirely.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.config.writer import _write_json_atomically
from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

# recall param -> tool wiring, keyed by the resolution kind.
_RECALL_WIRING: dict[str, tuple[str, str]] = {
    # kind: (api_name, param_name the internal code belongs to)
    "hk_equity": ("HKStockDailyQuotes", "stockObject"),
    "cn_index": ("IndexDailyQuote", "indexObject"),
    # OTC funds: the NetFundUnitValueReport NAV tool (agent-facing, not a
    # loader — the loader protocol is OHLCV bars and NAV series are not).
    "otc_fund": ("NetFundUnitValueReport", "fundObject"),
}

_CACHE_FILENAME = "gildata-codes.json"
_CACHE_MAX_AGE_S = 90 * 24 * 3600  # stale-proof: re-resolve quarterly

_cache_lock = threading.Lock()
_cache_memo: Dict[str, Dict[str, Any]] = {}


def _normalize_ref(code: str) -> str:
    """Upper-case and normalize the .SS variant onto .SH for ref matching."""
    upper = code.strip().upper()
    if upper.endswith(".SS"):
        upper = upper[: -len(".SS")] + ".SH"
    return upper


def _cache_path() -> Path:
    return get_runtime_root() / "cache" / _CACHE_FILENAME


def _load_cache() -> Dict[str, Any]:
    """Read the on-disk code map; any failure yields an empty mapping."""
    try:
        raw = _cache_path().read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(data: Dict[str, Any]) -> None:
    """Persist the code map best-effort; failures only cost a re-resolve."""
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomically(_cache_path(), data)
    except Exception as exc:
        logger.debug("gildata code cache write failed: %s", exc)


def _cached(vendor_code: Optional[str]) -> Dict[str, Any]:
    return {
        "code": vendor_code,
        "resolved_at": time.time(),
    }


def resolve_vendor_code(
    kind: str,
    symbol: str,
    call_tool: Callable[[str, Dict[str, Any]], Any],
) -> Optional[str]:
    """Resolve a project symbol to its Gildata internal code for ``kind``.

    Args:
        kind: Resolution wiring key — ``"hk_equity"`` or ``"cn_index"``.
        symbol: Project symbol, e.g. ``00700.HK`` or ``000300.SH``.
        call_tool: MCP transport — ``call_tool("ParamCandidateRecall", args)``
            must return the recall result's ``candidates`` list.

    Returns:
        The vendor internal code (e.g. ``"1000546"``), or ``None`` when the
        recall answers no candidate whose ``ref_code`` matches exactly.
    """
    wiring = _RECALL_WIRING.get(kind)
    if wiring is None:
        return None
    api_name, param_name = wiring
    want_ref = _normalize_ref(symbol)

    def valid_entry(entry):
        if not isinstance(entry, dict) or entry.get("kind") != kind:
            return False
        age = entry.get("resolved_at")
        code = entry.get("code")
        return (
            isinstance(age, (int, float))
            and not isinstance(age, bool)
            and math.isfinite(age)
            and 0 <= time.time() - age < _CACHE_MAX_AGE_S
            and isinstance(code, str)
            and bool(code.strip())
        )

    with _cache_lock:
        entry = _cache_memo.get(want_ref)
        if valid_entry(entry):
            return entry["code"]

    disk = _load_cache()
    entry = disk.get(want_ref)
    if valid_entry(entry):
        with _cache_lock:
            _cache_memo[want_ref] = dict(entry)
        return entry["code"]

    try:
        arguments = {
            "recall_list": [
                {
                    "api_name": api_name,
                    "keyword": symbol,
                    "param_name": param_name,
                    "top_k": 20,
                }
            ]
        }
        # The recall tool's result puts candidates under results[0]; the
        # injected transport may hand back either that unwrapped entry (the
        # loader's _call_tool does) or the raw recall body — accept both.
        candidates = call_tool("ParamCandidateRecall", arguments)
        if isinstance(candidates, dict):
            if isinstance(candidates.get("candidates"), list):
                candidates = candidates["candidates"]
            else:
                results = candidates.get("results") or []
                candidates = results[0].get("candidates", []) if results else []
    except Exception as exc:
        logger.warning("gildata code recall failed for %s: %s", symbol, exc)
        return None
    if not isinstance(candidates, list):
        return None

    hits = {
        str(candidate["code"]).strip()
        for candidate in candidates
        if isinstance(candidate, dict)
        and _normalize_ref(str(candidate.get("ref_code", ""))) == want_ref
        and isinstance(candidate.get("code"), (str, int))
        and not isinstance(candidate.get("code"), bool)
        and str(candidate["code"]).strip()
    }
    if len(hits) != 1:
        logger.warning("gildata recall has no unique exact ref_code match for %s", symbol)
        return None
    vendor_code = hits.pop()
    record = {"kind": kind, **_cached(vendor_code)}
    with _cache_lock:
        _cache_memo[want_ref] = record
    disk[want_ref] = record
    _save_cache(disk)
    return vendor_code


def reset_code_cache() -> None:
    """Clear the in-process memo (tests; the disk cache stays untouched)."""
    with _cache_lock:
        _cache_memo.clear()
