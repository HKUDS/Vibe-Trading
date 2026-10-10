"""Smoke tests for the candidate engines in skills/options-strategy.

Each engine runs a short deterministic backtest on a synthetic random walk
and must place trades, settle or close every expired leg, and produce finite
equity.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.options_portfolio import run_options_backtest

_PATH = Path(__file__).parents[1] / "src" / "skills" / "options-strategy" / "example_signal_engine.py"
_spec = spec_from_file_location("options_strategy_engines", _PATH)
engines = module_from_spec(_spec)
_spec.loader.exec_module(engines)

_DATES = pd.bdate_range("2023-01-02", periods=260)
_CLOSE = 100 * np.exp(np.cumsum(np.random.default_rng(7).normal(0.0003, 0.012, len(_DATES))))
_BARS = pd.DataFrame(
    {"open": _CLOSE, "high": _CLOSE * 1.005, "low": _CLOSE * 0.995, "close": _CLOSE,
     "volume": 1_000},
    index=_DATES,
)
_OPTS = {"risk_free_rate": 0.02, "iv_skew": -0.3, "iv_curvature": 0.0, "default_iv": 0.2}


class _Loader:
    name = "synthetic"

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        return {"SPY": _BARS.copy()}


@pytest.mark.parametrize("name", sorted(engines.ENGINES))
def test_engine_runs_and_settles(tmp_path: Path, name: str) -> None:
    engine = engines.ENGINES[name](**_OPTS, commission=0.01, capital=100_000,
                                   start_date="2023-03-01")
    config = {
        "codes": ["SPY"], "start_date": "2023-01-02", "end_date": "2023-12-29",
        "initial_cash": 100_000, "commission": 0.01,
        "evaluation_start_date": "2023-02-28",
        "options_config": dict(_OPTS, contract_multiplier=1.0,
                               margin_enabled=name not in {"covered_call", "protective_put",
                                                           "iron_condor"}),
    }
    run_options_backtest(config, _Loader(), engine, tmp_path)
    art = tmp_path / "artifacts"
    trades = pd.read_csv(art / "trades.csv")
    equity = pd.read_csv(art / "equity.csv")

    opens = trades[trades["side"].isin(["buy", "sell"])]
    assert len(opens) >= 3, trades
    assert not (trades["side"] == "reject").any()
    assert opens["timestamp"].min() >= "2023-03-01"
    assert np.isfinite(equity["equity"]).all() and (equity["equity"] > 0).all()

    # Every option leg that expired inside the run was settled or closed.
    last = equity["timestamp"].iloc[-1]
    settled = trades[trades["side"].isin(["close", "exercise", "expire"])]
    done = settled.groupby(["strike", "expiry", "entry_date"])["qty"].sum()
    for _, leg in opens[opens["expiry"] <= last].iterrows():
        assert done.get((leg["strike"], leg["expiry"], leg["timestamp"]), 0) == leg["qty"], leg
