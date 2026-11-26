"""Size compaction from the model window, measured input, and static prompt."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "providers" / "context_windows.json"

#: Share of the window a prompt may use; the rest is left for the reply,
#: reasoning tokens and the error of estimating growth between calls.
USABLE_FRACTION = 0.8
#: Layer 1 (clear old tool results, oldest first, only back down to this line)
#: and layer 2 (fold long text) start at these shares of the conversation
#: budget; layer 3 (summary) at all of it. Calibrated so the largest healthy
#: run measured on 2026-09-29 (154K real input, ~48K of it static) loses
#: nothing: with the 200K cost cap, layer 1 starts at ~170K.
MICRO_FRACTION = 0.8
COLLAPSE_FRACTION = 0.9
#: Floor for the conversation budget when the static prompt nearly fills the
#: window, so a tiny window still compacts instead of computing a negative.
#: Every layer's line is still capped at ``CompactionBudget.total``: the floor
#: must not lift a line past the prompt the run may grow to.
MIN_CONVERSATION_TOKENS = 8_000

_LIMIT_RE = re.compile(
    r"(?:maximum context length|context length|context window|token limit|maximum of)"
    r"\D{0,40}?(\d[\d,]{3,})",
    re.IGNORECASE,
)
_warned_token_threshold = False


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def estimate_tokens(value: Any) -> int:
    """Estimate tokens from the JSON representation of a value.

    Args:
        value: Value to serialize, with unsupported objects converted to strings.

    Returns:
        One token per four serialized characters, rounded down.
    """
    return len(json.dumps(value, default=str, ensure_ascii=False)) // 4


def resolve_window(
    provider: str,
    model: str,
    *,
    env_window: Optional[int] = None,
    learned_window: Optional[int] = None,
) -> tuple[int, str]:
    """Return the model's context window and where the number came from.

    Args:
        provider: Provider name, normalized to the catalog spelling.
        model: Model name as configured.
        env_window: Explicit window override, when set.
        learned_window: Limit read from a context-length error in this run.

    Returns:
        A pair of the window in tokens and its source label, using the override, learned limit,
        catalog match, or default in that order.
    """
    _warn_deprecated_token_threshold()
    if env_window:
        return int(env_window), "env:VIBE_TRADING_CONTEXT_WINDOW"
    if learned_window:
        return int(learned_window), "learned:context_length_error"
    catalog = _catalog()
    # Provider/model labels arrive from different adapters with either hyphens
    # or underscores.  Catalog patterns use the canonical hyphenated spelling.
    provider = (provider or "").strip().lower().replace("_", "-")
    model = (model or "").strip().replace("_", "-")
    for entry in catalog["models"]:
        if entry.get("provider") and entry["provider"] != provider:
            continue
        if re.search(entry["pattern"], model, re.IGNORECASE):
            return int(entry["window"]), f"catalog:{entry['pattern']}"
    return int(catalog["default_window"]), "default"


def _warn_deprecated_token_threshold() -> None:
    global _warned_token_threshold
    if _warned_token_threshold or "TOKEN_THRESHOLD" not in os.environ:
        return
    _warned_token_threshold = True
    logger.warning(
        "TOKEN_THRESHOLD is deprecated and ignored: it measured chars/4 of the "
        "messages without tool schemas. Compaction now follows the model's real "
        "context window; set VIBE_TRADING_CONTEXT_WINDOW to override it."
    )


def is_context_overflow(error_text: str) -> bool:
    """Recognize provider errors that report context-window overflow.

    Args:
        error_text: Provider error text to match case-insensitively.

    Returns:
        True if the text contains a catalogued overflow pattern.
    """
    lowered = (error_text or "").lower()
    return any(pattern in lowered for pattern in _catalog()["overflow_error_patterns"])


def parse_context_limit(error_text: str) -> Optional[int]:
    """Read the context limit a provider states in its overflow error, if any.

    Args:
        error_text: Provider error text that may report a context limit.

    Returns:
        The parsed limit in tokens if it is at least 1,000, or None.
    """
    match = _LIMIT_RE.search(error_text or "")
    if not match:
        return None
    value = int(match.group(1).replace(",", ""))
    return value if value >= 1_000 else None


@dataclass(frozen=True)
class CompactionBudget:
    """Real-token thresholds for the three compaction layers."""

    window: int
    source: str
    max_tokens: int
    static_tokens: int

    @property
    def total(self) -> int:
        """Largest prompt, in real tokens, the loop lets a run grow to.

        Returns:
            The smaller of the usable portion of the model window and the configured token cap.
        """
        return min(int(self.window * USABLE_FRACTION), self.max_tokens)

    @property
    def conversation(self) -> int:
        """Tokens left for the conversation after the static prompt.

        Returns:
            The prompt budget minus static tokens, floored at the minimum conversation allowance.
        """
        return max(self.total - self.static_tokens, MIN_CONVERSATION_TOKENS)

    @property
    def micro_at(self) -> int:
        """Return the prompt size that triggers microcompaction.

        Returns:
            The static tokens plus the microcompaction fraction of the conversation budget, capped
            at the total budget.
        """
        return min(self.static_tokens + int(self.conversation * MICRO_FRACTION), self.total)

    @property
    def collapse_at(self) -> int:
        """Return the prompt size that triggers conversation collapse.

        Returns:
            The static tokens plus the collapse fraction of the conversation budget, capped at the
            total budget.
        """
        return min(self.static_tokens + int(self.conversation * COLLAPSE_FRACTION), self.total)

    @property
    def compact_at(self) -> int:
        """Return the prompt size that triggers summarization.

        Returns:
            The static tokens plus the full conversation budget, capped at the total budget.
        """
        return min(self.static_tokens + self.conversation, self.total)


class ContextMeter:
    """Current prompt size in real tokens.

    Args:
        estimator: Function that estimates tokens in messages or other prompt data.
    """

    def __init__(self, estimator: Callable[[Any], int] = estimate_tokens) -> None:
        self._estimate = estimator
        self._anchor: Optional[tuple[int, int]] = None
        self.static_tokens: Optional[int] = None
        self._anchor_schema_tokens: Optional[int] = None
        self._static_schema_tokens: Optional[int] = None

    def observe(self, input_tokens: Optional[int], messages: list, *, tool_schema_tokens: Optional[int] = None) -> None:
        """Anchor on the real input size of the request just answered.

        Args:
            input_tokens: Provider-reported prompt tokens of that request. Only positive integers
                establish an anchor.
            messages: Exactly the messages that request sent.
            tool_schema_tokens: Estimate of the schemas sent with that request, if known.
        """
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool) or input_tokens <= 0:
            return
        self._anchor = (input_tokens, self._estimate(messages))
        self._anchor_schema_tokens = tool_schema_tokens
        if self.static_tokens is None:
            # The first request is the static prompt plus the opening turn(s).
            self.static_tokens = max(0, input_tokens - self._estimate(messages[1:]))
            self._static_schema_tokens = tool_schema_tokens

    def tokens(self, messages: list, tool_schema_tokens: int) -> int:
        """Estimate the next request's input tokens.

        Args:
            messages: Messages to include in the next request.
            tool_schema_tokens: Estimated tokens in the current tool schemas.

        Returns:
            The last measured input plus estimated changes, or an estimate of the full request
            before the first measurement.
        """
        if self._anchor is None:
            return self._estimate(messages) + tool_schema_tokens
        anchor_input, anchor_estimate = self._anchor
        schema_delta = 0 if self._anchor_schema_tokens is None else tool_schema_tokens - self._anchor_schema_tokens
        return max(0, anchor_input + self._estimate(messages) - anchor_estimate + schema_delta)

    def static(self, messages: list, tool_schema_tokens: int) -> int:
        """Estimate the static prompt size for the current schemas.

        Args:
            messages: Current messages, whose first entry is the system prompt.
            tool_schema_tokens: Estimated tokens in the current tool schemas.

        Returns:
            The measured static size adjusted for schema changes, or the estimated system prompt
            plus schemas.
        """
        if self.static_tokens is not None:
            schema_delta = 0 if self._static_schema_tokens is None else tool_schema_tokens - self._static_schema_tokens
            return max(0, self.static_tokens + schema_delta)
        return self._estimate(messages[:1]) + tool_schema_tokens
