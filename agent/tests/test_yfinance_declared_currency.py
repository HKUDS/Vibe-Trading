"""yfinance's declared-currency probe must read the metadata Mapping it returns.

yfinance 1.x (1.7.0 is the locked version) returns ``history_metadata`` as a
lazy ``HistoryMetadata`` Mapping, not a dict. The probe used to require a
dict, so every LSE/BYMA/TSX symbol read as "no currency" and the yfinance
path rejected them all. Existing loader tests stub ``_declared_currency``
itself, which is why that went unseen.
"""

from collections.abc import Mapping

import pandas as pd
import pytest

import backtest.loaders.yfinance_loader as yfl


class _LazyMetadata(Mapping):
    """Stand-in for yfinance.scrapers.history.HistoryMetadata."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class _Ticker:
    metadata: Mapping = _LazyMetadata({})

    def __init__(self, symbol):
        self.symbol = symbol

    @property
    def history_metadata(self):
        return self.metadata


@pytest.mark.parametrize("currency", ["ARS", "GBp", "CAD"])
def test_declared_currency_reads_a_non_dict_mapping(monkeypatch, currency):
    monkeypatch.setattr(_Ticker, "metadata", _LazyMetadata({"currency": currency}))
    monkeypatch.setattr(yfl.yf, "Ticker", _Ticker)
    assert yfl._declared_currency("YPFD.BA") == currency


@pytest.mark.parametrize("metadata", [_LazyMetadata({}), _LazyMetadata({"currency": ""}), None, "ARS"])
def test_missing_or_unusable_currency_is_still_none(monkeypatch, metadata):
    monkeypatch.setattr(_Ticker, "metadata", metadata)
    monkeypatch.setattr(yfl.yf, "Ticker", _Ticker)
    assert yfl._declared_currency("YPFD.BA") is None


def test_byma_fetch_succeeds_with_mapping_metadata(monkeypatch):
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)
    index = pd.DatetimeIndex(["2024-05-27", "2024-05-28"])
    bars = pd.DataFrame(
        {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0],
         "Close": [1.0, 2.0], "Volume": [10, 20]},
        index=index,
    )
    monkeypatch.setattr(yfl, "_download_history", lambda *a, **k: bars.copy())
    monkeypatch.setattr(_Ticker, "metadata", _LazyMetadata({"currency": "ARS"}))
    monkeypatch.setattr(yfl.yf, "Ticker", _Ticker)
    frame = yfl.DataLoader().fetch(["YPFD.BA"], "2024-05-27", "2024-05-28")["YPFD.BA"]
    assert frame.attrs["quote_currency"] == "ARS"
    assert list(frame["close"]) == [1.0, 2.0]
