"""D3 gate — the 1d ``bar_fingerprint`` covers the served day bars.

Before this change ``data.fetch_market_data`` hard-coded ``bar_fingerprint=""``
for ``interval="1d"``, so two different days (or two different price tapes)
shared one ``engine_fingerprint``.  The fingerprint is an audit field only: it
never changes matching, and the pt-v1.1 wire document still does not carry it.

Offline: no network, no clock, no writes.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.tool import run_paper_trade_step

_DAY_A = "2026-10-19"
_DAY_B = "2026-10-20"
_SYM = "AAPL.US"


def _frame(rows: Iterable[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {
            "trade_date": pd.Timestamp(day),
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        }
        for day, close in rows
    ]
    return pd.DataFrame(records).set_index("trade_date")


class _Loader:
    name = "fixture"

    def __init__(self, frames: Mapping[str, pd.DataFrame]) -> None:
        self.frames = dict(frames)
        self.calls: list[tuple[tuple[str, ...], str, str, str]] = []

    def is_available(self) -> bool:
        return True

    def fetch(
        self,
        codes: Iterable[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Sequence[str] | None = None,
    ) -> Mapping[str, pd.DataFrame]:
        self.calls.append((tuple(str(code) for code in codes), start_date, end_date, str(interval)))
        return {code: self.frames[code] for code in codes if code in self.frames}


def _fetch(day: str, close: float):
    loader = _Loader({_SYM: _frame([("2026-10-16", 100.0), (day, close)])})
    return fetch_market_data("us", [_SYM], day, day, loader=loader)


def test_different_days_and_prices_produce_different_fingerprints() -> None:
    first = _fetch(_DAY_A, 101.0)
    second = _fetch(_DAY_B, 101.0)
    repriced = _fetch(_DAY_A, 102.0)

    assert len(first.bar_fingerprint) == 64
    assert first.bar_fingerprint != second.bar_fingerprint
    assert first.bar_fingerprint != repriced.bar_fingerprint


def test_the_same_served_tape_hashes_identically_twice() -> None:
    first = _fetch(_DAY_A, 101.0)
    second = _fetch(_DAY_A, 101.0)

    assert first.bar_fingerprint == second.bar_fingerprint


def test_a_v1_1_document_still_has_no_engine_fingerprint() -> None:
    loader = _Loader({_SYM: _frame([("2026-10-16", 100.0), (_DAY_B, 101.0)])})
    payload: dict[str, Any] = {
        "account_id": "pa_1d_fingerprint",
        "market": "us",
        "account_state": {"cash": 100_000.0, "positions": []},
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 10}],
        "from_date": _DAY_B,
        "to_date": _DAY_B,
    }

    document = json.loads(
        run_paper_trade_step(payload, loader=loader, ch_client=None, calendar_client=None, limits_client=None)
    )

    assert document["schema_version"] == "pt-v1.1"
    assert "engine_fingerprint" not in document
    assert [fill["symbol"] for fill in document["fills"]] == [_SYM]
