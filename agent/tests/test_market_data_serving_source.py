"""An unavailable loader must not take credit for a substitute's data (#1491)."""

import pandas as pd
import pytest

from backtest.loaders import registry
from src.market_data import fetch_market_data


def _bars():
    return pd.DataFrame(
        {"close": [10.0], "volume": [100.0]},
        index=pd.DatetimeIndex(["2026-09-01"], name="trade_date"),
    )


@pytest.mark.parametrize("requested", ["baostock", "sina"])
@pytest.mark.parametrize("availability", ["unavailable", "constructor_error", "available"])
def test_real_registry_substitution_reports_serving_source(monkeypatch, requested, availability):
    """Exercise the real resolver, including unavailable optional SDKs."""

    class Requested:
        name = requested
        markets = {"a_share"}
        volume_units = {"a_share": "lots"}

        def __init__(self):
            if availability == "constructor_error":
                raise RuntimeError("optional SDK cannot initialize")

        def is_available(self):
            return availability == "available"

        def fetch(self, codes, start, end, interval="1D"):
            assert availability == "available"
            return {code: _bars() for code in codes}

    class Serving:
        name = "tencent"
        markets = {"a_share"}
        volume_units = {"a_share": "shares"}

        def is_available(self):
            return True

        def fetch(self, codes, start, end, interval="1D"):
            return {code: _bars() for code in codes}

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {requested: Requested, "tencent": Serving})
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["tencent", requested]})
    out = fetch_market_data(
        codes=["600519.SH"],
        start_date="2026-09-01",
        end_date="2026-09-02",
        source=requested,
        include_provenance=True,
    )
    provenance = out["_provenance"]["600519.SH"]
    available = availability == "available"
    assert provenance["source"] == (requested if available else "tencent")
    assert provenance["requested_source"] == requested
    assert provenance["fallback_used"] is (not available)
    assert provenance["volume_unit"] == ("lots" if available else "shares")
    # The caliber follows the source that actually served, not the one requested.
    caliber_by_source = {
        "sina": "raw",
        "baostock": "split_dividend",
        "tencent": "split_dividend_additive",
    }
    assert provenance["adjustment"] == caliber_by_source[provenance["source"]]


def test_substituted_partial_batch_keeps_each_serving_source():
    """A resolver substitution and later fetch fallback both retain identity."""
    calls = []

    class Tencent:
        name = "tencent"

        def fetch(self, codes, start, end, interval="1D"):
            calls.append((self.name, codes))
            return {"600519.SH": _bars()}

    class Sina:
        name = "sina"

        def fetch(self, codes, start, end, interval="1D"):
            calls.append((self.name, codes))
            return {code: _bars() for code in codes}

    out = fetch_market_data(
        codes=["600519.SH", "000001.SZ"],
        start_date="2026-09-01",
        end_date="2026-09-02",
        source="baostock",
        include_provenance=True,
        loader_resolver=lambda source: Tencent if source == "baostock" else Sina,
        fallback_chain_provider=lambda source: ["sina"],
    )
    assert calls == [("tencent", ["600519.SH", "000001.SZ"]), ("sina", ["000001.SZ"])]
    first, second = (out["_provenance"][code] for code in ["600519.SH", "000001.SZ"])
    assert (first["source"], first["adjustment"], first["fallback_used"]) == (
        "tencent",
        "split_dividend_additive",
        True,
    )
    assert (second["source"], second["adjustment"], second["fallback_used"]) == ("sina", "raw", True)
