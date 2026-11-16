"""HK board lots are set per issuer, so ``round_size`` must not assume 100.

A flat 100-share lot mis-sizes most HK names, and quietly: a target smaller
than one assumed lot rounds to zero and the symbol simply never trades. The
symbols and lot sizes below are synthetic.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine

LOTS = {"00001.HK": 20, "00002.HK": 100, "00003.HK": 5000}
LOGGER = "backtest.engines.global_equity"


def _engine(
    lots: dict[str, int] | None = LOTS,
    market: str = "hk",
    initial_cash: float = 1_000_000,
) -> GlobalEquityEngine:
    config: dict = {"initial_cash": initial_cash}
    if lots is not None:
        config["hk_lot_sizes"] = lots
    return GlobalEquityEngine(config, market=market)


def _sized(engine: GlobalEquityEngine, symbol: str, raw: float) -> float:
    engine._active_symbol = symbol
    return engine.round_size(raw, price=10.0)


@pytest.mark.parametrize(
    ("symbol", "raw", "expected"),
    [
        ("00001.HK", 99, 80),  # lot 20: four lots, where a 100 grid gives 0
        ("00001.HK", 19, 0),  # below one real lot
        ("00002.HK", 250, 200),  # lot 100 unchanged
        ("00003.HK", 12_345, 10_000),  # lot 5000
    ],
)
def test_round_size_uses_the_symbols_own_lot(
    symbol: str, raw: float, expected: float
) -> None:
    assert _sized(_engine(), symbol, raw) == expected


@pytest.mark.parametrize("written", ["1.HK", "0001.HK", " 00001.hk "])
def test_table_keys_match_however_the_code_is_padded(written: str) -> None:
    engine = _engine({written: 20})

    assert _sized(engine, "00001.HK", 99) == 80
    assert _sized(engine, "1.HK", 99) == 80
    assert engine.lot_assumptions == {}


def test_unlisted_symbol_falls_back_and_reaches_the_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = _engine()

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _sized(engine, "00009.HK", 250) == 200
        assert _sized(engine, "00009.HK", 350) == 300

    assert engine._engine_diagnostics() == {
        "lot_assumptions": [{"symbol": "0009.HK", "field": "board_lot", "value": 100}]
    }
    assert sum("0009.HK" in r.getMessage() for r in caplog.records) == 1


def test_non_positive_lot_is_treated_as_missing() -> None:
    engine = _engine({"00001.HK": 0})

    assert _sized(engine, "00001.HK", 250) == 200
    assert engine.lot_assumptions == {"0001.HK": 100}


def test_without_a_table_default_lots_are_still_disclosed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = _engine(lots=None)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _sized(engine, "00001.HK", 99) == 0
        assert _sized(engine, "00002.HK", 250) == 200

    assert engine.lot_assumptions == {"0001.HK": 100, "0002.HK": 100}
    assert len(engine._engine_diagnostics()["lot_assumptions"]) == 2
    assert len(caplog.records) == 2


def test_non_hk_markets_ignore_the_table() -> None:
    us = _engine(market="us")
    ca = _engine(market="ca")

    assert _sized(us, "AAPL", 59.4321) == 59.43
    assert _sized(ca, "SHOP.TO", 59.9) == 59.0
    assert "lot_assumptions" not in us._engine_diagnostics()
    assert ca._engine_diagnostics() == {}


def test_a_rebalance_fills_each_symbol_on_its_own_lot() -> None:
    """Through the engine's own sizing path, not just ``round_size``."""
    engine = _engine({"00001.HK": 20, "00002.HK": 500}, initial_cash=100_000)
    dates = pd.date_range("2026-01-05", periods=2, freq="B")
    prices = {"00001.HK": [300.0, 300.0], "00002.HK": [3.0, 3.0]}
    data_map = {
        symbol: pd.DataFrame({"open": values, "close": values}, index=dates)
        for symbol, values in prices.items()
    }
    weights = pd.DataFrame(
        {"00001.HK": [0.0, 0.1], "00002.HK": [0.0, 0.1]}, index=dates
    )

    engine._execute_bars(
        dates, data_map, pd.DataFrame(prices, index=dates), weights, list(prices)
    )

    opened = {
        fill.symbol: abs(fill.signed_quantity)
        for fill in engine.fill_records
        if fill.action == "open"
    }
    assert opened["00001.HK"] > 0 and opened["00001.HK"] % 20 == 0
    assert opened["00002.HK"] > 0 and opened["00002.HK"] % 500 == 0
    assert engine.lot_assumptions == {}


def test_composite_preserves_lot_and_futures_assumptions():
    from backtest.engines.composite import CompositeEngine

    engine = CompositeEngine({"hk_lot_sizes": {"0700.HK": 20}}, ["0700.HK", "0005.HK"])
    engine._active_symbol = "0005.HK"
    assert engine.round_size(250, 10) == 200
    hk = engine._rule_for("0005.HK")
    # Exercise an independent diagnostic provider without inventing a future's
    # exchange metadata: the composite must retain every sub-engine report.
    class OtherDiagnostics:
        def _engine_diagnostics(self):
            return {"pricing_assumptions": [{"product": "ZZ", "field": "tick", "value": 1}]}
    engine._rule_engines["synthetic"] = OtherDiagnostics()
    report = engine._engine_diagnostics()
    assert report["lot_assumptions"] == hk._engine_diagnostics()["lot_assumptions"]
    assert report["pricing_assumptions"] == [{"product": "ZZ", "field": "tick", "value": 1}]
    assert "hk_equity" in report["market_diagnostics"]


@pytest.mark.parametrize("composite", [False, True])
def test_local_csv_run_persists_lot_assumptions(tmp_path, monkeypatch, composite):
    """Actual CSV ingestion and artifact writing preserve sizing diagnostics."""
    import json

    from backtest.engines.composite import CompositeEngine
    from backtest.loaders import local_loader

    codes = ["00001.HK", "00002.HK"]
    dates = pd.date_range("2026-01-05", periods=4, freq="B")
    sources = []
    for symbol in codes:
        path = tmp_path / f"{symbol}.csv"
        pd.DataFrame({"date": dates, "open": 10, "high": 10, "low": 10,
                      "close": 10, "volume": 100_000}).to_csv(path, index=False)
        sources.append({"symbol": symbol, "type": "csv", "path": str(path)})
    config_path = tmp_path / "data-bridge.yaml"
    config_path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config_path)
    config = {"codes": codes, "initial_cash": 100_000, "source": "local",
              "start_date": "2026-01-05", "end_date": "2026-01-08",
              "hk_lot_sizes": {"00001.HK": 20}}

    class Signals:
        def generate(self, frames):
            return {symbol: pd.Series(1.0, index=frame.index)
                    for symbol, frame in frames.items()}

    engine = CompositeEngine(config, codes) if composite else GlobalEquityEngine(config, market="hk")
    run_dir = tmp_path / "run"
    engine.run_backtest(config, local_loader.DataLoader(), Signals(), run_dir)
    fills = [json.loads(line) for line in (run_dir / "artifacts/fills.jsonl").read_text().splitlines()]
    opened = [fill for fill in fills if fill["action"] == "open"]
    assert {fill["symbol"] for fill in opened} == set(codes)
    assert all(abs(fill["signed_quantity"]) % (20 if fill["symbol"] == codes[0] else 100) == 0
               for fill in opened)
    card = json.loads((run_dir / "run_card.json").read_text())
    expected = [{"symbol": "0002.HK", "field": "board_lot", "value": 100}]
    assert card["structured_metrics"]["lot_assumptions"] == expected
    if composite:
        assert card["structured_metrics"]["market_diagnostics"]["hk_equity"]["lot_assumptions"] == expected
