"""Random "thinking" verb for the streaming spinner."""

from __future__ import annotations

import random
from typing import Final, Tuple

THINKING_VERBS: Final[Tuple[str, ...]] = (
    "Pondering",
    "Analyzing",
    "Reasoning",
    "Investigating",
    "Synthesizing",
    "Cross-checking",
)


def pick_thinking_verb(*, seed: int | None = None) -> str:
    """Pick a random verb suffixed with an ellipsis."""

    if seed is not None:
        rng = random.Random(seed)
        return f"{rng.choice(THINKING_VERBS)}…"
    return f"{random.choice(THINKING_VERBS)}…"


__all__ = ["pick_thinking_verb", "THINKING_VERBS"]
