"""yfinance download always requests the adjusted series (qfq caliber)."""

from __future__ import annotations

from backtest.loaders import yfinance_loader as yfl


def test_download_history_requests_auto_adjust(monkeypatch):
    captured = {}

    def fake_download(tickers, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(yfl.yf, "download", fake_download)

    yfl._download_history("AAPL", "2026-01-01", "2026-01-31", "1d")

    assert captured["auto_adjust"] is True
    assert captured["interval"] == "1d"
