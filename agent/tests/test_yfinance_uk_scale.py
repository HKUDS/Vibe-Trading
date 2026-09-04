"""yfinance loader enforces the GBP-only LSE quote contract.

Yahoo-family data serves some LSE names in pence (VOD.L ~117p), some in
pounds, and some in other currencies. The loader normalizes GBp to GBP and
rejects anything that cannot safely enter ``code_currency``'s GBP pool.
"""
from __future__ import annotations

import pandas as pd
import pytest

import backtest.loaders.yfinance_loader as yfl


def _download_frame() -> pd.DataFrame:
    # Penny-scale LSE close: 117.5p.
    return pd.DataFrame(
        {
            "Open": [117.0, 118.0],
            "High": [118.5, 119.0],
            "Low": [116.0, 117.0],
            "Close": [117.5, 118.5],
            "Volume": [100, 200],
        },
        index=pd.DatetimeIndex(["2025-01-02", "2025-01-03"], name="Date"),
    )


def test_fetch_scales_lse_pence_to_gbp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["VOD.L"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)
    monkeypatch.setattr(yfl, "_declared_currency", lambda symbol: "GBp")

    result = yfl.DataLoader().fetch(["VOD.L"], "2025-01-01", "2025-01-03")

    frame = result["VOD.L"]
    # 117.5p -> £1.175; volume untouched.
    assert frame["close"].iloc[0] == pytest.approx(1.175)
    assert frame["high"].iloc[1] == pytest.approx(1.19)
    assert frame["low"].iloc[0] == pytest.approx(1.16)
    assert frame["volume"].iloc[0] == 100
    assert frame.attrs == {
        "quote_currency": "GBP",
        "currency_conversion": "GBp→GBP (÷100)",
    }


def test_fetch_scales_other_lse_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["BARC.L"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)
    monkeypatch.setattr(yfl, "_declared_currency", lambda symbol: "GBp")

    result = yfl.DataLoader().fetch(["BARC.L"], "2025-01-01", "2025-01-03")

    assert result["BARC.L"]["close"].iloc[0] == pytest.approx(1.175)


def test_fetch_leaves_us_prices_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["AAPL"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)

    result = yfl.DataLoader().fetch(["AAPL.US"], "2025-01-01", "2025-01-03")

    assert result["AAPL.US"]["close"].iloc[0] == pytest.approx(117.5)


def test_fetch_leaves_gbp_quoted_lse_unscaled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reviewer finding: .L is not uniformly GBp — VUSA.L is priced GBP and
    # must NOT be ÷100'd. Scale only on the declared currency.
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["VUSA.L"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)
    monkeypatch.setattr(yfl, "_declared_currency", lambda symbol: "GBP")

    result = yfl.DataLoader().fetch(["VUSA.L"], "2025-01-01", "2025-01-03")

    frame = result["VUSA.L"]
    assert frame["close"].iloc[0] == pytest.approx(117.5)  # untouched
    assert frame.attrs == {
        "quote_currency": "GBP",
        "currency_conversion": "none",
    }


def test_fetch_rejects_usd_quoted_lse_line(monkeypatch: pytest.MonkeyPatch) -> None:
    # VUSD.L is USD-priced. Passing it unscaled would still label the values GBP
    # in the composite and shadow-accounting layers.
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["VUSD.L"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)
    monkeypatch.setattr(yfl, "_declared_currency", lambda symbol: "USD")

    result = yfl.DataLoader().fetch(["VUSD.L"], "2025-01-01", "2025-01-03")

    assert "VUSD.L" not in result


def test_fetch_fails_closed_when_currency_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without metadata, 117.5 could mean GBP 117.50 or GBp 117.5. Returning it
    # under either assumption is unsafe, so the symbol must be omitted.
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["VOD.L"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)
    monkeypatch.setattr(yfl, "_declared_currency", lambda symbol: None)

    result = yfl.DataLoader().fetch(["VOD.L"], "2025-01-01", "2025-01-03")

    assert "VOD.L" not in result


def test_fetch_scales_only_on_gbp_pence(monkeypatch: pytest.MonkeyPatch) -> None:
    # GBp remains the only scaling trigger: real pence names still ÷100.
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["VOD.L"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)
    monkeypatch.setattr(yfl, "_declared_currency", lambda symbol: "GBp")

    result = yfl.DataLoader().fetch(["VOD.L"], "2025-01-01", "2025-01-03")

    frame = result["VOD.L"]
    assert frame["close"].iloc[0] == pytest.approx(1.175)  # still scaled


def test_fetch_declared_currency_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_offline(_symbol: str):
        raise RuntimeError("offline")

    monkeypatch.setattr(yfl.yf, "Ticker", raise_offline)

    assert yfl._declared_currency("VOD.L") is None
