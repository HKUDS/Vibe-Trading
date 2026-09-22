"""Tests for Tencent's daily-only market-data contract."""

from __future__ import annotations

import json
import urllib.request

import pandas as pd
import pytest

from backtest.loaders import tencent_loader


class _FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _hk_kline_payload(tencent_code: str) -> str:
    return json.dumps(
        {
            "code": 0,
            "data": {
                tencent_code: {
                    "day": [
                        ["2026-01-05", "466.4", "471.8", "475.0", "462.8", "31791979"],
                        ["2026-01-06", "470.0", "475.2", "479.8", "462.0", "31100240"],
                    ]
                }
            },
        }
    )


def _patch_http(monkeypatch, urls: list[str], payload: str) -> None:
    def fake_urlopen(req, timeout=None, **kwargs):  # noqa: ANN001, ANN002
        urls.append(req.full_url)
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        tencent_loader,
        "cached_loader_fetch",
        lambda **kwargs: kwargs["fetch"](),
    )


def test_intraday_request_does_not_return_daily_bars(monkeypatch) -> None:
    calls: list[str] = []
    daily = pd.DataFrame(
        {
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-05")]),
    )
    loader = tencent_loader.DataLoader()
    monkeypatch.setattr(
        tencent_loader,
        "cached_loader_fetch",
        lambda **kwargs: kwargs["fetch"](),
    )
    monkeypatch.setattr(
        loader,
        "_fetch_one",
        lambda code, start, end: calls.append(code) or daily,
    )

    result = loader.fetch(
        ["600519.SH"],
        "2026-01-01",
        "2026-01-31",
        interval="1m",
    )

    assert result == {}
    assert calls == []


def test_hk_equity_maps_to_hk_prefix_and_parses(monkeypatch) -> None:
    urls: list[str] = []
    _patch_http(monkeypatch, urls, _hk_kline_payload("hk00700"))

    result = tencent_loader.DataLoader().fetch(
        ["00700.HK"], "2026-01-01", "2026-01-31",
    )

    assert len(urls) == 1
    assert "param=hk00700,day," in urls[0]
    df = result["00700.HK"]
    assert len(df) == 2
    # Tencent kline rows are [date, open, close, high, low, volume].
    assert df.iloc[0]["open"] == 466.4
    assert df.iloc[0]["close"] == 471.8
    assert df.iloc[0]["high"] == 475.0
    assert df.iloc[0]["low"] == 462.8


def test_short_hk_code_is_zero_padded(monkeypatch) -> None:
    urls: list[str] = []
    _patch_http(monkeypatch, urls, _hk_kline_payload("hk00700"))

    result = tencent_loader.DataLoader().fetch(
        ["700.HK"], "2026-01-01", "2026-01-31",
    )

    assert "param=hk00700,day," in urls[0]
    assert "700.HK" in result


def _daily_page(dates: list[str]) -> pd.DataFrame:
    """Build a normalized daily frame indexed by trade date."""
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "open": [1.0] * len(index),
            "high": [1.0] * len(index),
            "low": [1.0] * len(index),
            "close": [1.0] * len(index),
            "volume": [1.0] * len(index),
        },
        index=index,
    )


def _history(start: str, n_days: int) -> pd.DataFrame:
    """A synthetic daily history of `n_days` consecutive calendar days."""
    dates = pd.date_range(start, periods=n_days, freq="D")
    return _daily_page([d.strftime("%Y-%m-%d") for d in dates])


def _last500_api(history: pd.DataFrame, requested_ends: list[str] | None = None):
    """Fake `_request_page` honouring the REAL Tencent fqkline contract.

    The API serves the LAST ≤_PAGE_SIZE bars of [start, end], not the first
    (verified live 2026-09-11). The previous mocks in this file encoded the
    opposite first-500 assumption, which is why tail truncation passed CI.
    """

    def fake_page(code, start, end, forward_adjusted=True):  # noqa: ANN001
        if requested_ends is not None:
            requested_ends.append(end)
        window = history.loc[
            (history.index >= pd.Timestamp(start))
            & (history.index <= pd.Timestamp(end))
        ]
        return window.iloc[-tencent_loader._PAGE_SIZE:]

    return fake_page


def test_multiyear_window_is_served_in_full(monkeypatch) -> None:
    """Regression: a >500-bar window must not degrade to its most recent 500.

    Under the real last-500 semantics, forward pagination (advancing the
    start cursor) exits after one page holding only the window's tail. The
    backward walk must serve every bar from start_date through end_date.
    """
    loader = tencent_loader.DataLoader()
    history = _history("2018-01-01", 1500)
    end_date = history.index.max().strftime("%Y-%m-%d")
    ends: list[str] = []
    monkeypatch.setattr(loader, "_request_page", _last500_api(history, ends))

    df = loader._fetch_one("600519.SH", "2018-01-01", end_date)

    assert len(df) == 1500
    assert df.index.min() == pd.Timestamp("2018-01-01")
    assert df.index.max() == history.index.max()
    assert df.index.is_monotonic_increasing
    assert len(ends) == 3
    assert ends[0] == end_date
    assert ends[1] < ends[0]
    assert ends[2] < ends[1]


def test_pagination_moves_the_end_cursor_behind_each_page(monkeypatch) -> None:
    """Next request's end = the day before the current page's oldest bar."""
    loader = tencent_loader.DataLoader()
    history = _history("2020-01-01", tencent_loader._PAGE_SIZE + 2)
    ends: list[str] = []
    monkeypatch.setattr(loader, "_request_page", _last500_api(history, ends))

    df = loader._fetch_one("600519.SH", "2020-01-01", "2021-12-31")

    assert len(df) == tencent_loader._PAGE_SIZE + 2
    first_page_oldest = history.index[-tencent_loader._PAGE_SIZE]
    expected_next_end = first_page_oldest - pd.Timedelta(days=1)
    assert ends[1] == expected_next_end.strftime("%Y-%m-%d")


def test_overlapping_pages_are_deduplicated(monkeypatch) -> None:
    """Rows repeated across pages must collapse, not double-count."""
    loader = tencent_loader.DataLoader()
    history = _history("2020-01-01", tencent_loader._PAGE_SIZE)
    calls = {"n": 0}

    def fake_page(code, start, end, forward_adjusted=True):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return history.iloc[-tencent_loader._PAGE_SIZE:]
        older = _daily_page(["2019-12-31"])
        return pd.concat([older, history.iloc[:2]])

    monkeypatch.setattr(loader, "_request_page", fake_page)
    df = loader._fetch_one("600519.SH", "2019-12-01", "2021-12-31")

    assert df.index.duplicated().sum() == 0
    assert len(df) == tencent_loader._PAGE_SIZE + 1


def test_exhausting_the_page_cap_raises_instead_of_truncating(monkeypatch) -> None:
    """Hitting _MAX_PAGES must fail loudly, like the other bounded loaders."""
    loader = tencent_loader.DataLoader()
    endless = _history("1990-01-01", 20000)
    monkeypatch.setattr(loader, "_request_page", _last500_api(endless))

    with pytest.raises(ValueError, match="incomplete tencent history"):
        loader._fetch_one("600519.SH", "1990-01-01", "2026-12-31")


def test_a_failed_page_raises_instead_of_returning_partial_history(
    monkeypatch,
) -> None:
    """A network failure mid-walk must not read downstream as a short series."""
    loader = tencent_loader.DataLoader()
    history = _history("2020-01-01", tencent_loader._PAGE_SIZE + 10)
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_page(code, start, end, forward_adjusted=True):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return history.iloc[-tencent_loader._PAGE_SIZE:]
        raise OSError("connection reset")

    monkeypatch.setattr(loader, "_request_page", fake_page)
    monkeypatch.setattr(tencent_loader.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="incomplete tencent history"):
        loader._fetch_one("600519.SH", "2020-01-01", "2021-12-31")

    # One good page, then the retry budget spent on the failing one.
    assert calls["n"] == 1 + tencent_loader._PAGE_RETRIES
    assert len(sleeps) == tencent_loader._PAGE_RETRIES - 1


def test_a_short_page_ends_the_walk(monkeypatch) -> None:
    """A page below the cap means the window is served; stop requesting."""
    loader = tencent_loader.DataLoader()
    history = _history("2026-01-05", 2)
    ends: list[str] = []
    monkeypatch.setattr(loader, "_request_page", _last500_api(history, ends))

    df = loader._fetch_one("600519.SH", "2026-01-01", "2026-01-31")

    assert ends == ["2026-01-31"]
    assert len(df) == 2


def test_a_bar_on_the_end_date_itself_is_not_dropped(monkeypatch) -> None:
    """A bar dated exactly end_date must be part of the served series."""
    loader = tencent_loader.DataLoader()
    history = _history("2020-01-01", tencent_loader._PAGE_SIZE + 1)
    end_date = history.index.max().strftime("%Y-%m-%d")
    monkeypatch.setattr(loader, "_request_page", _last500_api(history))

    df = loader._fetch_one("600519.SH", "2020-01-01", end_date)

    assert df.index.max() == history.index.max()
    assert len(df) == tencent_loader._PAGE_SIZE + 1


def test_error_shaped_reply_raises_instead_of_returning_none(monkeypatch) -> None:
    """A non-zero-code reply with no payload is a failure, not an empty window."""
    loader = tencent_loader.DataLoader()
    payload = json.dumps({"code": 1, "msg": "rate limit"})

    def fake_urlopen(req, timeout=None, **kwargs):  # noqa: ANN001, ANN002
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="error reply"):
        loader._request_page("600519.SH", "2024-01-01", "2024-06-30")


def test_midwalk_empty_page_is_rerequested_before_truncating(monkeypatch) -> None:
    """A glitched empty mid-walk must not end the walk: one re-request decides."""
    loader = tencent_loader.DataLoader()
    history = _history("2020-01-01", tencent_loader._PAGE_SIZE + 10)
    calls = {"n": 0}
    sleeps: list[float] = []
    monkeypatch.setattr(tencent_loader.time, "sleep", sleeps.append)

    def fake_page(code, start, end, forward_adjusted=True):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return history.iloc[-tencent_loader._PAGE_SIZE:]
        if calls["n"] == 2:
            return None
        return history.iloc[: -tencent_loader._PAGE_SIZE]

    monkeypatch.setattr(loader, "_request_page", fake_page)
    df = loader._fetch_one("600519.SH", "2020-01-01", "2026-12-31")

    assert calls["n"] == 3
    assert len(df) == tencent_loader._PAGE_SIZE + 10
    assert df.index.is_monotonic_increasing
    assert sleeps == [tencent_loader._PAGE_BACKOFF]


def test_midwalk_empty_page_that_persists_ends_the_walk(monkeypatch) -> None:
    """A genuine data start (e.g. a pre-IPO window) stays empty on re-request."""
    loader = tencent_loader.DataLoader()
    history = _history("2020-01-01", tencent_loader._PAGE_SIZE)
    calls = {"n": 0}
    sleeps: list[float] = []
    monkeypatch.setattr(tencent_loader.time, "sleep", sleeps.append)

    def fake_page(code, start, end, forward_adjusted=True):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return history.iloc[-tencent_loader._PAGE_SIZE:]
        return None

    monkeypatch.setattr(loader, "_request_page", fake_page)
    df = loader._fetch_one("600519.SH", "2019-01-01", "2026-12-31")

    assert calls["n"] == 3
    assert len(df) == tencent_loader._PAGE_SIZE
