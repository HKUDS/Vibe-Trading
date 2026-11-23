"""Calendar-backed completeness refuses a tail, duplicates and missing sessions."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from src.data_gateway.history_source import fetch_chunk


class Result:
    error_code = "0"

    def __init__(self, records):
        self.records = iter(records)
        self.fields = list(records[0]) if records else []

    def next(self):
        self.current = next(self.records, None)
        return self.current is not None

    def get_row_data(self):
        return [self.current[key] for key in self.fields]


@pytest.mark.parametrize("interval,frequency", [("5m", 5), ("15m", 15), ("30m", 30), ("1H", 60)])
@pytest.mark.parametrize("fault", [None, "missing_bar", "duplicate", "calendar_gap", "daily_gap", "wrong_symbol"])
def test_exact_grid(interval, frequency, fault, monkeypatch):
    import baostock
    import backtest.loaders.baostock_loader as loader

    @contextmanager
    def guard(*args):
        yield True

    monkeypatch.setattr(loader, "_baostock_socket_guard", guard)
    monkeypatch.setattr(baostock, "login", lambda: SimpleNamespace(error_code="0"))
    monkeypatch.setattr(baostock, "logout", lambda: None)
    monkeypatch.setattr(
        baostock,
        "query_trade_dates",
        lambda **kw: Result(
            [] if fault == "calendar_gap" else [{"calendar_date": "2021-11-15", "is_trading_day": "1"}]
        ),
    )
    minute = []
    for hour, minute_value in [(9, 30), (13, 0)]:
        base = datetime(2021, 11, 15, hour, minute_value)
        for offset in range(frequency, 121, frequency):
            minute.append(
                {
                    "date": "2021-11-15",
                    "time": (base + timedelta(minutes=offset)).strftime("%Y%m%d%H%M%S") + "000",
                    "code": "sh.601398",
                    "open": "4",
                    "high": "5",
                    "low": "3",
                    "close": "4",
                    "volume": "100",
                    "amount": "400",
                    "adjustflag": "3",
                }
            )
    if fault == "missing_bar":
        minute.pop(0)
    if fault == "duplicate":
        minute.append(minute[0])
    if fault == "wrong_symbol":
        minute[0] = {**minute[0], "code": "sz.000001"}
    daily = [] if fault == "daily_gap" else [{"date": "2021-11-15", "code": "sh.601398", "tradestatus": "1"}]
    monkeypatch.setattr(
        baostock, "query_history_k_data_plus", lambda *args, **kw: Result(daily if kw["frequency"] == "d" else minute)
    )
    if fault:
        with pytest.raises(ValueError):
            fetch_chunk("601398.SH", "2021-11-15", "2021-11-15", interval)
    else:
        data, meta = fetch_chunk("601398.SH", "2021-11-15", "2021-11-15", interval)
        assert len(data) == 240 // frequency and meta["coverage"] == "calendar_daily_status_and_exact_intraday_grid"


def test_sdk_notices_do_not_redirect_other_threads_or_mcp_stdout(capsys):
    import threading
    from importlib import import_module
    sdk = import_module("baostock.login.loginout")
    from src.data_gateway.history_source import _sdk_output

    missing = not hasattr(sdk, "print")
    with _sdk_output():
        sdk.print("login success!")
        thread = threading.Thread(target=lambda: print("protocol response"))
        thread.start()
        thread.join()
    assert capsys.readouterr().out == "protocol response\n"
    assert hasattr(sdk, "print") is not missing


def test_history_session_has_one_aggregate_deadline_and_restores_parent(monkeypatch):
    import time
    from backtest.loaders.base import source_background, source_deadline
    from src.data_gateway.history_source import _background_session

    monkeypatch.setattr("backtest.loaders.baostock_loader._read_timeout", lambda: 0.05)
    seen = []

    @_background_session
    def operation():
        seen.append((source_deadline.get(), source_background.get()))
        raise ConnectionError("bounded failure")

    start = time.monotonic()
    with pytest.raises(ConnectionError):
        operation()
    assert start < seen[-1][0] <= time.monotonic() + 0.05
    assert seen[-1][1] is True and source_deadline.get() is None and source_background.get() is False
    parent = time.monotonic() + 0.01
    token = source_deadline.set(parent)
    try:
        with pytest.raises(ConnectionError):
            operation()
        assert seen[-1][0] == parent and source_deadline.get() == parent
    finally:
        source_deadline.reset(token)
