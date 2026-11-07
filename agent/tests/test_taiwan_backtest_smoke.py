"""End-to-end smoke test: backtest runs on Taiwan (TWSE / TPEx) symbols.

Drives the real market-engine routing so a ``2330.TW`` or ``6488.TWO`` backtest
lands on ``TaiwanEquityEngine`` and executes against in-memory NT$ bars. This is
the path the routing tables feed: ``source=auto`` -> ``_MARKET_TO_SOURCE`` ->
yahoo -> ``taiwan_equity``. Without the detection rule the same call silently
produced a ``ChinaAEngine`` (T+1, CNY); without the runner branch it produced a
``CryptoEngine``.

All data is in-memory; no network access. The engine's own rules are covered in
``test_taiwan_equity_engine.py``; this file only proves they are reached.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines._market_hooks import code_currency
from backtest.engines.taiwan_equity import TW_LOT_SIZE, TaiwanEquityEngine
from backtest.runner import _create_market_engine

# Nine sessions rising NT$1 a bar: every move sits well inside the +/-10% band,
# so a limit block cannot be mistaken for a lot-size effect. The two listings
# start at different prices so the lot flooring is not one number's coincidence.
_BASE = {"2330.TW": 590.0, "6488.TWO": 420.0}

_CODES = list(_BASE)


def _bars(code: str) -> pd.DataFrame:
    base = _BASE[code]
    return pd.DataFrame(
        {
            "open": [base + i for i in range(9)],
            "high": [base + i + 3 for i in range(9)],
            "low": [base + i - 3 for i in range(9)],
            "close": [base + i + 1 for i in range(9)],
            "volume": [10_000_000] * 9,
        },
        index=pd.bdate_range("2026-03-02", periods=9),
    )


class _FakeLoader:
    def __init__(self, code: str) -> None:
        self._code = code

    def fetch(self, *args, **kwargs):
        return {self._code: _bars(self._code)}


class _WeightSignal:
    """Replay a fixed target-weight path, one weight per bar."""

    def __init__(self, code: str, weights: list[float]) -> None:
        self._code = code
        self._weights = weights

    def generate(self, data_map):
        return {self._code: pd.Series(self._weights, index=data_map[self._code].index)}


def _config(code: str) -> dict:
    return {
        "codes": [code],
        "start_date": "2026-03-02",
        "end_date": "2026-03-20",
        "source": "auto",
        "initial_cash": 10_000_000,
        "slippage": 0.0,
        # Increases only occur under 'rebalance'; 'hold' never scales in.
        "position_adjustment": "rebalance",
    }


def _run(code: str, weights: list[float], run_dir: Path) -> TaiwanEquityEngine:
    config = _config(code)
    engine = _create_market_engine("auto", config, [code])
    assert isinstance(engine, TaiwanEquityEngine), type(engine)
    engine.run_backtest(config, _FakeLoader(code), _WeightSignal(code, weights), run_dir)
    return engine


@pytest.mark.parametrize("code", _CODES)
def test_taiwan_symbol_runs_on_the_taiwan_engine_and_settles_in_twd(code: str) -> None:
    engine = _create_market_engine("auto", {"initial_cash": 10_000_000}, [code])

    assert isinstance(engine, TaiwanEquityEngine)
    assert code_currency(code) == "TWD"


@pytest.mark.parametrize("code", _CODES)
def test_backtest_completes_on_taiwan_bars(code: str, tmp_path: Path) -> None:
    # Half weight: a fully invested target cannot fund its own commissions
    # once equity drifts, which is BaseEngine behaviour and not under test.
    engine = _run(code, [0.5] * 9, tmp_path)

    assert engine.fill_records
    assert engine.fill_records[0].action == "open"


@pytest.mark.parametrize("code", _CODES)
def test_orders_are_whole_1000_share_lots(code: str, tmp_path: Path) -> None:
    """Open, scale in, and exit: every fill is a whole number of board lots."""
    engine = _run(code, [0.3, 0.3, 0.6, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0], tmp_path)

    actions = [fill.action for fill in engine.fill_records]
    assert actions[0] == "open"
    assert "increase" in actions
    assert actions[-1] == "close"
    for fill in engine.fill_records:
        assert abs(fill.signed_quantity) >= TW_LOT_SIZE
        assert abs(fill.signed_quantity) % TW_LOT_SIZE == 0
