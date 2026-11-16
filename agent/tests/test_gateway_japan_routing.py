"""Japan data coverage and fail-closed public identities at both fetch paths."""

import pandas as pd
import pytest

from backtest.engines._market_hooks import _detect_market
from backtest.loaders.base import normalize_declared_quote_currency
from backtest.loaders.yahoo_loader import _is_supported
from backtest.runner import BacktestConfigSchema, _create_market_engine
from src.data_gateway.calendars import CalendarCoverageError, validate
from src.data_gateway.config import Config
from src.data_gateway.history_router import candidates, market_for
from src.data_gateway.service import MarketDataGateway
from src.market_data import data_market, detect_source, fetch_market_data


@pytest.mark.parametrize("symbol", ["7203.T", "130A.T", " 7203.t "])
def test_japan_has_its_own_public_chain(symbol):
    assert data_market(symbol) == "jp_equity"
    assert market_for(symbol) == "jp_equity"
    assert detect_source(symbol) == "yahoo"
    assert candidates(symbol, "1D") == ["yahoo", "yfinance"]
    assert _is_supported(symbol)


@pytest.mark.parametrize("symbol", ["something_weird", "BHP.AX", "7203.XX"])
def test_unknown_public_market_never_uses_legacy_default(symbol):
    # Legacy journal/backtest callers retain their existing default; public reads do not.
    assert _detect_market(symbol) == "a_share"
    with pytest.raises(ValueError, match="Unsupported market identity"):
        detect_source(symbol)
    with pytest.raises(ValueError, match="Unsupported market identity"):
        market_for(symbol)


@pytest.mark.parametrize("symbol", ["600519", "600519.SS", "600519.SH"])
def test_existing_mainland_spellings_remain_supported(symbol):
    assert data_market(symbol) == "a_share"


@pytest.mark.parametrize("source", ["auto", "yahoo"])
@pytest.mark.parametrize("path", ["gateway", "full", "frames"])
def test_unknown_is_not_sent_with_healthy_symbols(tmp_path, monkeypatch, source, path):
    from backtest.loaders import registry
    from src.data_gateway.scheduling import background

    calls = []

    class Loader:
        name = "yahoo"
        volume_units = {}

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            calls.extend(codes)
            return {c: pd.DataFrame({"close": [100.]}, index=pd.to_datetime(["2026-11-13"])) for c in codes}

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "refresh_source_order_overrides", lambda: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {"yahoo": Loader})
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"jp_equity": ["yahoo"], "a_share": ["yahoo"]})
    params = dict(codes=["7203.T", "600519.SH", "BHP.AX"], start_date="2026-11-13", end_date="2026-11-13", source=source)
    if path == "gateway":
        # Background batches share a walker across markets, unlike foreground fanout.
        token = background.set(True)
        g = MarketDataGateway(Config(tmp_path))
        try:
            payload = g.bars(**params)["data"]
        finally:
            g.close()
            background.reset(token)
    else:
        payload = fetch_market_data(**params, loader_resolver=lambda _: Loader, max_rows=0, as_frames=path == "frames")
    assert sorted(calls) == ["600519.SH", "7203.T"]
    assert payload["_unresolved"] == ["BHP.AX"]
    reason = payload["_diagnostics"]["BHP.AX"]
    if isinstance(reason, dict):
        reason = reason["attempts"]
    assert reason[0]["reason"] == "unsupported_market"


def test_japan_requires_declared_yen():
    frame = pd.DataFrame({"close": [100.]})
    assert normalize_declared_quote_currency(frame.copy(), "7203.T", "JPY").attrs["quote_currency"] == "JPY"
    for currency in (None, "USD"):
        with pytest.raises(ValueError, match="JPY"):
            normalize_declared_quote_currency(frame.copy(), "7203.T", currency)


def test_japan_calendar_validates_observed_days_and_missing_rows():
    rows = [{"trade_date": d, "close": 100.} for d in ["2026-11-12", "2026-11-13"]]
    assert validate(rows, "jp_equity", "2026-11-12", "2026-11-13", "1D", {})[1]["coverage_verified"]
    with pytest.raises(CalendarCoverageError, match="missing=1"):
        validate(rows[:-1], "jp_equity", "2026-11-12", "2026-11-13", "1D", {})


@pytest.mark.parametrize("codes", [["7203.T"], ["AAPL.US", "7203.T"], ["local:7203.T"]])
def test_data_support_never_enables_unimplemented_execution_rules(codes):
    with pytest.raises(ValueError, match="Japanese backtest execution rules"):
        BacktestConfigSchema(codes=codes, start_date="2026-11-12", end_date="2026-11-13")
    with pytest.raises(ValueError, match="Japanese backtest execution rules"):
        _create_market_engine("yahoo", {}, codes)


@pytest.mark.parametrize("declared,expected,basis", [(None, "HKD", "instrument_market_contract"), ("USD", "USD", "source_metadata")])
def test_currency_provenance_keeps_observed_metadata_over_market_contract(declared, expected, basis):
    class Loader:
        name = "tencent"
        volume_units = {}

        def is_available(self):
            return True

        def fetch(self, codes, *args, **kwargs):
            frame = pd.DataFrame({"close": [100.]}, index=pd.to_datetime(["2026-11-13"]))
            if declared:
                frame.attrs["quote_currency"] = declared
            return {codes[0]: frame}

    payload = fetch_market_data(codes=["00700.HK"], start_date="2026-11-13", end_date="2026-11-13", loader_resolver=lambda _: Loader, include_provenance=True)
    provenance = payload["_provenance"]["00700.HK"]
    assert provenance["quote_currency"] == expected
    assert provenance["quote_currency_basis"] == basis


def test_crypto_settlement_currency_is_never_reported_as_quote_currency():
    class Loader:
        name = "okx"
        volume_units = {}

        def fetch(self, codes, *args, **kwargs):
            return {codes[0]: pd.DataFrame({"close": [100.]}, index=pd.to_datetime(["2026-11-13"]))}

    payload = fetch_market_data(codes=["BTC-USDT"], start_date="2026-11-13", end_date="2026-11-13", loader_resolver=lambda _: Loader, include_provenance=True)
    assert "quote_currency" not in payload["_provenance"]["BTC-USDT"]
