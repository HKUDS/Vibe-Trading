"""Bounded settled A-share minute chunks using the existing BaoStock transport."""

from contextlib import contextmanager
from functools import wraps
from importlib import import_module
import logging
from datetime import date, datetime, timedelta
import math
import re
import time


@contextmanager
def _sdk_output():
    """Route SDK notices to logging under its session lock, never sys.stdout.

    MCP uses stdout as its protocol transport. Module-local print hooks avoid
    process-wide redirect_stdout, which would also capture unrelated threads.
    The caller must hold the existing BaoStock session guard.
    """
    missing = object()
    modules = [
        import_module(name)
        for name in (
            "baostock.login.loginout",
            "baostock.security.history",
            "baostock.data.resultset",
        )
    ]
    saved = [(module, getattr(module, "print", missing)) for module in modules]

    def notice(*args, **kwargs):
        logging.getLogger(__name__).debug("BaoStock: %s", " ".join(map(str, args))[:200])

    try:
        for module in modules:
            module.print = notice
        yield
    finally:
        for module, original in saved:
            if original is missing:
                del module.print
            else:
                module.print = original


def _background_session(function):
    @wraps(function)
    def call(*args, **kwargs):
        from backtest.loaders.base import source_background, source_deadline
        from backtest.loaders.baostock_loader import _read_timeout

        token = source_background.set(True)
        # Bound the whole calendar/status/minute transaction, not each message
        # independently. Cancellation is checked before the next route/attempt.
        until = time.monotonic() + _read_timeout()
        inherited = source_deadline.get()
        deadline_token = source_deadline.set(min(until, inherited) if inherited is not None else until)
        try:
            return function(*args, **kwargs)
        finally:
            source_deadline.reset(deadline_token)
            source_background.reset(token)

    return call


@_background_session
def fetch_chunk(symbol: str, start: str, end: str, interval: str):
    """Fetch one month and check every bar against calendar and daily status.

    Args:
        symbol: Canonical mainland equity code, e.g. 601398.SH.
        start: Inclusive first calendar date.
        end: Inclusive last calendar date (settled, not today).
        interval: 5m/15m/30m/1H.

    Returns:
        Rows and source provenance; raises on omissions or inconsistent data.
    """
    import baostock as bs
    from backtest.loaders.baostock_loader import _baostock_socket_guard, _read_timeout

    frequency = {"5m": 5, "15m": 15, "30m": 30, "1H": 60}[interval]
    if not re.fullmatch(r"\d{6}\.(SH|SZ)", symbol):
        raise ValueError("Historical minute adapter requires an SH/SZ equity")
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 31:
        raise ValueError("Chunk exceeds one month")
    code, venue = symbol.split(".")
    native = venue.lower() + "." + code

    def rows(result):
        values = []
        while result.error_code == "0" and result.next():
            values.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
            if len(values) > 10000:
                raise ValueError("Source chunk row limit exceeded")
        if result.error_code != "0":
            raise ConnectionError("BaoStock query failed (code " + str(result.error_code) + ")")
        return values

    with _baostock_socket_guard(_read_timeout()) as acquired:
        if not acquired:
            raise TimeoutError("BaoStock session busy")
        with _sdk_output():
            login = bs.login()
            if login.error_code != "0":
                raise ConnectionError("BaoStock login failed")
            try:
                calendar = rows(bs.query_trade_dates(start_date=start, end_date=end))
                # Missing calendar dates themselves must not become missing sessions.
                expected_dates = {
                    str(date.fromisoformat(start) + timedelta(days=i))
                    for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
                }
                if {row["calendar_date"] for row in calendar} != expected_dates:
                    raise ValueError("Source calendar does not cover the chunk")
                sessions = {row["calendar_date"] for row in calendar if row["is_trading_day"] == "1"}
                daily = rows(
                    bs.query_history_k_data_plus(
                        native,
                        "date,code,open,high,low,close,volume,tradestatus",
                        start_date=start,
                        end_date=end,
                        frequency="d",
                        adjustflag="3",
                    )
                )
                if {row["date"] for row in daily} != sessions:
                    raise ValueError("Missing daily status: cannot certify intraday coverage")
                raw = rows(
                    bs.query_history_k_data_plus(
                        native,
                        "date,time,code,open,high,low,close,volume,amount,adjustflag",
                        start_date=start,
                        end_date=end,
                        frequency=str(frequency),
                        adjustflag="3",
                    )
                )
            finally:
                bs.logout()
    expected = set()
    for row in daily:
        if row["code"] != native or row["tradestatus"] not in {"0", "1"}:
            raise ValueError("Invalid daily identity/status")
        if row["tradestatus"] == "1":
            for hour, minute in ((9, 30), (13, 0)):
                base = datetime.fromisoformat(row["date"]).replace(hour=hour, minute=minute)
                expected.update((base + timedelta(minutes=m)).isoformat() for m in range(frequency, 121, frequency))
    output, observed = [], set()
    for row in raw:
        stamp = datetime.strptime(row["time"], "%Y%m%d%H%M%S%f").isoformat()
        if row["code"] != native or row["adjustflag"] != "3" or stamp[:10] != row["date"] or stamp in observed:
            raise ValueError("Invalid or duplicate minute identity")
        numbers = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume", "amount")}
        if not all(math.isfinite(n) and n >= 0 for n in numbers.values()):
            raise ValueError("Invalid minute numeric value")
        if numbers["low"] > min(numbers["open"], numbers["close"]) or numbers["high"] < max(
            numbers["open"], numbers["close"]
        ):
            raise ValueError("Invalid OHLC ordering")
        observed.add(stamp)
        output.append({"symbol": symbol, "time": stamp, **numbers})
    if observed != expected:
        raise ValueError(
            f"Incomplete minute grid: missing={len(expected - observed)}, unexpected={len(observed - expected)}"
        )
    output.sort(key=lambda row: row["time"])
    return output, {
        "source": "baostock",
        "adjustment": "raw",
        "quote_currency": "CNY",
        "volume_unit": "shares",
        "timezone": "Asia/Shanghai",
        "timestamp_basis": "bar_end",
        "coverage": "calendar_daily_status_and_exact_intraday_grid",
        "sessions": len(sessions),
        "suspended_sessions": sum(row["tradestatus"] == "0" for row in daily),
    }
