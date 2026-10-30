"""LLM usage accounting extracted from ``src/agent/loop.py``.

Extracted verbatim from ``src/agent/loop.py`` (issue #1624, roadmap item 3:
split ``loop.py`` along its existing seams). This module owns the provider
usage helpers: coercion of reported token counts, normalization of the
provider payload shapes, the run-scoped accumulator, and the atomic write of
``llm_usage.json`` beside a run. ``loop.py`` re-exports every moved name, so
existing imports keep working.

Auxiliary calls share the accumulator, with their purpose recorded separately.
Reported reasoning tokens are retained as a subset of output tokens.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LLM_USAGE_ARTIFACT = "llm_usage.json"


def _coerce_usage_int(value: Any) -> int:
    """Coerce provider token counts to non-negative ints."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_llm_usage(usage: Any) -> dict[str, int] | None:
    """Normalize provider-reported usage metadata without estimating tokens."""
    if usage is None:
        return None
    if not isinstance(usage, dict):
        try:
            usage = dict(usage)
        except (TypeError, ValueError):
            return None

    input_tokens = _coerce_usage_int(usage.get("input_tokens"))
    output_tokens = _coerce_usage_int(usage.get("output_tokens"))
    total_tokens = _coerce_usage_int(usage.get("total_tokens"))
    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    if not (input_tokens or output_tokens or total_tokens):
        return None
    normalized: dict[str, int] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    if "calls" in usage:
        normalized["calls"] = max(1, _coerce_usage_int(usage["calls"]))
    if "context_input_tokens" in usage:
        normalized["context_input_tokens"] = _coerce_usage_int(usage["context_input_tokens"])
    details = usage.get("input_token_details")
    if isinstance(details, dict):
        if details.get("cache_read") is not None:
            normalized["cache_read_tokens"] = _coerce_usage_int(details["cache_read"])
        creation_keys = ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
        if any(details.get(key) is not None for key in creation_keys):
            normalized["cache_creation_tokens"] = sum(
                _coerce_usage_int(details.get(key)) for key in creation_keys
            )
    output_details = usage.get("output_token_details")
    if isinstance(output_details, dict) and output_details.get("reasoning") is not None:
        normalized["reasoning_tokens"] = _coerce_usage_int(output_details["reasoning"])
    return normalized


def _new_llm_usage_summary(llm: Any) -> dict[str, Any]:
    """Create the run-scoped provider usage accumulator."""
    from src.config.accessor import get_env_config
    cfg = get_env_config()
    provider = cfg.llm.langchain_provider.strip() or "openai"
    model = getattr(llm, "model_name", None) or cfg.llm.langchain_model_name.strip()
    return {
        "provider": provider,
        "model": model,
        "totals": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        },
        "per_iteration": [],
    }


def _record_llm_usage(
    run_dir: Path,
    summary: dict[str, Any],
    usage: Any,
    iteration: int,
    *,
    purpose: str | None = None,
) -> dict[str, int] | None:
    """Accumulate and persist one provider-reported usage event."""
    normalized = _normalize_llm_usage(usage)
    if normalized is None:
        return None

    totals = summary.setdefault("totals", {})
    totals["input_tokens"] = int(totals.get("input_tokens") or 0) + normalized["input_tokens"]
    totals["output_tokens"] = int(totals.get("output_tokens") or 0) + normalized["output_tokens"]
    totals["total_tokens"] = int(totals.get("total_tokens") or 0) + normalized["total_tokens"]
    totals["calls"] = int(totals.get("calls") or 0) + normalized.get("calls", 1)
    for key in ("cache_read_tokens", "cache_creation_tokens", "reasoning_tokens"):
        if key in normalized:
            totals[key] = int(totals.get(key) or 0) + normalized[key]
    entry = {"iter": iteration, **normalized}
    if purpose is not None:
        entry["purpose"] = purpose
    summary.setdefault("per_iteration", []).append(entry)
    _write_llm_usage(run_dir, summary)
    return normalized


def _record_unreported_llm_call(run_dir: Path, summary: dict[str, Any]) -> None:
    """Count a call whose provider reported no usage, without inventing tokens.

    Args:
        run_dir: Active run's artifact directory.
        summary: The run's usage summary, updated in place.
    """
    totals = summary.setdefault("totals", {})
    totals["unreported_calls"] = int(totals.get("unreported_calls") or 0) + 1
    _write_llm_usage(run_dir, summary)


def _write_llm_usage(run_dir: Path, summary: dict[str, Any]) -> None:
    """Stamp and atomically persist the usage summary; a write failure is logged."""
    summary["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        path = run_dir / LLM_USAGE_ARTIFACT
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError as exc:
        logger.debug("LLM usage artifact write skipped: %s", exc)
