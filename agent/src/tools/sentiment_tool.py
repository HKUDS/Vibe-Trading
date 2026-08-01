"""Read-only market sentiment analysis tool.

Two capabilities:
1. ``sentiment_score`` — score arbitrary text [-1, 1] with a lexicon-based scorer
2. ``fear_greed_index`` — fetch the current crypto Fear & Greed Index

All computation is pure Python; the Fear & Greed call is a single HTTP GET
to the free, no-auth alternative.me API.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# ── Lexicon (subset, extensible) ─────────────────────────────────────────────
_POSITIVE: frozenset[str] = frozenset({
    "beat", "beats", "bullish", "buy", "cheap", "crush", "crushed",
    "crushing", "gain", "gained", "gaining", "gains", "green",
    "growth", "high", "higher", "hit", "improve", "improved",
    "jump", "jumped", "lead", "leading", "leads", "long", "low",
    "opportunity", "outperform", "outperformed", "profit", "profitable",
    "profits", "raise", "raised", "raises", "rally", "rallied",
    "rebound", "record", "rise", "rises", "rising", "rose",
    "strong", "stronger", "surge", "surged", "surges", "top",
    "undervalued", "up", "upgrade", "upgraded", "upside", "win",
})

_NEGATIVE: frozenset[str] = frozenset({
    "bearish", "bleed", "bottom", "bust", "crash", "crashed",
    "cut", "cuts", "cutting", "decline", "declined", "declining",
    "deficit", "downgrade", "downgraded", "downside", "drop", "dropped",
    "dropping", "fall", "falling", "fell", "fined", "firing",
    "frozen", "headwind", "headwinds", "investigation",
    "lawsuit", "layoff", "layoffs", "litigation", "lose", "loses",
    "losing", "loss", "losses", "low", "lower", "lowered",
    "miss", "missed", "missing", "negative", "overvalued", "penalty",
    "plunge", "plunged", "poor", "probe", "recall", "red",
    "risk", "risks", "sanction", "scandal", "sell", "selling",
    "short", "shrink", "sliding", "slump", "slumped", "turmoil",
    "underperform", "volatile", "volatility", "warn", "warned", "warns", "warning",
    "weak", "weaker", "worry", "worries", "worse", "worst",
})


def _tokenize(text: str) -> list[str]:
    """Lowercase, split, and strip common punctuation from each token."""
    stripped = [tok.strip(".,;:!?\"'()[]{}") for tok in text.split()]
    return [tok.lower() for tok in stripped if tok and tok.isalpha()]


def _score_text(text: str) -> dict[str, Any]:
    """Score one text snippet in [-1, 1].

    Returns a dict with ``score`` (float), ``positive`` (int), and ``negative`` (int).
    """
    tokens = _tokenize(text)
    if not tokens:
        return {"score": 0.0, "positive": 0, "negative": 0}
    pos = sum(1 for t in tokens if t in _POSITIVE)
    neg = sum(1 for t in tokens if t in _NEGATIVE)
    hits = pos + neg
    if hits == 0:
        return {"score": 0.0, "positive": 0, "negative": 0}
    return {"score": round((pos - neg) / hits, 4), "positive": pos, "negative": neg}


def _fetch_fear_greed() -> dict[str, Any] | None:
    """Fetch the latest crypto Fear & Greed Index from alternative.me."""
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Vibe-Trading/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:
        logger.debug("Fear & Greed fetch failed: %s", exc)
        return None
    data = body.get("data", [])
    if not data:
        return None
    item = data[0]
    return {
        "value": int(item.get("value", 0)),
        "classification": item.get("value_classification", "unknown"),
    }


class SentimentTool(BaseTool):
    """Analyze market sentiment from text and external indices.

    Two modes:
    - ``sentiment_score``: score any free-text (news headline, tweet, etc.) on [-1, 1]
    - ``fear_greed_index``: fetch the crypto Fear & Greed Index (0-100, lower = more fear)
    """

    name = "sentiment"
    description = (
        "Analyze market sentiment. Two modes: (1) 'sentiment_score' scores "
        "arbitrary text on -1 (bearish) to 1 (bullish); (2) 'fear_greed_index' "
        "returns the crypto Fear & Greed Index (0-100, lower = more fear). "
        'Example: {"mode": "sentiment_score", "text": "Tesla beats earnings estimates"}'
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["sentiment_score", "fear_greed_index"],
                "description": (
                    "'sentiment_score' to score text; "
                    "'fear_greed_index' for the crypto F&G index."
                ),
            },
            "text": {
                "type": "string",
                "description": "Text to analyze (required when mode='sentiment_score').",
            },
        },
        "required": ["mode"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        mode = str(kwargs.get("mode", "")).strip()

        if mode == "fear_greed_index":
            fg = _fetch_fear_greed()
            if fg is None:
                return json.dumps({"ok": False, "error": "Failed to fetch Fear & Greed Index"})
            return json.dumps({"ok": True, "mode": mode, **fg})

        if mode == "sentiment_score":
            text = str(kwargs.get("text", "")).strip()
            if not text:
                return json.dumps({"ok": False, "error": "text is required for mode 'sentiment_score'"})
            result = _score_text(text)
            return json.dumps({"ok": True, "mode": mode, "text": text[:500], **result})

        return json.dumps({"ok": False, "error": f"Unknown mode: {mode!r}"})
