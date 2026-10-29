"""End-to-end BYMA backtests through runner.main: YPFD buy-and-hold, YPFD/GGAL
rotation, AAPL.BA across its 2024 CEDEAR ratio change, and composite parity.

Synthetic bars on real 2024 BYMA sessions (holidays are simply absent, as in
the loaders' output once placeholder bars are dropped); the Yahoo descriptor
is stubbed; no network.
"""

from __future__ import annotations

import csv
import io
import json
import textwrap
from contextlib import redirect_stdout

import pandas as pd
import pytest

from backtest import runner
from backtest.engines.argentina_equity import ArgentinaEquityEngine
from backtest.engines.composite import CompositeEngine

HOLIDAYS_2024 = {
    "2024-01-01",
    "2024-02-12",
    "2024-02-13",
    "2024-03-28",
    "2024-03-29",
    "2024-04-01",
    "2024-04-02",
    "2024-05-01",
    "2024-06-17",
    "2024-06-20",
    "2024-06-21",
    "2024-07-09",
}
NAMES = {"YPFD.BA": "YPF SOCIEDAD ANONIMA", "GGAL.BA": "GRUPO FINANCIERO GALICIA SA"}
HOLD = textwrap.dedent("""
    import pandas as pd


    class SignalEngine:
        def generate(self, data_map):
            return {c: pd.Series(0.95, index=d.index) for c, d in data_map.items()}
""")
ROTATE = textwrap.dedent('''
    import pandas as pd


    class SignalEngine:
        """YPFD until the 2024-08-01 session, GGAL from then on."""

        def generate(self, data_map):
            out = {}
            for code, df in data_map.items():
                nxt = pd.Series(df.index, index=df.index).shift(-1).fillna(df.index[-1])
                on_ggal = nxt >= pd.Timestamp("2024-08-01")
                weight = on_ggal if code == "GGAL.BA" else ~on_ggal
                out[code] = weight.astype(float) * 0.95
            return out
''')


def _frame(start, end, base, drift=0.0, ex=None, factor=1.0, placeholders=()):
    days = [
        d
        for d in pd.bdate_range(start, end)
        if d.strftime("%Y-%m-%d") not in HOLIDAYS_2024
    ]
    days = sorted(set(days) | {pd.Timestamp(p) for p in placeholders})
    rows = []
    for i, day in enumerate(days):
        close = round(base * (1 + drift) ** i * (1 + 0.004 * ((i * 7) % 5 - 2)), 2)
        if ex is not None and day >= pd.Timestamp(ex):
            close = round(close * factor, 2)
        volume = 0.0 if day.strftime("%Y-%m-%d") in placeholders else 80_000.0
        rows.append((day, round(close * 0.998, 2), close, volume))
    frame = pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] * 1.01 for r in rows],
            "low": [r[2] * 0.99 for r in rows],
            "close": [r[2] for r in rows],
            "volume": [r[3] for r in rows],
        },
        index=pd.DatetimeIndex([r[0] for r in rows]),
    )
    frame.attrs["quote_currency"] = "ARS"
    return frame


def _run(tmp_path, monkeypatch, config, frames, signal=HOLD):
    class Loader:
        name = "yahoo"

        def fetch(self, codes, *args, **kwargs):
            out = {}
            for code in codes:
                out[code] = frames[code].copy()
                out[code].attrs = dict(frames[code].attrs)
            return out

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)
    monkeypatch.setattr(runner, "_get_loader", lambda source: Loader)
    monkeypatch.setattr(
        ArgentinaEquityEngine, "describe_instrument", staticmethod(NAMES.get)
    )
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (run_dir / "code" / "signal_engine.py").write_text(signal, encoding="utf-8")
    out = io.StringIO()
    with redirect_stdout(out):
        runner.main(run_dir)
    printed = out.getvalue()
    ledger = list(csv.DictReader((run_dir / "artifacts" / "cash_ledger.csv").open()))
    prep = json.loads((run_dir / "artifacts" / "byma_preparation.json").read_text())
    return json.loads(printed[printed.index("{") :]), ledger, prep, run_dir


def _config(codes, start, end, **extra):
    return {
        "source": "yahoo",
        "codes": codes,
        "start_date": start,
        "end_date": end,
        "initial_cash": 1_000_000,
        "commission": 0.001,
        "engine": "daily",
        "ar_tick_table": "2024-07-04",
        **extra,
    }


def _closes_on_cash(ledger, metrics):
    cash = 1_000_000.0
    for row in ledger:
        cash += float(row["cash_flow"])
        assert abs(float(row["fee"]) - float(row["notional"]) * 0.001) < 1e-6
    assert cash == pytest.approx(float(ledger[-1]["cash_after"]))
    assert cash == pytest.approx(metrics["final_value"])


def test_ypfd_buy_and_hold_minimal_config(tmp_path, monkeypatch):
    frame = _frame(
        "2024-06-03", "2024-09-30", 26000.0, 0.001, placeholders={"2024-06-20"}
    )
    config = _config(
        ["YPFD.BA"], "2024-06-01", "2024-09-30", position_adjustment="hold"
    )
    metrics, ledger, prep, _ = _run(tmp_path, monkeypatch, config, {"YPFD.BA": frame})
    assert metrics["trade_count"] == 1 and metrics["settlement_currency"] == "ARS"
    buy, sell = ledger
    assert (buy["timestamp"], buy["settlement_date"]) == (
        "2024-06-04",
        "2024-06-05",
    )  # T+1
    assert (sell["timestamp"], sell["settlement_basis"]) == (
        "2024-09-30",
        "beyond_loaded_data",
    )
    assert sell["settlement_date"] == ""  # never a guessed date
    assert prep["ar_metadata_provenance"]["YPFD.BA"]["kind"].startswith("vendor")
    assert "observed trading sessions [approximation" in metrics["ar_data_basis"]
    assert prep["ar_dropped_no_trade_dates"] == ["2024-06-20"]  # holiday placeholder
    _closes_on_cash(ledger, metrics)


@pytest.mark.parametrize("mode", ["hold", "rebalance"])
def test_ypfd_ggal_rotation_nets_the_same_session_sale(tmp_path, monkeypatch, mode):
    frames = {
        "YPFD.BA": _frame("2024-06-03", "2024-09-30", 2900.0, -0.002),
        "GGAL.BA": _frame("2024-06-03", "2024-09-30", 3500.0, 0.004),
    }
    config = _config(
        ["YPFD.BA", "GGAL.BA"], "2024-06-01", "2024-09-30", position_adjustment=mode
    )
    metrics, ledger, _, _ = _run(tmp_path, monkeypatch, config, frames, ROTATE)
    by_side = [(r["timestamp"], r["code"], r["side"]) for r in ledger]
    assert ("2024-08-01", "YPFD.BA", "sell") in by_side and (
        "2024-08-01",
        "GGAL.BA",
        "buy",
    ) in by_side
    sale = next(
        r for r in ledger if r["timestamp"] == "2024-08-01" and r["side"] == "sell"
    )
    buy = next(
        r for r in ledger if r["timestamp"] == "2024-08-01" and r["side"] == "buy"
    )
    assert sale["settlement_date"] == buy["settlement_date"] == "2024-08-02"
    previous_cash = float(ledger[ledger.index(sale) - 1]["cash_after"])
    assert float(buy["buying_power_before"]) == pytest.approx(
        previous_cash + float(sale["net_proceeds"])
    )
    assert float(buy["total_cost"]) <= float(buy["buying_power_before"])
    assert (
        float(buy["total_cost"]) > previous_cash
    )  # funded by the sale, not by settled cash alone
    assert min(float(r["cash_after"]) for r in ledger) >= -1e-6
    _closes_on_cash(ledger, metrics)


AAPL = {
    "kind": "cedear",
    "underlying": "AAPL",
    "ratio_history": [
        {"effective_date": "2010-06-24", "ratio": "10"},
        {"effective_date": "2024-01-24", "ratio": "20", "credit_date": "2024-01-26"},
    ],
}


def test_aapl_ratio_change_books_no_artificial_loss(tmp_path, monkeypatch):
    frame = _frame(
        "2024-01-02", "2024-03-27", 25000.0, 0.0, ex="2024-01-24", factor=0.5
    )
    config = _config(
        ["AAPL.BA"],
        "2024-01-02",
        "2024-03-27",
        position_adjustment="hold",
        ar_instruments={"AAPL.BA": AAPL},
    )
    metrics, ledger, prep, run_dir = _run(
        tmp_path, monkeypatch, config, {"AAPL.BA": frame}
    )
    buy, sell = ledger
    assert (buy["timestamp"], buy["settlement_date"]) == (
        "2024-01-03",
        "2024-01-05",
    )  # T+2
    assert float(buy["qty"]) % 2 == 0  # whole real certificates before the change
    assert (sell["timestamp"], sell["settlement_basis"]) == (
        "2024-03-27",
        "beyond_loaded_data",
    )
    adj = prep["ar_cedear_ratio_adjustments"][0]
    assert adj["rescaled_prior_bars"] is True and adj["credit_date"] == "2024-01-26"
    equity = pd.read_csv(run_dir / "artifacts" / "equity.csv", index_col=0)["equity"]
    assert (
        abs(equity.loc["2024-01-24"] / equity.loc["2024-01-23"] - 1) < 0.05
    )  # no -50% step
    _closes_on_cash(ledger, metrics)


def test_aapl_without_the_ratio_change_fails_closed(tmp_path, monkeypatch):
    frame = _frame(
        "2024-01-02", "2024-03-27", 25000.0, 0.0, ex="2024-01-24", factor=0.5
    )
    instrument = {**AAPL, "ratio_history": AAPL["ratio_history"][:1]}
    config = _config(
        ["AAPL.BA"], "2024-01-02", "2024-03-27", ar_instruments={"AAPL.BA": instrument}
    )
    with pytest.raises(
        ValueError, match="unexplained price discontinuities on 2024-01-24"
    ):
        _run(tmp_path, monkeypatch, config, {"AAPL.BA": frame})


@pytest.mark.parametrize("mode", ["hold", "rebalance"])
def test_composite_matches_the_standalone_engine(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(
        ArgentinaEquityEngine, "describe_instrument", staticmethod(NAMES.get)
    )
    frames = {
        "YPFD.BA": _frame("2024-06-03", "2024-09-30", 2900.0, -0.002),
        "GGAL.BA": _frame("2024-06-03", "2024-09-30", 3500.0, 0.004),
    }
    codes = ["YPFD.BA", "GGAL.BA"]
    config = _config(codes, "2024-06-01", "2024-09-30", position_adjustment=mode)

    class Loader:
        def fetch(self, codes, *a, **k):
            return {c: frames[c].copy() for c in codes}

    namespace: dict = {}
    exec(
        compile(ROTATE, "signal_engine.py", "exec"), namespace
    )  # noqa: S102 - test fixture
    results = []
    for engine in (ArgentinaEquityEngine(config), CompositeEngine(config, codes)):
        with redirect_stdout(io.StringIO()):
            metrics = engine.run_backtest(
                config,
                Loader(),
                namespace["SignalEngine"](),
                tmp_path / type(engine).__name__,
            )
        results.append(
            (
                [
                    (
                        f.symbol,
                        f.action,
                        str(f.timestamp.date()),
                        f.signed_quantity,
                        f.fee,
                    )
                    for f in engine.fill_records
                ],
                metrics["total_return"],
            )
        )
    assert results[0] == results[1]
