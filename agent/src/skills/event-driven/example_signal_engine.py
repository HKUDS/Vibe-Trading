"""Event-driven example signal engine (sentiment pre-filter / long-only).

Companion to ``fundamental-filter/example_signal_engine.py``. It consumes the
point-in-time-safe ``event_score`` column produced by
:func:`backtest.loaders.rsshub_events.enrich_price_frames_with_events` (set
``event_feeds`` in the backtest config) and goes equal-weight long on the names
whose decayed sentiment clears a threshold on each bar.

The ``event_score`` is already look-ahead-safe: for bar ``t`` it only reflects
events knowable on or before ``t``. This engine therefore just reads the column;
it never shifts it forward.
"""

from typing import Dict, List

import numpy as np
import pandas as pd


class SignalEngine:
    """Long-only sentiment pre-filter over the enriched ``event_score`` column.

    Attributes:
        score_threshold: Minimum ``event_score`` for a name to qualify on a bar.
        top_n: Optional cap on the number of names held per bar (highest score
            first); ``None`` holds all qualifiers.
    """

    def __init__(self, score_threshold: float = 0.2, top_n: int | None = None) -> None:
        """Initialise the engine.

        Args:
            score_threshold: Minimum decayed sentiment to qualify (``[-1, 1]``).
            top_n: Max names to hold per bar; ``None`` for unbounded.
        """
        self.score_threshold = score_threshold
        self.top_n = top_n

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Equal-weight long the top-sentiment names on each bar.

        Args:
            data_map: Mapping ``{code: DataFrame}``; each frame must carry an
                ``event_score`` column (enrichment adds it, defaulting to 0.0).

        Returns:
            Mapping ``{code: signal Series}`` aligned to each frame's index.
        """
        codes = list(data_map)
        if not codes:
            return {}

        all_dates = sorted(set().union(*(df.index for df in data_map.values())))
        date_index = pd.DatetimeIndex(all_dates)
        signals: Dict[str, pd.Series] = {code: pd.Series(0.0, index=date_index) for code in codes}

        for dt in date_index:
            scored: List[tuple[str, float]] = []
            for code, df in data_map.items():
                if dt not in df.index:
                    continue
                score = df.loc[dt].get("event_score", np.nan)
                if pd.notna(score) and score >= self.score_threshold:
                    scored.append((code, float(score)))

            if not scored:
                continue
            scored.sort(key=lambda item: item[1], reverse=True)
            if self.top_n is not None:
                scored = scored[: self.top_n]

            weight = 1.0 / len(scored)
            for code, _ in scored:
                signals[code].at[dt] = weight

        return {code: signals[code].reindex(df.index).fillna(0.0) for code, df in data_map.items()}
