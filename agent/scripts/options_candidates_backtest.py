"""Backtest the candidate options strategies in skills/options-strategy.

In-sample 2016-2020 picks one parameter per strategy (best mean Sharpe over
SPY and QQQ); out-of-sample 2021 onward reports every underlying with those
parameters untouched. Prints markdown tables.

    PYTHONPATH=agent python agent/scripts/options_candidates_backtest.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.engines.options_portfolio import run_options_backtest
from backtest.loaders.yfinance_loader import DataLoader

_spec = importlib.util.spec_from_file_location(
    "options_strategy_engines",
    Path(__file__).parents[1] / "src" / "skills" / "options-strategy" / "example_signal_engine.py",
)
engines = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engines)

UNDERLYINGS = {"SPY.US": 0.01, "QQQ.US": 0.01, "AAPL.US": 0.02, "MSFT.US": 0.02}  # commission
IS = ("2015-01-01", "2016-01-04", "2020-12-31")   # load from, evaluate from, end
OOS = ("2020-01-01", "2021-01-04", "2026-10-08")
OPTIONS = {"risk_free_rate": 0.02, "iv_skew": -0.3, "iv_curvature": 0.0,
           "default_iv": 0.3, "contract_multiplier": 1.0}
CASH = 100_000.0
# The engine margins every short leg as naked. Covered calls are covered by the
# share replica and condors are sized so max loss is 10% of capital (the
# Reg-T spread requirement), so neither is run against that margin model; left
# on, it rejects single condor legs and leaves the rest of the structure naked.
NO_MARGIN = {"covered_call", "protective_put", "iron_condor"}
GRID = {
    "covered_call": [{"delta": 0.20}, {"delta": 0.30}],
    "cash_secured_put": [{"delta": 0.20}, {"delta": 0.30}],
    "iron_condor": [{"short_delta": 0.10}, {"short_delta": 0.16}, {"short_delta": 0.25}],
    "vol_gated_strangle": [{"gate": "none"}, {"gate": "contracting"}, {"gate": "elevated"}],
    "protective_put": [{"delta": 0.15}, {"delta": 0.30}],
}

_frames: dict[str, pd.DataFrame] = {}


class _Loader:
    name = "yfinance"

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        missing = [c for c in codes if c not in _frames]
        if missing:
            _frames.update(DataLoader().fetch(missing, "2015-01-01", OOS[2]))
        return {c: _frames[c].loc[start_date:end_date] for c in codes}


_tbill: pd.Series | None = None


def with_tbill(equity: pd.Series, cash: pd.Series) -> pd.Series:
    """Credit (or charge) the 13-week T-bill rate on the engine's cash balance,
    which the engine itself leaves at 0%. Simple interest, added post hoc."""
    global _tbill
    if _tbill is None:
        import yfinance as yf

        irx = yf.download("^IRX", start="2015-01-01", end=OOS[2], progress=False,
                          auto_adjust=False)["Close"].squeeze()
        _tbill = irx.tz_localize(None) / 100.0
    rate = _tbill.reindex(cash.index, method="ffill").fillna(0.0)
    return equity + (cash.shift(1).fillna(0.0) * rate / 252).cumsum()


def run(strategy: str, params: dict, code: str, window: tuple) -> tuple[pd.Series, pd.DataFrame]:
    load_from, eval_from, end = window
    commission = UNDERLYINGS[code]
    engine = engines.ENGINES[strategy](
        **{k: OPTIONS[k] for k in ("risk_free_rate", "iv_skew", "iv_curvature", "default_iv")},
        commission=commission, capital=CASH, start_date=eval_from, **params)
    config = {
        "codes": [code], "start_date": load_from, "end_date": end, "source": "yfinance",
        "engine": "options", "initial_cash": CASH, "commission": commission,
        "evaluation_start_date": eval_from,
        "options_config": dict(OPTIONS, margin_enabled=strategy not in NO_MARGIN),
    }
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        run_options_backtest(config, _Loader(), engine, Path(tmp))
        art = Path(tmp) / "artifacts"
        frame = pd.read_csv(art / "equity.csv", index_col="timestamp", parse_dates=True)
        trades = pd.read_csv(art / "trades.csv")
    return frame["equity"], trades, frame["cash"]


def stats(equity: pd.Series, trades: pd.DataFrame | None = None,
          cash: pd.Series | None = None) -> dict:
    ret = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    monthly = equity.resample("ME").last().pct_change().dropna()
    out = {
        "CAGR": (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1,
        "Sharpe": ret.mean() / ret.std() * np.sqrt(252),
        "MaxDD": (equity / equity.cummax() - 1).min(),
        "WorstMo": monthly.min(),
        "WorstDay": ret.min(),
        "CVaR5": ret[ret <= ret.quantile(0.05)].mean(),
        "Skew": ret.skew(),
    }
    if cash is not None:
        adj = with_tbill(equity, cash)
        out["CAGR+bill"] = (adj.iloc[-1] / adj.iloc[0]) ** (1 / years) - 1
    if trades is not None:
        settled = trades[trades["side"].isin(["close", "exercise", "expire"])
                         & (trades["strike"] > 0.01)]
        per_trade = settled.groupby(["entry_date", "expiry"])["pnl"].sum()
        out["WinRate"] = (per_trade > 0).mean() if len(per_trade) else np.nan
        out["Trades"] = len(per_trade)
        out["Rejects"] = int((trades["side"] == "reject").sum())
    return out


def table(rows: list[dict]) -> str:
    cols = list(dict.fromkeys(k for r in rows for k in r))
    pct = {"CAGR", "CAGR+bill", "MaxDD", "WorstMo", "WorstDay", "CVaR5", "WinRate"}

    def fmt(k: str, v: object) -> str:
        if isinstance(v, float):
            return f"{v:.1%}" if k in pct else f"{v:.2f}"
        return str(v)

    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(k, r.get(k, "")) for k in cols) + " |" for r in rows]
    return "\n".join(lines)


def main() -> None:
    chosen, is_rows = {}, []
    for strategy, grid in GRID.items():
        scores = []
        for params in grid:
            sharpes = []
            for code in ("SPY.US", "QQQ.US"):
                s = stats(*run(strategy, params, code, IS))
                sharpes.append(s["Sharpe"])
                is_rows.append({"Strategy": strategy, "Params": params, "Code": code, **s})
            scores.append(np.mean(sharpes))
        chosen[strategy] = grid[int(np.argmax(scores))]
    for code in ("SPY.US", "QQQ.US"):
        close = _Loader().fetch([code], IS[1], IS[2])[code]["close"]
        is_rows.append({"Strategy": "buy_and_hold", "Params": {}, "Code": code, **stats(close)})
    print("## In-sample 2016-2020\n\n" + table(is_rows) + "\n")
    print("Chosen: " + ", ".join(f"{k}={v}" for k, v in chosen.items()) + "\n")

    oos_rows = []
    for code in UNDERLYINGS:
        close = _Loader().fetch([code], OOS[1], OOS[2])[code]["close"]
        oos_rows.append({"Strategy": "buy_and_hold", "Code": code, **stats(close)})
        for strategy, params in chosen.items():
            oos_rows.append({"Strategy": strategy, "Code": code,
                             **stats(*run(strategy, params, code, OOS))})
    print("## Out-of-sample 2021-2026\n\n" + table(oos_rows) + "\n")

    # Smile sensitivity: the only lever on option richness the engine exposes.
    sens_rows = []
    for skew in (0.0, -0.3, -0.6):
        OPTIONS["iv_skew"] = skew
        for strategy, params in chosen.items():
            s = stats(*run(strategy, params, "SPY.US", OOS))
            sens_rows.append({"iv_skew": skew, "Strategy": strategy,
                              **{k: s[k] for k in ("CAGR", "CAGR+bill", "Sharpe", "MaxDD")}})
    print("## SPY out-of-sample, smile skew sensitivity\n\n" + table(sens_rows))


if __name__ == "__main__":
    main()
