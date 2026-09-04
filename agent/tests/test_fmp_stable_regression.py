"""Regression for issue 1270: FMP Stable endpoint and no silent fallback for explicit source=fmp."""

import pandas as pd

from backtest.loaders.fmp_loader import _parse_historical
from backtest.loaders.base import NoAvailableSourceError


def _stable_bars():
    return [
        {"date": "2024-01-03", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
        {"date": "2024-01-04", "open": 3.0, "high": 4.0, "low": 2.5, "close": 3.5, "volume": 200.0},
    ]


def test_parse_stable_top_level_array():
    """Stable API returns a top-level array, not {"historical": [...]}."""
    payload = _stable_bars()
    df = _parse_historical(payload)
    assert df is not None
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_parse_stable_empty_array_returns_none():
    assert _parse_historical([]) is None


def test_explicit_fmp_does_not_fallback_to_yahoo(monkeypatch):
    """Explicit source=fmp must not silently return yahoo data when FMP 403s."""
    from src.market_data import fetch_market_data

    class FailFMP:
        name = "fmp"
        markets = {"us_equity"}
        def __init__(self): pass
        def is_available(self): return True
        def fetch(self, codes, start_date, end_date, interval="1D"):
            raise RuntimeError("FMP 403 legacy retired")

    class YahooOK:
        name = "yahoo"
        markets = {"us_equity"}
        def __init__(self): pass
        def is_available(self): return True
        def fetch(self, codes, start_date, end_date, interval="1D"):
            df = pd.DataFrame([{"trade_date": pd.Timestamp("2024-01-03"), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]).set_index("trade_date")
            return {codes[0]: df}

    def resolver(name):
        if name == "fmp":
            return FailFMP
        if name == "yahoo":
            return YahooOK
        class Fail:
            name = name
            markets = {"us_equity"}
            def __init__(self): pass
            def is_available(self): return False
            def fetch(self, *a, **kw): raise RuntimeError("unavailable")
        return Fail

    result = fetch_market_data(
        codes=["AAPL.US"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        source="fmp",
        interval="1D",
        loader_resolver=resolver,
        include_provenance=True,
    )
    # Must not contain yahoo data
    assert "AAPL.US" not in result, "explicit fmp should not fallback to yahoo"
    assert "_unresolved" in result and "AAPL.US" in result["_unresolved"]
    # provenance must not claim yahoo
    prov = result.get("_provenance", {})
    assert not any(v.get("source") == "yahoo" for v in prov.values())


def test_explicit_fmp_unavailable_raises_no_fallback(monkeypatch):
    """registry: explicit fmp unavailable must raise, not fallback to yahoo."""
    from backtest.loaders.registry import get_loader_cls_with_fallback
    from backtest.loaders import registry

    fmp_cls = registry.LOADER_REGISTRY["fmp"]
    monkeypatch.setattr(fmp_cls, "is_available", lambda self: False)
    try:
        get_loader_cls_with_fallback("fmp")
        assert False, "should have raised NoAvailableSourceError"
    except NoAvailableSourceError as exc:
        assert "does not fall back" in str(exc)


def test_explicit_fmp_unavailable_names_the_missing_credential(monkeypatch):
    """The refusal must say how to fix it, the way local/tickerall already do.

    ``fmp`` joined ``_NO_NETWORK_FALLBACK_SOURCES`` but not the hint table
    beside it, so the user got "unavailable and does not fall back" with no
    remedy — the one thing that error exists to deliver.
    """
    from backtest.loaders.registry import get_loader_cls_with_fallback
    from backtest.loaders import registry

    fmp_cls = registry.LOADER_REGISTRY["fmp"]
    monkeypatch.setattr(fmp_cls, "is_available", lambda self: False)
    try:
        get_loader_cls_with_fallback("fmp")
        assert False, "should have raised NoAvailableSourceError"
    except NoAvailableSourceError as exc:
        assert "FMP_API_KEY" in str(exc)


def test_auto_chain_still_walks_past_an_unavailable_fmp():
    """The other side of the gate: auto must NOT stop at fmp.

    Every other test here asserts the gate closes (explicit fmp refuses to
    substitute). None asserted it stays open, and that is the direction a
    no-fallback rule breaks things: ``fmp`` sits inside the ``us_equity``
    chain, so if adding it to ``_NO_NETWORK_FALLBACK_SOURCES`` had made the
    walk abort at that link, every keyless user's auto US fetch would die
    there. ``fmp`` is placed mid-chain on purpose — behind the detected head,
    ahead of the source that actually serves — because a chain that reaches
    fmp only after something already succeeded proves nothing.
    """
    from src.market_data import fetch_market_data

    served = pd.DataFrame(
        [{"trade_date": pd.Timestamp("2024-01-03"), "open": 1, "high": 1,
          "low": 1, "close": 1, "volume": 1}]
    ).set_index("trade_date")
    attempted: list[str] = []

    def resolver(name):
        attempted.append(name)
        if name == "fmp":
            raise NoAvailableSourceError(
                "Data source 'fmp' is unavailable and does not fall back to a "
                "network source. Set FMP_API_KEY."
            )

        class Loader:
            markets = {"us_equity"}

            def __init__(self): pass

            def is_available(self): return True

            def fetch(self, codes, start_date, end_date, interval="1D"):
                if name == "yahoo":
                    raise RuntimeError("yahoo 404")
                return {codes[0]: served}

        Loader.name = name
        return Loader

    result = fetch_market_data(
        codes=["AAPL.US"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        source="auto",
        interval="1D",
        loader_resolver=resolver,
        fallback_chain_provider=lambda src: ["yahoo", "fmp", "stooq"],
        include_provenance=True,
    )

    assert "fmp" in attempted, "test is void unless the walk actually reached fmp"
    assert attempted[-1] == "stooq", f"walk stopped at fmp: {attempted}"
    assert "AAPL.US" in result, "an unavailable fmp must not abort the auto walk"
    prov = result.get("_provenance", {}).get("AAPL.US", {})
    assert prov.get("source") == "stooq"
