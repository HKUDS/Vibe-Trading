"""Deterministic pre-LLM workflow for candlestick analysis prompts.

Five-step pipeline:
  1. detect_candlestick_intent (Patch 5 detector)
  2. registry.execute("get_market_data", ...)
  3. persist OHLCV in <run_dir>/artifacts/ohlcv_<safe_code>.csv
  4. registry.execute("pattern", {run_dir, patterns:"candlestick", window})
  5. compute verdict ∈ {bullish, bearish, neutral, no_clear_signal}

LLM is never invoked. web_search/read_url are never invoked. Any failure
returns a sanitised error and short-circuits — no fallback, no retry.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.agent.candlestick_intent import (
    CandlestickIntent,
    detect_candlestick_intent,
)
from src.agent.market_data_dispatcher import _sanitize

logger = logging.getLogger(__name__)

_VERDICT_THRESHOLD = 3


def _safe_code(symbol: str) -> str:
    """BTC/USDT -> BTC_USDT; AAPL -> AAPL; 0700.HK -> 0700_HK."""
    return symbol.replace("/", "_").replace("-", "_").replace(".", "_")


def _compute_verdict(counts: Dict[Any, int]) -> str:
    bull = int(counts.get(1, counts.get("1", 0)))
    bear = int(counts.get(-1, counts.get("-1", 0)))
    if bull == 0 and bear == 0:
        return "no_clear_signal"
    if bull - bear >= _VERDICT_THRESHOLD:
        return "bullish"
    if bear - bull >= _VERDICT_THRESHOLD:
        return "bearish"
    return "neutral"


def _render_content(intent: CandlestickIntent, verdict: str,
                    counts: Dict[Any, int], current_price: Any) -> str:
    bull = counts.get(1, counts.get("1", 0))
    bear = counts.get(-1, counts.get("-1", 0))
    neutral = counts.get(0, counts.get("0", 0))
    price_line = (
        f"\nCurrent price: **{current_price}**" if current_price is not None else ""
    )
    return (
        f"**{intent.symbol}** — candlestick analysis "
        f"(timeframe={intent.timeframe}, last={intent.limit} candles, "
        f"window={intent.window}){price_line}\n\n"
        f"Verdict: **{verdict}**\n\n"
        f"| Signal | Count |\n|---|---:|\n"
        f"| bullish | {bull} |\n"
        f"| bearish | {bear} |\n"
        f"| neutral | {neutral} |\n"
    )


def _persist_ohlcv(run_dir: str, code: str, candles: list[dict]) -> Path:
    """Write OHLCV CSV in the shape the pattern tool expects."""
    artifacts = Path(run_dir) / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    csv_path = artifacts / f"ohlcv_{code}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([
                c.get("date", ""), c.get("open", ""), c.get("high", ""),
                c.get("low", ""), c.get("close", ""), c.get("volume", ""),
            ])
    return csv_path


class CandlestickWorkflowDispatcher:
    """Routes candlestick-analysis prompts through a deterministic workflow."""

    ROUTED_BY = "candlestick_workflow"

    def try_route(
        self, user_message: str, registry: Any, trace: Any, run_dir: str,
    ) -> Optional[Dict[str, Any]]:
        intent = detect_candlestick_intent(user_message)
        if intent is None:
            return None

        logger.info(
            "candlestick_intent_detected symbol=%s timeframe=%s limit=%d window=%d",
            intent.symbol, intent.timeframe, intent.limit, intent.window,
        )
        trace.write({
            "type": "router",
            "name": self.ROUTED_BY,
            "intent": {
                "symbol": intent.symbol, "timeframe": intent.timeframe,
                "limit": intent.limit, "window": intent.window,
            },
        })

        md_args = {
            "symbol": intent.symbol,
            "timeframe": intent.timeframe,
            "limit": intent.limit,
        }
        trace.write({"type": "tool_call", "name": "get_market_data",
                     "arguments": md_args, "iter": 0})
        try:
            md_raw = registry.execute("get_market_data", md_args)
            md_payload = json.loads(md_raw)
        except Exception:
            logger.warning("candlestick_workflow get_market_data invoke failed")
            return self._fail(trace, "market data fetch failed.")

        trace.write({"type": "tool_result", "name": "get_market_data",
                     "status": md_payload.get("status", "unknown")})
        if md_payload.get("status") != "ok":
            safe = _sanitize(str(md_payload.get("error", "market data unavailable")))
            return self._fail(trace, f"market data error: {safe}")

        candles = md_payload.get("candles", [])
        if not candles:
            return self._fail(trace, "market data returned empty candles.")

        code = _safe_code(intent.symbol)
        try:
            csv_path = _persist_ohlcv(run_dir, code, candles)
        except Exception:
            logger.warning("candlestick_workflow persist ohlcv failed")
            return self._fail(trace, "failed to persist OHLCV to run dir.")

        trace.write({
            "type": "workflow_step",
            "name": "persist_ohlcv",
            "path_rel": str(csv_path.relative_to(Path(run_dir))),
            "rows": len(candles),
        })

        pattern_args = {
            "run_dir": run_dir,
            "patterns": "candlestick",
            "window": intent.window,
        }
        trace.write({"type": "tool_call", "name": "pattern",
                     "arguments": pattern_args, "iter": 0})
        try:
            pat_raw = registry.execute("pattern", pattern_args)
            pat_payload = json.loads(pat_raw)
        except Exception:
            logger.warning("candlestick_workflow pattern invoke failed")
            return self._fail(trace, "pattern detection failed.")

        trace.write({"type": "tool_result", "name": "pattern",
                     "status": pat_payload.get("status", "unknown")})
        if pat_payload.get("status") != "ok":
            safe = _sanitize(str(pat_payload.get("error", "pattern unavailable")))
            return self._fail(trace, f"pattern error: {safe}")

        results = pat_payload.get("results", {}) or {}
        per_code = results.get(code) or next(iter(results.values()), {})
        counts = (per_code or {}).get("candlestick", {}) if isinstance(per_code, dict) else {}
        if not isinstance(counts, dict):
            counts = {}

        verdict = _compute_verdict(counts)
        content = _render_content(intent, verdict, counts,
                                  md_payload.get("current_price"))

        trace.write({"type": "answer", "iter": 0, "content": content[:2000]})
        trace.write({
            "type": "end", "status": "success", "iterations": 0,
            "routed_by": self.ROUTED_BY, "verdict": verdict,
        })
        return {
            "status": "success", "content": content, "iterations": 0,
            "routed_by": self.ROUTED_BY, "verdict": verdict,
        }

    def _fail(self, trace: Any, message: str) -> Dict[str, Any]:
        safe = _sanitize(message)
        trace.write({"type": "answer", "iter": 0, "content": safe})
        trace.write({
            "type": "end", "status": "failed", "iterations": 0,
            "routed_by": self.ROUTED_BY,
        })
        return {
            "status": "failed", "content": safe, "iterations": 0,
            "routed_by": self.ROUTED_BY,
        }
