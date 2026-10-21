"""Production loader resolution must not silently reprice a cash ledger."""

import pandas as pd
import pytest

from src.tools.paper_trade import data


@pytest.mark.parametrize(
    "market,source,adjustment,accepted",
    [
        ("us", "yfinance", None, False),
        ("us", "sina", None, True),
        ("hk", "tencent", None, True),
        ("hk", "tencent", "split_dividend", False),
        ("us", "unverified", None, False),
        ("cn_a", "tencent", "split_dividend", False),
    ],
)
def test_resolved_loader_requires_raw_prices(
    monkeypatch, market, source, adjustment, accepted
):
    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [100.0],
            "low": [100.0],
            "close": [100.0],
            "volume": [1000.0],
        },
        index=pd.to_datetime(["2026-10-20"]),
    )
    if adjustment:
        frame.attrs["adjustment"] = adjustment

    class Loader:
        name = source

        def fetch(self, *args, **kwargs):
            return {"TEST": frame}

    monkeypatch.setattr(data, "_resolve_network_loader", lambda *a, **kw: Loader())
    result = data.fetch_market_data(
        market,
        ("TEST",),
        "2026-10-20",
        "2026-10-20",
        ch_client=None,
    )
    assert data.assess_readiness(result, "2026-10-20").ready is accepted
    if not accepted:
        assert any("requires raw prices" in warning for warning in result.warnings)
