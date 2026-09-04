"""End-to-end smoke test: backtest runs on UK (LSE) symbols.

Drives the real market-engine routing so a ``VOD.L`` backtest lands on
``GlobalEquityEngine(market="uk")`` and executes against in-memory LSE-style
bars. This is the path the routing tables feed: ``source=auto`` ->
``_MARKET_TO_SOURCE`` -> yahoo -> GlobalEquity, submarket ``uk``. Without the
``uk_equity`` entries the same call silently produced a CryptoEngine (the
regression this guards).

All data is in-memory; no network access. The loader contract normalizes LSE
GBp prices to GBP before the engine, so the synthetic series uses pound-scale
prices and whole-share sizes. Buys carry the statutory 0.5% SDRT (rounded to
the nearest penny, exact ½p up).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.runner import _create_market_engine

CODE = "VOD.L"

_BARS = pd.DataFrame(
    {
        "open": [1.10 + 0.02 * i for i in range(9)],
        "high": [1.12 + 0.02 * i for i in range(9)],
        "low": [1.08 + 0.02 * i for i in range(9)],
        "close": [1.11 + 0.02 * i for i in range(9)],
        "volume": [1_000_000] * 9,
    },
    index=pd.bdate_range("2026-03-02", periods=9),
)


class _FakeLoader:
    def fetch(self, *args, **kwargs):
        return {CODE: _BARS.copy()}


class _WeightSignal:
    """Replay a fixed target-weight path, one weight per bar."""

    def __init__(self, weights: list[float]) -> None:
        self._weights = weights

    def generate(self, data_map):
        return {CODE: pd.Series(self._weights, index=data_map[CODE].index)}


def _run(weights: list[float], run_dir: Path) -> GlobalEquityEngine:
    config = {
        "codes": [CODE],
        "start_date": "2026-03-02",
        "end_date": "2026-03-20",
        "source": "auto",
        "initial_cash": 1_000_000,
        "slippage": 0.0,
        "position_adjustment": "rebalance",
    }
    engine = _create_market_engine("auto", config, [CODE])
    assert isinstance(engine, GlobalEquityEngine), type(engine)
    engine.run_backtest(config, _FakeLoader(), _WeightSignal(weights), run_dir)
    return engine


def test_uk_routes_to_global_equity_engine() -> None:
    engine = _create_market_engine("auto", {"initial_cash": 100_000}, [CODE])
    assert isinstance(engine, GlobalEquityEngine)
    assert engine.market == "uk"


def test_backtest_completes_on_lse_bars(tmp_path: Path) -> None:
    # Half weight: a fully invested target cannot fund its own commissions
    # once equity drifts, which is BaseEngine behaviour and not under test.
    engine = _run([0.5] * 9, tmp_path)
    assert engine.fill_records
    assert engine.fill_records[0].action == "open"


def test_uk_orders_are_whole_shares(tmp_path: Path) -> None:
    """LSE has no native fractional-share orders."""
    engine = _run([0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5], tmp_path)
    fills = engine.fill_records
    assert fills
    assert all(abs(fill.signed_quantity) > 0 for fill in fills)
    assert all(float(fill.signed_quantity).is_integer() for fill in fills)


def test_uk_uses_uk_slippage_configuration() -> None:
    engine = GlobalEquityEngine(
        {"slippage_us": 0.001, "slippage_uk": 0.02}, market="uk"
    )

    assert engine.apply_slippage(100.0, 1) == pytest.approx(102.0)
    assert engine.apply_slippage(100.0, -1) == pytest.approx(98.0)


def test_uk_sdrt_charged_on_buys_only() -> None:
    """LSE Main Market carries 0.5% SDRT on the buyer (purchase-side only).

    The engine's commission function is the fee surface the market= value
    selects. Sells pay nothing; buys (including covering a short) pay 0.5%
    of consideration rounded to the nearest penny (FA86/S99(13)).
    """
    engine = _create_market_engine("auto", {"initial_cash": 100_000}, [CODE])
    assert isinstance(engine, GlobalEquityEngine)
    assert engine.market == "uk"
    assert engine.calc_commission(1000.0, 1.10, 1, is_open=True) == 5.5
    assert engine.calc_commission(1000.0, 1.10, -1, is_open=True) == 0.0
    # Close path: the engine passes the POSITION side, so closing a long
    # (direction=1) is a sale and covering a short (direction=-1) is a buy.
    assert engine.calc_commission(1000.0, 1.10, 1, is_open=False) == 0.0
    assert engine.calc_commission(1000.0, 1.10, -1, is_open=False) == 5.5
    # Exact half-penny rounds UP per the HMRC manual (13.4547 -> 13.45,
    # 13.455 -> 13.46).
    assert engine.calc_commission(2690.94, 1.0, 1, is_open=True) == 13.45
    assert engine.calc_commission(2691.0, 1.0, 1, is_open=True) == 13.46
