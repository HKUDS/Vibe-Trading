"""Standalone validation must preserve the saved simulation settings."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest import validation


def _write_run(tmp_path: Path, config: dict | None) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    if config is not None:
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    dates = pd.date_range("2026-01-01", periods=20)
    equity = 1000 * np.cumprod(1 + np.array([0.01, -0.005, 0.02, -0.01] * 5))
    pd.DataFrame({"equity": equity}, index=dates).to_csv(artifacts / "equity.csv")
    pd.DataFrame(
        {
            "timestamp": ["2026-01-03", "2026-01-08", "2026-01-15"],
            "code": ["TEST"] * 3,
            "side": ["sell"] * 3,
            "price": [110, 95, 102],
            "qty": [1] * 3,
            "pnl": [10, -5, 2],
            "event": ["exit"] * 3,
        }
    ).to_csv(artifacts / "trades.csv", index=False)


def test_main_honors_saved_settings(tmp_path: Path, capsys) -> None:
    settings = {
        "monte_carlo": {"n_simulations": 7, "seed": 17},
        "bootstrap": {"n_bootstrap": 11, "confidence": 0.8, "seed": 23},
        "walk_forward": {"n_windows": 2},
    }
    config = {"initial_cash": 1000, "validation": settings}
    _write_run(tmp_path, config)

    actual = validation.main(tmp_path)

    assert actual["monte_carlo"]["n_simulations"] == 7
    assert actual["bootstrap"]["n_bootstrap"] == 11
    assert actual["bootstrap"]["confidence"] == 0.8
    assert actual["walk_forward"]["n_windows"] == 2
    # Direct dispatch uses the same saved knobs and independently initialized
    # RNGs; comparing sample arrays catches ignored seeds, not just metadata.
    expected = validation.run_validation(
        config,
        validation._load_equity(tmp_path),
        validation._load_trades(tmp_path),
        1000,
    )
    assert actual == expected
    assert json.loads(capsys.readouterr().out) == expected
    assert json.loads((tmp_path / "artifacts/validation.json").read_text()) == expected
    assert json.loads((tmp_path / "config.json").read_text()) == config


def test_partial_config_still_runs_all_tools(tmp_path: Path, capsys) -> None:
    _write_run(tmp_path, {"validation": {"bootstrap": {"n_bootstrap": 9}}})

    actual = validation.main(tmp_path)

    assert actual["bootstrap"]["n_bootstrap"] == 9
    assert actual["monte_carlo"]["n_simulations"] == 1000
    assert actual["walk_forward"]["n_windows"] == 5
    capsys.readouterr()


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"validation": None},
        {"validation": False},
        {"validation": {"bootstrap": True}},
    ],
)
def test_missing_settings_keep_standalone_defaults(
    tmp_path: Path, capsys, config
) -> None:
    _write_run(tmp_path, config)

    actual = validation.main(tmp_path)

    expected = {
        "monte_carlo": validation.monte_carlo_test(
            validation._load_trades(tmp_path), 1_000_000
        ),
        # The CLI seeds bootstrap returns with its initial_cash fallback
        # (1_000_000 when the config carries none), same as run_validation.
        "bootstrap": validation.bootstrap_sharpe_ci(
            validation._load_equity(tmp_path), initial_capital=1_000_000
        ),
        "walk_forward": validation.walk_forward_analysis(
            validation._load_equity(tmp_path), validation._load_trades(tmp_path)
        ),
    }
    assert actual == expected
    capsys.readouterr()


@pytest.mark.parametrize(
    "tool, settings, message",
    [
        ("monte_carlo", {"seed": -1}, "seed must be >= 0"),
        ("bootstrap", {"confidence": 1.5}, "confidence must be in (0, 1)"),
        ("walk_forward", {"n_windows": 0}, "n_windows must be >= 1"),
    ],
)
def test_invalid_saved_settings_use_existing_errors(
    tmp_path: Path, capsys, tool: str, settings: dict, message: str
) -> None:
    _write_run(tmp_path, {"validation": {tool: settings}})

    actual = validation.main(tmp_path)

    assert message in actual[tool]["error"]
    capsys.readouterr()


@pytest.mark.parametrize(
    "run_config, annualisation",
    [
        ({"source": "okx", "interval": "1H", "codes": ["BTC-USDT"]}, "interval"),
        ({"source": "tushare", "interval": "1D", "codes": ["000001.SZ"]}, "interval"),
        ({"source": "auto", "interval": "1D", "codes": ["000001.SZ", "BTC-USDT"]}, "calendar"),
    ],
)
def test_main_annualises_like_the_saved_run(tmp_path: Path, capsys, run_config, annualisation) -> None:
    from backtest.metrics import calc_bars_per_year

    settings = {
        "monte_carlo": {"n_simulations": 5, "seed": 1},
        "bootstrap": {"n_bootstrap": 5, "seed": 2},
        "walk_forward": {"n_windows": 2},
    }
    config = {"initial_cash": 1000, "validation": settings, **run_config}
    _write_run(tmp_path, config)
    if annualisation == "calendar":
        bars = None
    else:
        bars = calc_bars_per_year(run_config["interval"], run_config["source"])

    actual = validation.main(tmp_path)
    capsys.readouterr()

    expected = validation.run_validation(
        config, validation._load_equity(tmp_path), validation._load_trades(tmp_path), 1000, bars
    )
    assert actual["bootstrap"]["observed_sharpe"] == expected["bootstrap"]["observed_sharpe"]
    assert actual == expected
