import pandas as pd
import pytest
from backtest.correlation import infer_market, _fetch_price_series
from backtest.loaders import registry
from src.market_data import fetch_market_data


@pytest.mark.parametrize("symbol", ["ABNB", "ABNB.US", "SOL", "SOL.US"])
def test_equity_names_are_not_crypto_quote_suffixes(symbol):
    assert infer_market(symbol) == "us_equity"


@pytest.mark.parametrize(
    "symbol",
    ["BTC-USDT", "ETH/USD", "ETHUSDT", "ETHBTC", "XRPUSDT", "LTCETH", "AVAXBNB"],
)
def test_explicit_crypto_pairs_stay_crypto(symbol):
    assert infer_market(symbol) == "crypto"


def test_airbnb_fetch_uses_equity_chain(monkeypatch):
    from backtest.loaders import registry

    seen = []

    class Loader:
        def is_available(self):
            return True

        def fetch(self, codes, **kwargs):
            seen.extend(codes)
            return {codes[0]: pd.DataFrame({"close": [100, 110]})}

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"us_equity": ["equity"]})
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {"equity": Loader})
    assert list(_fetch_price_series(["ABNB"], "2025-01-01", "2025-01-02")) == ["ABNB"]
    assert seen == ["ABNB.US"]


@pytest.mark.parametrize(
    "symbol", ["BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD", "ADA/USD", "DOGE/USD"]
)
def test_shared_engine_recognizes_known_slash_usd_crypto(symbol):
    """The engine and correlation consumer must agree on documented USD pairs."""
    from backtest.engines._market_hooks import _detect_market

    assert _detect_market(symbol) == "crypto"


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("GBP/USD", "forex"),
        ("EUR/USD", "forex"),
        ("USD/JPY", "forex"),
        ("SOL.US", "us_equity"),
    ],
)
def test_shared_engine_slash_crypto_keeps_fiat_and_equity_controls(symbol, expected):
    from backtest.engines._market_hooks import _detect_market

    assert _detect_market(symbol) == expected
    assert infer_market(symbol) == expected


def test_correlation_slash_crypto_uses_crypto_chain(monkeypatch):
    """Exercise the public price consumer with isolated data-provider seams."""
    from backtest.loaders import registry

    seen = []

    class CryptoLoader:
        def is_available(self):
            return True

        def fetch(self, codes, **kwargs):
            seen.extend(codes)
            return {codes[0]: pd.DataFrame({"close": [100, 110]})}

    class WrongForexLoader:
        def is_available(self):
            return True

        def fetch(self, codes, **kwargs):
            raise AssertionError("a crypto pair must not visit the fiat provider")

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(
        registry,
        "FALLBACK_CHAINS",
        {"crypto": ["fixture_crypto"], "forex": ["fixture_forex"]},
    )
    monkeypatch.setattr(
        registry,
        "LOADER_REGISTRY",
        {"fixture_crypto": CryptoLoader, "fixture_forex": WrongForexLoader},
    )
    diagnostics = {}
    rows = _fetch_price_series(
        ["ETH/USD"], "2025-01-01", "2025-01-02", diagnostics=diagnostics
    )
    assert diagnostics["ETH/USD"]["market"] == "crypto"
    assert diagnostics["ETH/USD"]["source"] == "fixture_crypto"
    assert list(rows) == ["ETH/USD"]
    assert rows["ETH/USD"]["close"].tolist() == [100, 110]
    assert seen == ["ETH/USD"]


def _routing_frame():
    return pd.DataFrame(
        {'open': [100., 101.], 'high': [101., 102.], 'low': [99., 100.],
         'close': [100., 101.], 'volume': [1., 1.]},
        index=pd.date_range('2025-01-01', periods=2, name='date'),
    )


@pytest.mark.parametrize('symbol', ['XAU/USD', 'XAG/USD', 'XPT/USD', 'XPD/USD'])
def test_precious_metals_keep_the_forex_loader(symbol, monkeypatch):
    calls = []

    class Forex:
        def is_available(self):
            return True

        def fetch(self, codes, **kwargs):
            calls.append('forex')
            return {code: _routing_frame() for code in codes}

    class Crypto:
        def is_available(self):
            return True

        def fetch(self, codes, **kwargs):
            calls.append('crypto')
            return {}

    monkeypatch.setattr(registry, '_ensure_registered', lambda: None)
    monkeypatch.setattr(registry, 'get_source_order_override', lambda market: None)
    monkeypatch.setattr(registry, 'FALLBACK_CHAINS', {'forex': ['fx'], 'crypto': ['coin']})
    monkeypatch.setattr(registry, 'LOADER_REGISTRY', {'fx': Forex, 'coin': Crypto})
    rows = _fetch_price_series([symbol], '2025-01-01', '2025-01-02')
    assert calls == ['forex']
    assert symbol in rows


@pytest.mark.parametrize('symbol', ['BTC/USD', 'ETH/USD', 'BNB/USD', 'SOL/USD', 'ADA/USD', 'DOGE/USD'])
def test_market_data_auto_reaches_crypto_chain(symbol, monkeypatch):
    calls = []
    monkeypatch.setattr(registry, 'refresh_source_order_overrides', lambda: None)
    monkeypatch.setattr(registry, 'get_source_order_override', lambda market: None)
    monkeypatch.setattr(registry, 'FALLBACK_CHAINS', {'forex': ['mt5'], 'crypto': ['okx']})

    def resolve(source):
        class Loader:
            name = source

            def fetch(self, codes, *args, **kwargs):
                calls.append(source)
                return {code: _routing_frame() for code in codes} if source == 'okx' else {}
        return Loader

    result = fetch_market_data(
        codes=[symbol], start_date='2025-01-01', end_date='2025-01-02',
        loader_resolver=resolve,
    )
    assert calls == ['okx']
    assert result[symbol]
