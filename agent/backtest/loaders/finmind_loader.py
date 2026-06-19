"""FinMind loader skeleton for Taiwan markets."""

from __future__ import annotations

import os

from backtest.loaders.registry import register


@register
class DataLoader:
    name = "finmind"
    markets = {"tw_stock", "tw_futures", "tw_options"}
    requires_auth = True

    def is_available(self) -> bool:
        return bool(os.getenv("FINMIND_TOKEN"))

    def fetch(self, codes, start_date, end_date, interval="1D"):
        raise NotImplementedError
