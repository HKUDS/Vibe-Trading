"""Tests for the opt-in Aperiodic perpetuals loader.

The ``aperiodic`` SDK is replaced by a fake at ``aperiodic_loader._require_sdk``,
so no test imports the real SDK or touches the network.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from backtest.engines._market_hooks import _detect_market, calc_crypto_funding_fee
from backtest.loaders import aperiodic_loader as ap
from backtest.loaders.base import NoAvailableSourceError
from backtest.models import Position
from tests.loader_contract import assert_loader_contract

_KEY = "test-aperiodic-key-5f1c"


class FakeAPIError(Exception):
    """Mirrors ``aperiodic.APIError``: status, server message and details."""

    def __init__(
        self, message: str, status_code: int, details: list[str] | None = None
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.details = details or []
        super().__init__(f"{status_code}: {message}")


class FakeSDK:
    """Serves canned responses per Atlas symbol and records every call."""

    def __init__(
        self,
        ohlcv: dict[str, object],
        funding: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        self.ohlcv = ohlcv
        self.funding = funding or {}
        self.calls: list[tuple[str, dict]] = []

    def get_ohlcv(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("ohlcv", kwargs))
        served = self.ohlcv[kwargs["symbol"]]
        if isinstance(served, Exception):
            raise served
        return served

    def get_derivative_metrics(self, **kwargs) -> pd.DataFrame:
        self.calls.append((kwargs["metric"], kwargs))
        return self.funding.get(kwargs["symbol"], pd.DataFrame())


def _bars(
    start: str, periods: int, freq: str | pd.Timedelta, *, tz: str | None = None
) -> pd.DataFrame:
    close = 100.0 + np.arange(periods, dtype="float64")
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq=freq, tz=tz),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(periods, 2.5, dtype="float32"),
            "volume_notional": np.full(periods, 250.0, dtype="float32"),
        }
    )


def _funding(start: str, periods: int, freq: str | pd.Timedelta) -> pd.DataFrame:
    """One distinct rate per bar, so a test can tell which bar a slot read."""
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq=freq),
            "funding_rate": (np.arange(periods, dtype="float32") + 1)
            * np.float32(1e-5),
            "funding_rate_update_frequency": np.full(periods, 0.01, dtype="float32"),
            "funding_rate_avg_update_interval": np.full(periods, 75.0, dtype="float32"),
        }
    )


@pytest.fixture()
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APERIODIC_API_KEY", _KEY)


@pytest.fixture()
def without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APERIODIC_API_KEY", raising=False)


def _install(monkeypatch: pytest.MonkeyPatch, sdk: FakeSDK) -> FakeSDK:
    monkeypatch.setattr(ap, "_require_sdk", lambda: sdk)
    return sdk


# ---------------------------------------------------------------------------
# Symbol convention and market identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, exchange, atlas",
    [
        ("BINANCE.BTC-USDT-PERP", "binance-futures", "perpetual-BTC-USDT:USDT"),
        ("okx.eth-usdt-perp", "okx-perps", "perpetual-ETH-USDT:USDT"),
        ("OKX.XAU-USD-PERP", "okx-perps", "perpetual-XAU-USD:USD"),
        (
            "BINANCE.1000PEPE-USDC-PERP",
            "binance-futures",
            "perpetual-1000PEPE-USDC:USDC",
        ),
        ("HYPERLIQUID.BTC-USDC-PERP", "hyperliquid-perps", "perpetual-BTC-USDC:USDC"),
        (
            "HYPERLIQUID.XYZ.TSLA-USDC-PERP",
            "hyperliquid-perps",
            "perpetual-XYZ:TSLA-USDC:USDC",
        ),
        (
            "hyperliquid.flx.nvda-usdh-perp",
            "hyperliquid-perps",
            "perpetual-FLX:NVDA-USDH:USDH",
        ),
        (
            "HYPERLIQUID.CASH.TSLA-USDT0-PERP",
            "hyperliquid-perps",
            "perpetual-CASH:TSLA-USDT0:USDT0",
        ),
    ],
)
def test_parse_symbol_maps_to_the_atlas_market(
    code: str, exchange: str, atlas: str
) -> None:
    assert ap.parse_symbol(code) == ap.Instrument(exchange, atlas)
    assert _detect_market(code) == "crypto"


@pytest.mark.parametrize(
    "code",
    [
        "BTC-USDT-PERP",  # the ccxt/Binance spelling keeps its own loader
        "BYBIT.BTC-USDT-PERP",
        "OKX.BTC-USDT",
        "OKX:BTC-USDT-PERP",  # a colon would end up in artifact file names
        "OKX.BTC-BTC-PERP",  # inverse contract, not USD-quoted
        "OKX.XYZ.TSLA-USDT-PERP",  # builder dex outside Hyperliquid
        "perpetual-BTC-USDT:USDT",
        "local:OKX.BTC-USDT-PERP",
    ],
)
def test_parse_symbol_rejects_other_forms(code: str) -> None:
    with pytest.raises(ValueError):
        ap.parse_symbol(code)


def test_unqualified_perp_still_routes_to_ccxt() -> None:
    from backtest.loaders.ccxt_loader import _parse_ccxt_symbol
    from src.market_data import detect_source

    assert _parse_ccxt_symbol("BTC-USDT-PERP") == ("BTC/USDT:USDT", "swap")
    assert detect_source("BTC-USDT-PERP") != "aperiodic"
    assert ap.VENUE_PERP_PATTERN.fullmatch("BTC-USDT-PERP") is None


def test_venue_form_routes_to_aperiodic_and_is_a_perpetual() -> None:
    from backtest.engines.crypto import CryptoEngine
    from backtest.runner import BacktestConfigSchema
    from src.market_data import data_market, detect_source

    code = "HYPERLIQUID.XYZ.TSLA-USDC-PERP"
    assert data_market(code) == "crypto"
    assert detect_source(code) == "aperiodic"
    assert CryptoEngine({}).funding_enabled(code)
    BacktestConfigSchema(
        codes=[code, "OKX.BTC-USDT-PERP"],
        start_date="2026-03-01",
        end_date="2026-03-31",
        source="aperiodic",
    )


# ---------------------------------------------------------------------------
# Registry: opt-in, explicit-only
# ---------------------------------------------------------------------------


def test_registered_as_an_explicit_only_source() -> None:
    from backtest.loaders import registry

    registry._ensure_registered()
    assert registry.LOADER_REGISTRY["aperiodic"] is ap.DataLoader
    assert "aperiodic" in registry.VALID_SOURCES
    assert registry.is_no_network_fallback_source("aperiodic")
    for market, chain in registry.FALLBACK_CHAINS.items():
        assert "aperiodic" not in chain, f"aperiodic must not join the {market} chain"
    assert ap.DataLoader.requires_auth is True


def test_missing_sdk_is_unavailable_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtest.loaders.registry import get_loader_cls_with_fallback

    def missing() -> None:
        raise NoAvailableSourceError("The 'aperiodic' SDK is not installed.")

    monkeypatch.setattr(ap, "_require_sdk", missing)
    assert ap.DataLoader().is_available() is False
    with pytest.raises(NoAvailableSourceError, match=r"vibe-trading-ai\[aperiodic\]"):
        get_loader_cls_with_fallback("aperiodic")
    with pytest.raises(NoAvailableSourceError, match="not installed"):
        ap.DataLoader().fetch(["OKX.BTC-USDT-PERP"], "2025-03-01", "2025-03-02")


def test_history_inventory_lists_the_served_intervals() -> None:
    from src.data_gateway.history_router import inventory

    row = next(item for item in inventory() if item["source"] == "aperiodic")
    assert set(row["intervals"]) == {
        "1m",
        "5m",
        "15m",
        "30m",
        "1H",
        "4H",
        "1D",
        "1W",
        "1M",
    }
    assert row["requires_auth"] is True


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interval, bar",
    [
        ("1m", "1m"),
        ("5m", "5m"),
        ("15m", "15m"),
        ("30m", "30m"),
        ("1H", "1h"),
        ("4H", "4h"),
        ("1D", "1d"),
    ],
)
def test_interval_is_passed_through(
    interval: str, bar: str, monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-BTC-USDT:USDT"
    span = ap._BAR_SPAN[bar]
    sdk = _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2025-03-01", 3, span)},
            {atlas: _funding("2025-03-01", 3, span)},
        ),
    )

    ap.DataLoader().fetch(
        ["BINANCE.BTC-USDT-PERP"], "2025-03-01", "2025-03-03", interval=interval
    )

    assert {call["interval"] for _, call in sdk.calls} == {bar}


@pytest.mark.parametrize("interval", ["1W", "1M", "2H", "garbage"])
def test_unsupported_interval_fails_before_any_request(
    interval: str, monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    sdk = _install(monkeypatch, FakeSDK({}))
    with pytest.raises(NoAvailableSourceError, match="unsupported Aperiodic interval"):
        ap.DataLoader().fetch(
            ["OKX.BTC-USDT-PERP"], "2025-03-01", "2025-03-02", interval=interval
        )
    assert sdk.calls == []


# ---------------------------------------------------------------------------
# Frame schema
# ---------------------------------------------------------------------------


def test_frame_matches_the_loader_contract(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-XYZ:TSLA-USDC:USDC"
    _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2026-03-01", 48, "1h", tz="UTC")},
            {atlas: _funding("2026-03-01", 48, "1h")},
        ),
    )

    out = ap.DataLoader().fetch(
        ["HYPERLIQUID.XYZ.TSLA-USDC-PERP"], "2026-03-01", "2026-03-02", interval="1H"
    )
    frame = out["HYPERLIQUID.XYZ.TSLA-USDC-PERP"]

    assert_loader_contract(frame, context="aperiodic HIP-3 1H")
    assert list(frame.columns) == [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "funding_rate",
    ]
    assert all(dtype == np.float64 for dtype in frame.dtypes)
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.tz is None
    assert frame.index.name == "trade_date"
    assert frame.index[0] == pd.Timestamp("2026-03-01 00:00:00")
    assert len(frame) == 48


def test_request_uses_exchange_time_and_no_progress_bar(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-ETH-USDT:USDT"
    sdk = _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2025-03-01", 2, "1D")},
            {atlas: _funding("2025-03-01", 2, "1D")},
        ),
    )

    ap.DataLoader().fetch(["OKX.ETH-USDT-PERP"], "2025-03-01", "2025-03-02")

    (kind, ohlcv), (metric, funding) = sdk.calls
    assert (kind, metric) == ("ohlcv", "funding")
    for call in (ohlcv, funding):
        assert call["exchange"] == "okx-perps"
        assert call["symbol"] == atlas
        assert call["timestamp"] == "exchange"
        assert call["output"] == "pandas"
        assert call["show_progress"] is False
        assert str(call["start_date"]) == "2025-03-01"
        assert str(call["end_date"]) == "2025-03-02"


# ---------------------------------------------------------------------------
# Funding alignment
# ---------------------------------------------------------------------------


def _fetch_one(
    monkeypatch,
    code: str,
    atlas: str,
    bars: pd.DataFrame,
    funding: pd.DataFrame,
    interval: str,
) -> pd.DataFrame:
    _install(monkeypatch, FakeSDK({atlas: bars}, {atlas: funding}))
    start = str(bars["time"].iloc[0].date())
    end = str(bars["time"].iloc[-1].date())
    return ap.DataLoader().fetch([code], start, end, interval=interval)[code]


def test_hourly_funding_sits_on_settlement_bars(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    funding = _funding("2025-03-01", 48, "1h")
    frame = _fetch_one(
        monkeypatch,
        "BINANCE.BTC-USDT-PERP",
        "perpetual-BTC-USDT:USDT",
        _bars("2025-03-01", 48, "1h"),
        funding,
        "1H",
    )

    rates = frame["funding_rate"]
    published = funding.set_index("time")["funding_rate"].astype("float64")
    slots = rates[rates != 0.0]
    assert list(slots.index.hour) == [0, 8, 16, 0, 8, 16]
    # A slot reads the last rate published before it: the bar ending at 08:00.
    assert rates[pd.Timestamp("2025-03-01 08:00")] == pytest.approx(
        published[pd.Timestamp("2025-03-01 07:00")]
    )
    assert rates[pd.Timestamp("2025-03-02 00:00")] == pytest.approx(
        published[pd.Timestamp("2025-03-01 23:00")]
    )
    # Nothing was published before the first slot of the range.
    assert rates[pd.Timestamp("2025-03-01 00:00")] == pytest.approx(published.iloc[0])
    assert (rates.drop(slots.index) == 0.0).all()


def test_hyperliquid_hourly_rate_is_restated_per_8_hours(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    funding = _funding("2025-03-01", 24, "1h")
    frame = _fetch_one(
        monkeypatch,
        "HYPERLIQUID.BTC-USDC-PERP",
        "perpetual-BTC-USDC:USDC",
        _bars("2025-03-01", 24, "1h"),
        funding,
        "1H",
    )

    published = funding.set_index("time")["funding_rate"].astype("float64")
    assert frame.loc["2025-03-01 16:00", "funding_rate"] == pytest.approx(
        8 * published[pd.Timestamp("2025-03-01 15:00")]
    )


def test_daily_bars_read_the_previous_day(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    funding = _funding("2025-03-01", 5, "1D")
    frame = _fetch_one(
        monkeypatch,
        "OKX.BTC-USDT-PERP",
        "perpetual-BTC-USDT:USDT",
        _bars("2025-03-01", 5, "1D"),
        funding,
        "1D",
    )

    published = funding["funding_rate"].astype("float64").to_numpy()
    assert frame["funding_rate"].to_numpy() == pytest.approx(
        [published[0], *published[:-1]]
    )


def test_missing_slot_bar_moves_funding_to_the_next_bar_in_that_hour(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    bars = _bars("2025-03-01 06:00", 36, "5min")
    bars = bars[bars["time"] != pd.Timestamp("2025-03-01 08:00")]
    funding = _funding("2025-03-01 06:00", 36, "5min")
    frame = _fetch_one(
        monkeypatch, "OKX.BTC-USDT-PERP", "perpetual-BTC-USDT:USDT", bars, funding, "5m"
    )

    slots = frame["funding_rate"][frame["funding_rate"] != 0.0]
    assert list(slots.index) == [pd.Timestamp("2025-03-01 08:05")]
    published = funding.set_index("time")["funding_rate"].astype("float64")
    assert slots.iloc[0] == pytest.approx(published[pd.Timestamp("2025-03-01 07:55")])


def test_funding_history_starting_after_the_bars_names_the_first_date(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-XYZ:TSLA-USDC:USDC"
    _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2026-03-29", 6, "1D")},
            {atlas: _funding("2026-04-01", 3, "1D")},
        ),
    )

    with pytest.raises(
        ap.AperiodicRequestError,
        match="no funding rate .* before 2026-04-01 00:00:00.* start the range",
    ):
        ap.DataLoader().fetch(
            ["HYPERLIQUID.XYZ.TSLA-USDC-PERP"], "2026-03-29", "2026-04-03"
        )


def test_no_funding_in_the_range_fails_the_symbol(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-XYZ:TSLA-USDC:USDC"
    _install(monkeypatch, FakeSDK({atlas: _bars("2026-01-01", 3, "1D")}))

    with pytest.raises(
        ap.AperiodicRequestError,
        match="no funding rate .* between 2026-01-01 00:00:00 and 2026-01-03 00:00:00",
    ):
        ap.DataLoader().fetch(
            ["HYPERLIQUID.XYZ.TSLA-USDC-PERP"], "2026-01-01", "2026-01-03"
        )


def test_a_funding_gap_at_a_slot_fails_the_symbol(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    funding = _funding("2025-03-01", 24, "1h")
    funding = funding[
        ~funding["time"].between(
            pd.Timestamp("2025-03-01 05:00"), pd.Timestamp("2025-03-01 07:00")
        )
    ]
    atlas = "perpetual-BTC-USDT:USDT"
    _install(
        monkeypatch, FakeSDK({atlas: _bars("2025-03-01", 24, "1h")}, {atlas: funding})
    )

    with pytest.raises(
        ap.AperiodicRequestError, match="funding rate is missing .* 2025-03-01 08:00:00"
    ):
        ap.DataLoader().fetch(
            ["OKX.BTC-USDT-PERP"], "2025-03-01", "2025-03-01", interval="1H"
        )


def test_engine_settles_the_supplied_rates(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    frame = _fetch_one(
        monkeypatch,
        "BINANCE.BTC-USDT-PERP",
        "perpetual-BTC-USDT:USDT",
        _bars("2025-03-01", 48, "1h"),
        _funding("2025-03-01", 48, "1h"),
        "1H",
    )
    code = "BINANCE.BTC-USDT-PERP"
    positions = {code: Position(code, 1, 100.0, frame.index[0], size=2.0)}
    applied: set = set()
    daily: set = set()

    charged = sum(
        calc_crypto_funding_fee(
            code, bar, timestamp, positions, 0.0001, applied, daily, 1.0
        )
        for timestamp, bar in frame.iterrows()
    )

    expected = (frame["funding_rate"] * 2.0 * frame["close"]).sum()
    assert charged == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Access: key, preview and refusals
# ---------------------------------------------------------------------------


def test_without_a_key_requests_go_to_the_preview(
    monkeypatch: pytest.MonkeyPatch, without_key: None
) -> None:
    atlas = "perpetual-BTC-USDT:USDT"
    sdk = _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2025-05-01", 3, "5min")},
            {atlas: _funding("2025-05-01", 3, "5min")},
        ),
    )

    ap.DataLoader().fetch(
        ["BINANCE.BTC-USDT-PERP"], "2025-05-01", "2025-05-01", interval="5m"
    )

    assert all(
        call["preview"] is True and "api_key" not in call for _, call in sdk.calls
    )


def test_with_a_key_requests_carry_it(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-BTC-USDT:USDT"
    sdk = _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2025-05-01", 3, "1D")},
            {atlas: _funding("2025-05-01", 3, "1D")},
        ),
    )

    ap.DataLoader().fetch(["BINANCE.BTC-USDT-PERP"], "2025-05-01", "2025-05-03")

    assert all(
        call["api_key"] == _KEY and "preview" not in call for _, call in sdk.calls
    )


@pytest.mark.parametrize("placeholder", ["", "your_aperiodic_api_key", "xxx"])
def test_placeholder_key_counts_as_no_key(
    placeholder: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APERIODIC_API_KEY", placeholder)
    assert ap._resolve_key() == ""


def test_missing_key_outside_the_preview_says_so(
    monkeypatch: pytest.MonkeyPatch, without_key: None
) -> None:
    atlas = "perpetual-XYZ:TSLA-USDC:USDC"
    refusal = FakeAPIError(
        "Requested parameters do not match any available preview data", 400
    )
    _install(monkeypatch, FakeSDK({atlas: refusal}))

    with pytest.raises(ap.AperiodicRequestError) as caught:
        ap.DataLoader().fetch(
            ["HYPERLIQUID.XYZ.TSLA-USDC-PERP"], "2026-03-01", "2026-03-31"
        )

    message = str(caught.value)
    assert (
        "HTTP 400: Requested parameters do not match any available preview data"
        in message
    )
    assert "APERIODIC_API_KEY is not set" in message
    assert "preview" in message
    assert "https://aperiodic.io" in message


def test_plan_refusal_is_raised_with_the_api_text(
    monkeypatch: pytest.MonkeyPatch, with_key: None, caplog: pytest.LogCaptureFixture
) -> None:
    atlas = "perpetual-BTC-USDT:USDT"
    refusal = FakeAPIError(
        "Your plan covers 2025-01-01 to 2025-12-31; the request starts 2024-06-01", 403
    )
    _install(monkeypatch, FakeSDK({atlas: refusal}))

    with caplog.at_level(logging.WARNING, logger="backtest.loaders.aperiodic_loader"):
        with pytest.raises(ap.AperiodicRequestError) as caught:
            ap.DataLoader().fetch(["BINANCE.BTC-USDT-PERP"], "2024-06-01", "2024-06-30")

    message = str(caught.value)
    assert "HTTP 403: Your plan covers 2025-01-01 to 2025-12-31" in message
    assert "does not cover this request" in message
    assert _KEY not in message
    assert _KEY not in caplog.text


def test_rejected_key_is_named(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    atlas = "perpetual-BTC-USDT:USDT"
    _install(monkeypatch, FakeSDK({atlas: FakeAPIError("Authorization Required", 401)}))

    with pytest.raises(
        ap.AperiodicRequestError,
        match="HTTP 401: Authorization Required. APERIODIC_API_KEY was rejected",
    ):
        ap.DataLoader().fetch(["BINANCE.BTC-USDT-PERP"], "2025-03-01", "2025-03-02")


def test_one_refused_symbol_does_not_discard_the_others(
    monkeypatch: pytest.MonkeyPatch, with_key: None, caplog: pytest.LogCaptureFixture
) -> None:
    served, refused = "perpetual-BTC-USDT:USDT", "perpetual-DOGE-USDT:USDT"
    sdk = FakeSDK(
        {
            served: _bars("2025-03-01", 2, "1D"),
            refused: FakeAPIError("DOGE is not in your plan", 403),
        },
        {served: _funding("2025-03-01", 2, "1D")},
    )
    _install(monkeypatch, sdk)
    loader = ap.DataLoader()

    with caplog.at_level(logging.WARNING, logger="backtest.loaders.aperiodic_loader"):
        out = loader.fetch(
            ["OKX.BTC-USDT-PERP", "OKX.DOGE-USDT-PERP"], "2025-03-01", "2025-03-02"
        )

    assert list(out) == ["OKX.BTC-USDT-PERP"]
    assert loader.fetch_errors == {"OKX.DOGE-USDT-PERP": "fetch_failed"}
    assert "DOGE is not in your plan" in caplog.text


def test_download_failures_do_not_leak_presigned_urls(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-BTC-USDT:USDT"
    failure = RuntimeError(
        "Failed to download data for 2025-03: Server error '503' for url "
        "'https://storage.example/ohlcv/2025-03.parquet?X-Amz-Signature=abc123'"
    )
    _install(monkeypatch, FakeSDK({atlas: failure}))

    with pytest.raises(ap.AperiodicRequestError) as caught:
        ap.DataLoader().fetch(["OKX.BTC-USDT-PERP"], "2025-03-01", "2025-03-02")

    assert "X-Amz-Signature" not in str(caught.value)
    assert "<url>" in str(caught.value)


def test_a_cached_range_needs_neither_the_sdk_nor_a_request(
    monkeypatch: pytest.MonkeyPatch, with_key: None, tmp_path
) -> None:
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "1")
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE_ROOT", str(tmp_path))
    atlas = "perpetual-BTC-USDT:USDT"
    _install(
        monkeypatch,
        FakeSDK(
            {atlas: _bars("2025-03-01", 3, "1D")},
            {atlas: _funding("2025-03-01", 3, "1D")},
        ),
    )
    first = ap.DataLoader().fetch(["OKX.BTC-USDT-PERP"], "2025-03-01", "2025-03-03")

    def missing() -> None:
        raise NoAvailableSourceError("SDK must not be needed for a cached range")

    monkeypatch.setattr(ap, "_require_sdk", missing)
    second = ap.DataLoader().fetch(["OKX.BTC-USDT-PERP"], "2025-03-01", "2025-03-03")

    pd.testing.assert_frame_equal(
        second["OKX.BTC-USDT-PERP"], first["OKX.BTC-USDT-PERP"]
    )


# ---------------------------------------------------------------------------
# Empty responses
# ---------------------------------------------------------------------------


def test_empty_response_is_reported_not_returned(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    atlas = "perpetual-XYZ:TSLA-USDC:USDC"
    _install(monkeypatch, FakeSDK({atlas: pd.DataFrame()}))
    loader = ap.DataLoader()

    with pytest.raises(
        ap.AperiodicRequestError, match="no bars between 2025-01-01 and 2025-12-31"
    ):
        loader.fetch(["HYPERLIQUID.XYZ.TSLA-USDC-PERP"], "2025-01-01", "2025-12-31")

    assert loader.fetch_errors == {"HYPERLIQUID.XYZ.TSLA-USDC-PERP": "no_data"}


def test_empty_symbol_beside_a_served_one_is_omitted(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    served, empty = "perpetual-BTC-USDT:USDT", "perpetual-SRM-USDT:USDT"
    _install(
        monkeypatch,
        FakeSDK(
            {served: _bars("2025-03-01", 2, "1D"), empty: pd.DataFrame()},
            {served: _funding("2025-03-01", 2, "1D")},
        ),
    )
    loader = ap.DataLoader()

    out = loader.fetch(
        ["BINANCE.BTC-USDT-PERP", "BINANCE.SRM-USDT-PERP"], "2025-03-01", "2025-03-02"
    )

    assert list(out) == ["BINANCE.BTC-USDT-PERP"]
    assert loader.fetch_errors == {"BINANCE.SRM-USDT-PERP": "no_data"}


def test_invalid_symbol_is_a_per_symbol_failure(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    sdk = _install(monkeypatch, FakeSDK({}))

    with pytest.raises(
        ap.AperiodicRequestError, match="not an Aperiodic perpetual symbol"
    ):
        ap.DataLoader().fetch(["BTC-USDT"], "2025-03-01", "2025-03-02")

    assert sdk.calls == []
