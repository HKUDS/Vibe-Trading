"""Shioaji loader skeleton for Taiwan markets."""

from __future__ import annotations

import os
from typing import Final

from backtest.loaders.registry import register

_API_KEY_ENV: Final[str] = "SHIOAJI_API_KEY"
_SECRET_KEY_ENV: Final[str] = "SHIOAJI_SECRET_KEY"


@register
class DataLoader:
    """Shioaji-backed Taiwan market loader skeleton.

    Importing this module must stay safe without credentials or the shioaji SDK
    installed. Authentication and network activity are intentionally deferred.
    """

    name = "shioaji"
    markets = {"tw_stock", "tw_futures", "tw_options"}
    requires_auth = True

    def __init__(self) -> None:
        self._api = None

    def is_available(self) -> bool:
        """Return True only when credentials exist and API object creation succeeds."""
        if not os.getenv(_API_KEY_ENV) or not os.getenv(_SECRET_KEY_ENV):
            return False
        try:
            self._ensure_api()
        except Exception:
            return False
        return True

    def fetch(self, codes, start_date, end_date, interval="1D"):
        """Placeholder fetch implementation for future task work."""
        self._ensure_api()
        raise NotImplementedError

    def _ensure_api(self):
        """Lazily construct a Shioaji API object without logging in."""
        if self._api is None:
            import shioaji as sj  # noqa: PLC0415

            self._api = sj.Shioaji()
        return self._api
