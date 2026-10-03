"""Tests for the Tiingo US-equity OHLCV loader.

All HTTP is mocked at :func:`backtest.loaders._http.throttled_get_json` (imported
into the loader module as ``throttled_get_json``), so no test touches a live
Tiingo endpoint.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from backtest.loaders.tiingo_loader import (
    DataLoader,
    _resolve_key,
    _rows_to_frame,
    _to_tiingo_symbol,
)


# ---------------------------------------------------------------------------
# Symbol mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        ("AAPL.US", "aapl"),
        ("AAPL", "aapl"),
        ("msft", "msft"),
        ("BRK", "brk"),
        ("00700.HK", None),  # HK suffix
        ("000001.SZ", None),  # A-share suffix
        ("BTC-USDT", None),  # crypto pair
        ("", None),
    ],
)
def test_to_tiingo_symbol(code: str, expected) -> None:
    assert _to_tiingo_symbol(code) == expected


# ---------------------------------------------------------------------------
# Key resolution / availability
# ---------------------------------------------------------------------------


def test_is_available_false_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    assert DataLoader().is_available() is False


def test_is_available_false_for_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "your_tiingo_api_key")
    assert DataLoader().is_available() is False
    assert _resolve_key() == ""


def test_is_available_true_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "real-token-123")
    assert DataLoader().is_available() is True


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------


def _sample_rows() -> list[dict]:
    return [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 187.15,
            "high": 188.44,
            "low": 183.89,
            "close": 185.64,
            "volume": 82488700,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 184.22,
            "high": 185.88,
            "low": 183.43,
            "close": 184.25,
            "volume": 58414500,
        },
    ]


def test_rows_to_frame_shape_and_dtypes() -> None:
    df = _rows_to_frame(_sample_rows())
    assert df is not None
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "trade_date"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is None
    assert all(str(df[col].dtype) == "float64" for col in df.columns)
    assert len(df) == 2
    assert df.index[0] == pd.Timestamp("2024-01-02")


def test_rows_to_frame_empty_returns_none() -> None:
    assert _rows_to_frame([]) is None
    assert _rows_to_frame([{"open": 1.0}]) is None  # no date field


def test_rows_to_frame_drops_rows_missing_ohlc() -> None:
    rows = _sample_rows() + [{"date": "2024-01-04T00:00:00.000Z", "volume": 100}]
    df = _rows_to_frame(rows)
    assert df is not None
    assert len(df) == 2  # row with no OHLC dropped


def test_rows_with_incomplete_adjusted_ohlc_do_not_mix_price_bases() -> None:
    rows = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 50, "adjHigh": 50.5, "adjLow": 49.5, "adjClose": 50,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": None, "adjHigh": None, "adjLow": None, "adjClose": None,
        },
    ]

    df = _rows_to_frame(rows)

    assert df is not None
    # This loader promises split/dividend-adjusted prices, so reject the row
    # without adjusted prices rather than fabricate a 100% return from raw data.
    assert list(df["close"]) == [50.0]


def test_zero_adjusted_ohlc_is_rejected_not_priced() -> None:
    rows = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 50, "adjHigh": 50.5, "adjLow": 49.5, "adjClose": 50,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 0, "adjHigh": 0, "adjLow": 0, "adjClose": 0,
        },
    ]

    df = _rows_to_frame(rows)

    assert df is not None
    # A zero-adjusted bar is not a price: accepting it fabricates a -100% bar.
    assert list(df["close"]) == [50.0]


def test_an_all_unusable_adjusted_response_stays_one_raw_basis() -> None:
    rows = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 0, "adjHigh": 0, "adjLow": 0, "adjClose": 0,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 101, "high": 102, "low": 100, "close": 101, "volume": 1000,
            "adjOpen": 0, "adjHigh": 0, "adjLow": 0, "adjClose": 0,
        },
    ]

    df = _rows_to_frame(rows)

    # No bar carries a usable adjustment, so the series stays consistently raw
    # (one basis) rather than being discarded or priced at zero.
    assert df is not None
    assert list(df["close"]) == [100.0, 101.0]
    # The static source table stamps tiingo split_dividend; an all-raw
    # response must override that on the frame so frame_caliber reports the
    # basis actually served.
    assert df.attrs["adjustment"] == "raw"


def test_an_adjusted_response_stamps_the_adjusted_basis() -> None:
    rows = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 50.0, "adjHigh": 50.5, "adjLow": 49.5, "adjClose": 50.0,
        },
    ]

    df = _rows_to_frame(rows)

    assert df is not None
    # Both bases carry an explicit stamp; the provenance table must never
    # fall back to the static source default for a served frame.
    assert df.attrs["adjustment"] == "split_dividend"


def test_a_bar_that_cannot_be_emitted_does_not_set_the_adjusted_basis() -> None:
    """A computable factor on an incomplete bar must not claim the basis.

    Such a bar is dropped either way; what it must not do is drag its
    unadjusted siblings down with it, which turned a usable raw series into no
    series at all.
    """
    rows = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": None, "high": 102, "low": 99, "close": 100, "volume": 1000,
            "adjClose": 50,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 101, "high": 103, "low": 100, "close": 101, "volume": 1000,
        },
    ]

    df = _rows_to_frame(rows)

    assert df is not None
    assert list(df["close"]) == [101.0]


def test_a_non_finite_adjusted_price_is_not_served() -> None:
    """An adjusted leg of infinity is not a price: the bar is not adjusted."""
    rows = [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 50, "adjHigh": 50.5, "adjLow": 49.5, "adjClose": 50,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": float("inf"), "adjHigh": 50.5, "adjLow": 49.5, "adjClose": 50,
        },
    ]

    df = _rows_to_frame(rows)

    assert df is not None
    assert list(df["close"]) == [50.0]


def test_a_dropped_row_is_reported_not_truncated_in_silence(caplog) -> None:
    """A long-history symbol can lose old rows to the 0.01-100x factor window."""
    rows = [
        # A 1997-style row: only adjClose is present and its 600x cumulative
        # factor (0.002/1.2) sits below the 0.01 floor, so it cannot join the
        # adjusted series.
        {
            "date": "1997-05-15T00:00:00.000Z",
            "open": 1.0, "high": 1.5, "low": 0.9, "close": 1.2, "volume": 1000,
            "adjClose": 0.002,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
            "adjOpen": 50, "adjHigh": 50.5, "adjLow": 49.5, "adjClose": 50,
        },
    ]

    with caplog.at_level("WARNING", logger="backtest.loaders.tiingo_loader"):
        df = _rows_to_frame(rows)

    assert df is not None
    assert list(df["close"]) == [50.0]
    assert "dropped 1 of 2" in caplog.text


# ---------------------------------------------------------------------------
# fetch() behavior (HTTP mocked)
# ---------------------------------------------------------------------------


def test_fetch_returns_normalized_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "real-token-123")
    with patch(
        "backtest.loaders.tiingo_loader.throttled_get_json",
        return_value=_sample_rows(),
    ) as mock_get:
        out = DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-05")

    assert "AAPL.US" in out
    df = out["AAPL.US"]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "trade_date"
    assert len(df) == 2
    # URL uses the bare lower-cased ticker; key + dates passed as params.
    url = mock_get.call_args.args[0]
    assert url.endswith("/tiingo/daily/aapl/prices")
    params = mock_get.call_args.kwargs["params"]
    assert params["token"] == "real-token-123"
    assert params["startDate"] == "2024-01-01"
    assert params["endDate"] == "2024-01-05"
    assert mock_get.call_args.kwargs["host_key"] == "tiingo"


def test_fetch_without_key_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with patch("backtest.loaders.tiingo_loader.throttled_get_json") as mock_get:
        out = DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-05")
    assert out == {}
    mock_get.assert_not_called()  # no key -> no HTTP


def test_fetch_skips_non_us_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "real-token-123")
    with patch("backtest.loaders.tiingo_loader.throttled_get_json") as mock_get:
        out = DataLoader().fetch(["00700.HK", "BTC-USDT"], "2024-01-01", "2024-01-05")
    assert out == {}
    mock_get.assert_not_called()  # symbols rejected before any request


def test_fetch_one_bad_symbol_does_not_abort_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "real-token-123")

    def fake_get(url, **kwargs):
        if "/aapl/" in url:
            raise RuntimeError("boom")
        return _sample_rows()

    with patch("backtest.loaders.tiingo_loader.throttled_get_json", side_effect=fake_get):
        out = DataLoader().fetch(["AAPL.US", "MSFT.US"], "2024-01-01", "2024-01-05")

    assert "AAPL.US" not in out  # failing symbol skipped
    assert "MSFT.US" in out  # batch continued


def test_fetch_empty_payload_omits_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "real-token-123")
    with patch("backtest.loaders.tiingo_loader.throttled_get_json", return_value=[]):
        out = DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-05")
    assert out == {}


def test_fetch_rejects_bad_date_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "real-token-123")
    with pytest.raises(ValueError):
        DataLoader().fetch(["AAPL.US"], "2024-02-01", "2024-01-01")


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_loader_self_registers() -> None:
    import backtest.loaders.tiingo_loader  # noqa: F401  (import triggers @register)
    from backtest.loaders.registry import LOADER_REGISTRY

    assert "tiingo" in LOADER_REGISTRY
    cls = LOADER_REGISTRY["tiingo"]
    assert cls.markets == {"us_equity"}
    assert cls.requires_auth is True
