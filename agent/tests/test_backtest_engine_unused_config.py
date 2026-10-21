"""Engine-specific configuration warnings use the actual selected rule books."""

import json
from pathlib import Path

import pandas as pd

from backtest.engines.crypto import CryptoEngine
from backtest.runner import _AutoLoader, _create_market_engine


def test_crypto_unused_commission_is_visible_in_real_run_card(tmp_path: Path) -> None:
    config = {
        "codes": ["BTC-USDT"],
        "source": "okx",
        "start_date": "2024-01-01",
        "end_date": "2024-01-06",
        "initial_cash": 1000,
        "commission_rate": 0.001,
    }
    engine = _create_market_engine("okx", config, config["codes"])
    assert isinstance(engine, CryptoEngine)
    # This key does not configure crypto: the genuine fee remains the default.
    assert engine.taker_rate == 0.0005
    dates = pd.date_range("2024-01-01", periods=6)
    bars = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=dates,
    )

    class SignalEngine:
        def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
            return {"BTC-USDT": pd.Series(0.0, index=dates)}

    engine.run_backtest(
        config, _AutoLoader({"BTC-USDT": bars}), SignalEngine(), tmp_path
    )
    card = json.loads((tmp_path / "run_card.json").read_text())
    assert any(
        "commission_rate" in warning and "unused" in warning
        for warning in card["warnings"]
    )


def test_active_crypto_and_shared_settings_are_not_reported_unused() -> None:
    config = {
        "codes": ["BTC-USDT"],
        "taker_rate": 0.001,
        "maker_rate": 0.002,
        "constraints": [],
        "model_training_cutoff": "2023-12-31",
    }
    engine = _create_market_engine("okx", config, config["codes"])
    assert engine.taker_rate == 0.001
    assert engine.maker_rate == 0.002
    assert not config.get("_run_card_unrecognized_config_warning")


def test_equity_commission_is_read_by_the_selected_engine() -> None:
    config = {"codes": ["000001.SZ"], "commission_rate": 0.001}
    engine = _create_market_engine("tushare", config, config["codes"])
    assert engine.commission_rate == 0.001
    assert not config.get("_run_card_unrecognized_config_warning")


def test_composite_includes_config_read_by_its_actual_subengines() -> None:
    config = {"codes": ["AAPL", "BTC-USDT"], "slippage_us": 0.001, "maker_rate": 0.002}
    engine = _create_market_engine("auto", config, config["codes"])
    assert engine._rule_engines["crypto"].maker_rate == 0.002
    assert engine._rule_engines["us_equity"].slippage_us == 0.001
    assert not config.get("_run_card_unrecognized_config_warning")
