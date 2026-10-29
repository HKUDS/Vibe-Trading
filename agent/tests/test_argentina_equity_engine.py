"""BYMA engine rules: configuration, units, settlement in sessions, netting,
terminal close, CEDEAR credit window and price basis. Synthetic data only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.engines.argentina_equity import (
    classify_short_name,
    discontinuities,
    equity_tick,
    reconcile_ratio_changes,
)
from backtest.engines.argentina_equity import (
    ArgentinaEquityEngine,
    argentina_available_cash,
    argentina_sell_allowed,
    normal_cash_lag,
)

SHARE = {"kind": "share"}
RATIO = [
    {"effective_date": "2010-06-24", "ratio": "10"},
    {"effective_date": "2024-01-24", "ratio": "20", "credit_date": "2024-01-26"},
]
CEDEAR = {"kind": "cedear", "underlying": "AAPL", "ratio_history": RATIO}


def _bars(days, closes, volume=1000.0):
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [volume] * len(days),
        },
        index=pd.DatetimeIndex(days),
    )
    frame.attrs["quote_currency"] = "ARS"
    return frame


def _fill(symbol, action, bar_idx, day, qty, price=100.0, fee=0.0):
    return SimpleNamespace(
        symbol=symbol,
        action=action,
        bar_idx=bar_idx,
        timestamp=pd.Timestamp(day),
        signed_quantity=qty,
        execution_price=price,
        fee=fee,
    )


def _engine(instruments=None, **config):
    engine = ArgentinaEquityEngine(
        {
            "initial_cash": 1000,
            "ar_tick_table": "2024-07-04",
            **config,
            "ar_instruments": instruments or {"YPFD.BA": SHARE},
        }
    )
    engine.describe_instrument = lambda symbol: None
    return engine


def _prepared(instruments, frames, **config):
    engine = _engine(instruments, **config)
    engine.prepare_market_data(frames)
    return engine


# ── configuration ──


def test_configuration_problems_are_reported_together():
    with pytest.raises(ValueError) as err:
        ArgentinaEquityEngine(
            {
                "ar_instruments": {
                    "YPFD.BA": {"kind": "acciones", "lot_size": 0},
                    "AAPL.BA": {"kind": "cedear"},
                    "GGALD.BA": {"kind": "share", "currency": "USD"},
                }
            }
        )
    message = str(err.value)
    for expected in (
        "YPFD.BA.kind must be",
        "YPFD.BA.lot_size must be",
        "AAPL.BA.underlying is required",
        "AAPL.BA.ratio_history",
        "GGALD.BA.currency: only ARS",
        'do not set "engine"',
    ):
        assert expected in message


def test_long_only_and_cost_validation():
    with pytest.raises(ValueError, match="long-only"):
        ArgentinaEquityEngine({"allow_short": True})
    with pytest.raises(ValueError, match="finite nonnegative"):
        ArgentinaEquityEngine({"ar_fixed_fee": -1})


def test_generic_commission_is_the_brokerage_rate_unless_declared():
    assert (
        ArgentinaEquityEngine({"commission": 0.001}).fee_basis["brokerage_source"]
        == "commission"
    )
    engine = ArgentinaEquityEngine({"commission": 0.001, "ar_brokerage_rate": 0.002})
    assert engine.brokerage_rate == 0.002
    assert ArgentinaEquityEngine({}).fee_basis["brokerage_source"] == "none configured"


def test_undeclared_cedear_and_unknown_kind_fail_closed():
    days = ["2024-06-03", "2024-06-04"]
    engine = ArgentinaEquityEngine({})
    engine.describe_instrument = lambda s: "APPLE INC CEDEAR(REPR 1/20 SHR)"
    with pytest.raises(ValueError, match="names a CEDEAR"):
        engine.prepare_market_data({"AAPL.BA": _bars(days, [1.0, 1.0])})
    engine.describe_instrument = lambda s: "STATE ST SPDR S&P 500 ETF TR CE"
    with pytest.raises(ValueError, match="may be truncated"):
        engine.prepare_market_data({"SPY.BA": _bars(days, [1.0, 1.0])})


# ── units ──


@pytest.mark.parametrize(
    "price,tick",
    [
        ("1", "0.001"),
        ("1.01", "0.005"),
        ("250", "0.25"),
        ("26000", "25.00"),
        ("50000.01", "50.00"),
    ],
)
def test_tick_bands(price, tick):
    assert equity_tick(Decimal(price)) == Decimal(tick)


def test_lots_and_ticks_are_real_certificates_before_a_ratio_change():
    days = ["2024-01-22", "2024-01-23", "2024-01-24", "2024-01-25"]
    engine = _prepared(
        {"AAPL.BA": CEDEAR},
        {"AAPL.BA": _bars(days, [25000.0, 25000.0, 12500.0, 12500.0])},
    )
    engine._active_symbol = "AAPL.BA"
    engine._bar_ts = pd.Timestamp("2024-01-23")
    assert engine.round_size(9.9, 12500.0) == 8.0  # 4 real certificates = 8 units
    assert engine.apply_slippage(12500.15, 1) == pytest.approx(
        12512.5
    )  # real tick 25 / 2
    engine._bar_ts = pd.Timestamp("2024-01-24")
    assert engine.round_size(9.9, 12500.0) == 9.0
    assert engine.calc_commission(8, 12500.0, 1, True) == engine.calc_commission(
        4, 25000.0, 1, True
    )


# ── settlement in observed sessions ──


def test_settlement_lag_switches_to_t1_on_2024_05_27():
    assert normal_cash_lag(date(2024, 5, 24)) == 2
    assert normal_cash_lag(date(2024, 5, 27)) == 1


@pytest.mark.parametrize("day,lag", [("2024-05-20", 2), ("2024-06-03", 1)])
def test_normal_settlement_does_not_forbid_reselling_acquired_shares(day, lag):
    engine = _engine()
    engine.positions["YPFD.BA"] = object()
    engine.fill_records = [_fill("YPFD.BA", "open", 5, day, 10)]
    for bars_later in range(lag + 1):
        engine._bar_idx = 5 + bars_later
        assert argentina_sell_allowed(engine, engine, "YPFD.BA", pd.Timestamp(day))


def test_a_scale_in_does_not_freeze_the_position():
    engine = _engine()
    engine.positions["YPFD.BA"] = object()
    engine.fill_records = [
        _fill("YPFD.BA", "open", 0, "2024-06-03", 10),
        _fill("YPFD.BA", "increase", 3, "2024-06-06", 5),
    ]
    engine._bar_idx = 3
    assert argentina_sell_allowed(engine, engine, "YPFD.BA", pd.Timestamp("2024-06-06"))
    engine._bar_idx = 4
    assert argentina_sell_allowed(engine, engine, "YPFD.BA", pd.Timestamp("2024-06-07"))


def test_buying_power_excludes_only_sales_settling_after_the_purchase():
    engine = _engine()
    engine.capital = 2000.0
    # T+2 sale on bar 4 (settles bar 6); a T+1 purchase on bar 5 settles bar 6: usable.
    engine.fill_records = [_fill("YPFD.BA", "close", 4, "2024-05-24", -10)]
    engine._bar_idx = 5
    assert (
        argentina_available_cash(engine, engine, pd.Timestamp("2024-05-27")) == 2000.0
    )
    # A T+1 sale and a T+1 purchase on the same bar settle together: usable.
    engine._bar_idx = 3
    engine.fill_records = [_fill("YPFD.BA", "close", 3, "2024-06-03", -10, fee=1.0)]
    assert (
        argentina_available_cash(engine, engine, pd.Timestamp("2024-06-03")) == 2000.0
    )
    # A sale settling on bar 5 cannot fund a purchase settling on bar 4.
    engine.fill_records = [_fill("YPFD.BA", "close", 3, "2024-05-23", -10, fee=1.0)]
    assert argentina_available_cash(
        engine, engine, pd.Timestamp("2024-06-03")
    ) == pytest.approx(2000 - 999)


def test_credit_window_holds_a_position_through_the_ex_date():
    """Synthetic T+1-era change (not an official event): ex Wed 2025-03-19,
    credit Fri 03-21. An ex-date sale's earliest settlement is 03-20: held."""
    engine = _engine(
        {
            "SYN.BA": {
                **CEDEAR,
                "ratio_history": [
                    {"effective_date": "2020-01-02", "ratio": "10"},
                    {
                        "effective_date": "2025-03-19",
                        "ratio": "20",
                        "credit_date": "2025-03-21",
                    },
                ],
            }
        }
    )
    engine.ratio_adjustments = [
        {
            "symbol": "SYN.BA",
            "effective_date": "2025-03-19",
            "credit_date": "2025-03-21",
            "old_ratio": 10.0,
            "new_ratio": 20.0,
        }
    ]
    engine.positions["SYN.BA"] = object()
    engine.fill_records = [_fill("SYN.BA", "open", 0, "2025-03-17", 10)]
    engine._bar_idx = 2
    assert not argentina_sell_allowed(
        engine, engine, "SYN.BA", pd.Timestamp("2025-03-19")
    )
    engine._bar_idx = 3
    assert argentina_sell_allowed(engine, engine, "SYN.BA", pd.Timestamp("2025-03-20"))


def test_terminal_close_can_sell_acquired_shares_before_settlement(tmp_path):
    days = ["2024-06-03", "2024-06-04"]
    engine = _engine()

    class Loader:
        def fetch(self, *a, **k):
            return {"YPFD.BA": _bars(days, [100.0, 100.0])}

    class Signal:
        def generate(self, data_map):
            return {"YPFD.BA": pd.Series([1.0, 1.0], index=data_map["YPFD.BA"].index)}

    import io
    from contextlib import redirect_stdout

    with redirect_stdout(io.StringIO()):
        metrics = engine.run_backtest(
            {
                "codes": ["YPFD.BA"],
                "start_date": days[0],
                "end_date": days[-1],
                "initial_cash": 1000,
                "source": "local",
            },
            Loader(),
            Signal(),
            tmp_path,
        )
    assert [f.action for f in engine.fill_records] == ["open", "close"]
    assert metrics["ar_unliquidated_position_count"] == 0
    assert engine.equity_snapshots[-1].positions == 0


def test_terminal_close_preserves_the_cedear_credit_window(tmp_path):
    days = ["2025-03-17", "2025-03-18", "2025-03-19"]
    instrument = {
        **CEDEAR,
        "ratio_history": [
            {"effective_date": "2020-01-02", "ratio": "10"},
            {
                "effective_date": "2025-03-19",
                "ratio": "20",
                "credit_date": "2025-03-21",
            },
        ],
    }
    engine = _engine({"SYN.BA": instrument})

    class Loader:
        def fetch(self, *args, **kwargs):
            return {"SYN.BA": _bars(days, [100.0, 100.0, 50.0])}

    class Signal:
        def generate(self, data_map):
            return {"SYN.BA": pd.Series(0.8, index=data_map["SYN.BA"].index)}

    metrics = engine.run_backtest(
        {
            "codes": ["SYN.BA"],
            "start_date": days[0],
            "end_date": days[-1],
            "initial_cash": 1000,
            "position_adjustment": "hold",
            "source": "local",
        },
        Loader(),
        Signal(),
        tmp_path,
    )
    assert [f.action for f in engine.fill_records] == ["open"]
    assert metrics["ar_unliquidated_position_count"] == 1
    assert engine.equity_snapshots[-1].positions == 1
    assert metrics["final_value"] == pytest.approx(1000)


@pytest.mark.parametrize(
    "table,price,tick",
    [
        ("2025-09-08-leader", "10.01", ".01"),
        ("2025-09-08-leader", "1000.01", "1"),
        ("2025-09-08-leader", "50000.01", "25"),
        ("2025-09-08-general", "100.01", ".50"),
        ("2025-09-08-general", "800.01", "2.5"),
        ("2025-09-08-general", "50000", "50"),
    ],
)
def test_versioned_tick_tables(table, price, tick):
    assert equity_tick(Decimal(price), table) == Decimal(tick)


def test_tick_table_is_declared_instead_of_guessing_panel_or_history():
    frames = {"YPFD.BA": _bars(["2025-10-01"], [100.0])}
    with pytest.raises(ValueError, match="tick_table"):
        _engine(ar_tick_table=None).prepare_market_data(frames)
    engine = _engine({"YPFD.BA": {**SHARE, "tick_size": "0.5"}}, ar_tick_table=None)
    engine.prepare_market_data(frames)
    engine._active_symbol = "YPFD.BA"
    engine._bar_ts = pd.Timestamp("2025-10-01")
    assert engine.apply_slippage(100.1, 1) == 100.5


@pytest.mark.parametrize("value", ["NaN", "Infinity", "0", "-1"])
def test_tick_must_be_positive_and_finite(value):
    with pytest.raises(ValueError, match="tick_size"):
        _engine({"YPFD.BA": {**SHARE, "tick_size": value}})


def test_no_leverage_or_nonfinite_discontinuity_threshold():
    with pytest.raises(ValueError, match="leverage"):
        _engine(leverage=2)
    for value in (float("nan"), float("inf"), 0, 1):
        with pytest.raises(ValueError, match="ar_max_share_move"):
            _engine(ar_max_share_move=value)


# ── price basis ──


@pytest.mark.parametrize(
    "name,kind",
    [
        ("YPF SOCIEDAD ANONIMA", "share"),
        ("APPLE INC CEDEAR(REPR 1/20 SHR)", "cedear"),
        ("STATE ST SPDR S&P 500 ETF TR CE", None),
        (None, None),
    ],
)
def test_vendor_classification(name, kind):
    assert classify_short_name(name)[0] == kind


def test_ratio_change_rescaling_and_ambiguity():
    days = ["2024-01-22", "2024-01-23", "2024-01-24", "2024-01-25"]
    raw = _bars(days, [25000.0, 25000.0, 12500.0, 12500.0])
    adjusted, events = reconcile_ratio_changes(raw, "AAPL.BA", RATIO)
    assert (
        events[0]["rescaled_prior_bars"] and adjusted["close"].tolist() == [12500.0] * 4
    )
    _, again = reconcile_ratio_changes(adjusted, "AAPL.BA", RATIO)
    assert not again[0]["rescaled_prior_bars"]
    with pytest.raises(ValueError, match="not provable"):
        reconcile_ratio_changes(
            raw, "AAPL.BA", [RATIO[0], {**RATIO[1], "price_series": "adjusted"}]
        )
    small = [
        RATIO[0],
        {"effective_date": "2024-01-24", "ratio": "11", "credit_date": "2024-01-26"},
    ]
    with pytest.raises(ValueError, match="not provable"):
        reconcile_ratio_changes(_bars(days, [100.0] * 4), "AAPL.BA", small)


def test_discontinuity_bands_allow_real_crashes_but_not_unadjusted_splits():
    days = ["2019-08-08", "2019-08-09", "2019-08-12"]
    assert discontinuities(_bars(days, [174.55, 174.55, 92.4]), 0.75) == []
    assert discontinuities(_bars(days, [8000.0, 8000.0, 800.0]), 0.75) == ["2019-08-12"]


def test_currency_must_be_declared_ars():
    frame = _bars(["2024-06-03"], [1.0])
    frame.attrs = {}
    with pytest.raises(ValueError, match="no quote currency"):
        _engine().prepare_market_data({"YPFD.BA": frame})


def test_only_dates_nobody_traded_are_dropped():
    days = ["2024-06-19", "2024-06-20", "2024-06-24"]
    ypfd = _bars(days, [100.0, 100.0, 101.0])
    ypfd.loc["2024-06-20", "volume"] = 0.0  # holiday placeholder
    ggal = _bars(days, [50.0, 50.0, 51.0])
    ggal.loc["2024-06-20", "volume"] = 0.0
    ggal.loc["2024-06-24", "volume"] = 0.0  # illiquid on an open day
    engine = _engine({"YPFD.BA": SHARE, "GGAL.BA": SHARE})
    prepared = engine.prepare_market_data({"YPFD.BA": ypfd, "GGAL.BA": ggal})
    assert engine.dropped_no_trade_dates == ["2024-06-20"]
    assert list(prepared["GGAL.BA"].index.strftime("%Y-%m-%d")) == [
        "2024-06-19",
        "2024-06-24",
    ]
    stale = prepared["GGAL.BA"].loc["2024-06-24"]
    assert not engine.can_execute("GGAL.BA", 1, stale)  # zero volume: not executable
