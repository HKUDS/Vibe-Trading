"""Regressions for data fallback, shared snapshots and recoverable factor jobs."""
from __future__ import annotations

import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api_server
from backtest import correlation, regime
from src.api import alpha_routes
from src.market_data import detect_source, fetch_market_data, fetch_market_data_json


def _frame(seed=1):
    dates = pd.bdate_range("2025-01-01", periods=240, name="trade_date")
    return pd.DataFrame({"close": np.cumprod(1 + np.random.default_rng(seed).normal(0, .01, len(dates))) * 100}, index=dates)


def test_empty_primary_falls_through_only_for_missing_symbols():
    calls = []
    class Primary:
        name = "yahoo"
        def fetch(self, codes, *_args, **_kw):
            return {code: _frame() if code == "AAPL.US" else pd.DataFrame() for code in codes}
    class Secondary:
        name = "stooq"
        def fetch(self, codes, *_args, **_kw):
            calls.append(codes)
            return {code: _frame(2) for code in codes}
    result = fetch_market_data(codes=["AAPL.US", "MSFT.US"], start_date="2025-01-01", end_date="2026-01-01", include_provenance=True,
        loader_resolver=lambda name: {"yahoo": Primary, "stooq": Secondary}[name])
    assert calls == [["MSFT.US"]]
    assert "_unresolved" not in result
    assert result["_provenance"]["MSFT.US"]["source"] == "stooq"
    assert result["_provenance"]["AAPL.US"]["source"] == "yahoo"


@pytest.mark.parametrize("symbol", ["BTCUSDT", "BTC/USDT", "BTC-USDT"])
def test_crypto_alias_fetch_uses_canonical_pair_and_preserves_requested_identity(symbol):
    class Crypto:
        def fetch(self, codes, *_args, **_kw):
            assert codes == ["BTC-USDT"]
            return {codes[0]: _frame()}
    result = fetch_market_data(codes=[symbol], start_date="2025-01-01", end_date="2026-01-01", loader_resolver=lambda _: Crypto)
    assert set(result) == {symbol}
    assert result[symbol]
    assert detect_source("BTCUSDT") == "okx"
    assert detect_source("BRK.B.US") == "yahoo"


def test_failed_chat_data_names_attempts_without_raw_exception():
    class Broken:
        def fetch(self, *_args, **_kw):
            raise RuntimeError("private /path and credentials")
    output = json.loads(fetch_market_data_json(codes=["AAPL.US"], start_date="2025-01-01", end_date="2026-01-01",
        loader_resolver=lambda _: Broken, fallback_chain_provider=lambda _: ["yahoo", "stooq"]))
    assert output["error_code"] == "no_market_data"
    assert output["_diagnostics"]["AAPL.US"]["attempts"] == [
        {"source": "yahoo", "reason": "fetch_failed"}, {"source": "stooq", "reason": "fetch_failed"}]
    assert "private" not in json.dumps(output)


def test_matrix_and_regime_use_same_snapshot_and_surface_coverage(monkeypatch):
    frames = {"AAPL": _frame(), "SPY": _frame(2)}
    fetch = Mock(return_value=frames)
    monkeypatch.setattr(correlation, "_fetch_price_series", fetch)
    result = correlation.compute_correlation_analysis(["AAPL", "SPY", "MISSING"], days=30, include_regime=True)
    assert fetch.call_count == 1
    assert result["correlation"]["labels"] == ["AAPL", "SPY"]
    assert result["regime"]["labels"] == ["AAPL", "SPY"]
    assert result["coverage"]["missing"] == ["MISSING"]
    assert result["coverage"]["observations"] == 30
    assert result["coverage"]["last_date"] == frames["AAPL"].index[-1].strftime("%Y-%m-%d")


def test_regime_failure_does_not_discard_valid_matrix(monkeypatch):
    monkeypatch.setattr(correlation, "_fetch_price_series", lambda *_: {"AAPL": _frame(), "SPY": _frame(2)})
    def fail(*_a, **_kw):
        raise ValueError("insufficient observations for a regime")
    monkeypatch.setattr(regime, "compute_regime_timeline", fail)
    result = correlation.compute_correlation_analysis(["AAPL", "SPY"], include_regime=True)
    assert result["correlation"] is not None
    assert result["regime"] is None
    assert "regime" in result["errors"]


def test_duplicate_aliases_rejected_before_any_fetch(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(correlation, "_fetch_price_series", fetch)
    with pytest.raises(ValueError, match="distinct"):
        correlation.compute_correlation_analysis(["AAPL", "AAPL.US"])
    fetch.assert_not_called()
    assert correlation._normalize_symbol("BRK.B", "us_equity") == "BRK.B.US"
    assert correlation._normalize_symbol("eur/usd", "forex") == "EURUSD=X"


@pytest.mark.parametrize(
    "pair", [
        ("700", "700.HK"), ("9988", "9988.HK"), ("00700", "00700.HK"),
        ("00700.HK", "0700.HK"), ("00005.HK", "5"),
    ]
)
def test_hk_spellings_of_one_instrument_are_rejected_as_duplicates(pair, monkeypatch):
    """A bare HK code and its suffixed spelling must normalize to one key.

    The bare path zero-pads to four digits while the suffixed spelling passed
    through unchanged, so the duplicate guard missed the same instrument written
    both ways and the endpoint returned a self-correlation, presented as a
    cross-asset relationship.
    """
    fetch = Mock()
    monkeypatch.setattr(correlation, "_fetch_price_series", fetch)
    left, right = pair
    market = correlation.infer_market(left)
    assert correlation._normalize_symbol(left, market) == correlation._normalize_symbol(
        right, market
    )
    with pytest.raises(ValueError, match="distinct"):
        correlation.compute_correlation_analysis(list(pair))
    fetch.assert_not_called()


def test_hk_normalization_preserves_distinct_currency_counters():
    """Remove redundant zeroes without truncating a real five-digit counter."""
    assert correlation._normalize_symbol("80700.HK", "hk_equity") == "80700.HK"
    assert correlation._normalize_symbol("80700", "hk_equity") == "80700.HK"
    assert correlation._normalize_symbol("00700.HK", "hk_equity") == "0700.HK"


def test_readiness_snapshots_and_single_asset_validation():
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    assert client.get("/alpha/readiness").json()["universes"]["btc-usdt"]["ready"] is False
    assert client.post("/alpha/bench", json={"zoo": "alpha101", "universe": "btc-usdt", "period": "2024-2025"}).status_code == 400
    job_id = "recovery-test"
    alpha_routes.ALPHA_BENCH_JOBS[job_id] = {"job_id": job_id, "status": "running", "progress": {"n_done": 0, "n_total": 1, "stage": "loading_data"}, "result": None, "error": None, "_private": "secret"}
    try:
        snapshot = client.get(f"/alpha/bench/{job_id}").json()
        assert snapshot["progress"]["stage"] == "loading_data"
        assert "_private" not in snapshot
        assert client.get("/alpha/bench/expired").status_code == 404
    finally:
        alpha_routes.ALPHA_BENCH_JOBS.pop(job_id, None)


@pytest.mark.parametrize("token,ready", [("", False), (" \t\n", False), ("synthetic-token", True)])
def test_alpha_readiness_requires_a_nonblank_tushare_token(monkeypatch, token, ready):
    from src.config import accessor

    config = accessor.get_env_config()
    config = config.model_copy(update={"data": config.data.model_copy(update={"tushare_token": token})})
    monkeypatch.setattr(accessor, "get_env_config", lambda: config)
    find_spec = alpha_routes.importlib.util.find_spec
    monkeypatch.setattr(
        alpha_routes.importlib.util, "find_spec",
        lambda name: object() if name == "tushare" else find_spec(name),
    )
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    status = client.get("/alpha/readiness").json()["universes"]["csi300"]
    assert status == {"ready": ready, "reason": "tushare_ready" if ready else "tushare_token_missing"}


def test_lost_submission_response_reuses_job_and_refuses_changed_parameters(monkeypatch):
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    job_id = "a" * 32
    body = {"request_id": job_id, "zoo": "alpha101", "alpha_id": "alpha101_001", "universe": "sp500", "period": "2024-2025", "top": 20}
    validated = alpha_routes.BenchRequest(**body).model_dump()
    alpha_routes.ALPHA_BENCH_JOBS[job_id] = {"job_id": job_id, "status": "running", "_request": validated}
    try:
        result = client.post("/alpha/bench", json=body)
        assert result.status_code == 202
        assert result.json()["job_id"] == job_id
        assert client.post("/alpha/bench", json={**body, "period": "2023-2025"}).status_code == 409
    finally:
        alpha_routes.ALPHA_BENCH_JOBS.pop(job_id, None)


def test_factor_data_falls_back_and_names_unserved_members(monkeypatch):
    from src.tools import alpha_bench_tool as tool
    monkeypatch.setattr(tool, "_fetch_sp500_constituents", lambda: (["AAPL", "MSFT", "MISSING"], {}))
    class Primary:
        name = "yahoo"
        def fetch(self, codes, *_args, **_kw):
            return {code: pd.DataFrame() for code in codes}
    class Secondary:
        name = "stooq"
        def fetch(self, codes, *_args, **_kw):
            return {code: _frame() for code in codes if code != "MISSING.US"}
    def resolve(name):
        return {"yahoo": Primary, "stooq": Secondary}.get(name, Primary)
    monkeypatch.setattr("src.market_data.get_loader", resolve)
    panel = tool._load_sp500_panel("2025-01-01", "2026-01-01")
    assert set(panel["close"].columns) == {"AAPL.US", "MSFT.US"}
    assert panel["_meta"]["missing_instruments"] == ["MISSING.US"]
    assert panel["_meta"]["price_sources"] == ["stooq"]
    assert panel["_meta"]["survivorship_bias"] is True


def test_fundamental_factor_dependencies_are_loaded_at_filing_time(monkeypatch):
    from types import SimpleNamespace
    from src.tools.alpha_bench_tool import _prepare_bench_panel
    frame = pd.concat([_frame()["close"], _frame(2)["close"]], axis=1)
    frame.columns = ["AAPL.US", "MSFT.US"]
    frame.iloc[0] = np.nan
    loader = Mock(return_value={"net_income": frame, "shares_diluted": frame})
    monkeypatch.setattr("backtest.loaders.fundamentals_loader.load_fundamental_panel", loader)
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(meta={"columns_required": ["close", "fund:net_income", "fund:shares_diluted"]}))
    prices = {"close": frame.copy()}
    result = _prepare_bench_panel(registry, ["fundamental_earnings_yield"], prices, "sp500", "2025-2025")
    assert loader.call_args.kwargs["pit"] is True
    assert loader.call_args.kwargs["fields"] == ["net_income", "shares_diluted"]
    assert result["fund:net_income"].iloc[0].isna().all()
    assert "fund:net_income" not in prices
    with pytest.raises(ValueError, match="SEC US filings"):
        _prepare_bench_panel(registry, ["fundamental_earnings_yield"], prices, "csi300", "2025-2025")


def test_empty_financial_input_does_not_become_a_factor_signal(monkeypatch):
    from types import SimpleNamespace
    from src.tools.alpha_bench_tool import _prepare_bench_panel
    frame = pd.concat([_frame()["close"], _frame(2)["close"]], axis=1)
    loader = Mock(return_value={"net_income": frame * np.nan})
    monkeypatch.setattr("backtest.loaders.fundamentals_loader.load_fundamental_panel", loader)
    registry = SimpleNamespace(get=lambda _: SimpleNamespace(meta={"columns_required": ["fund:net_income"]}))
    with pytest.raises(RuntimeError, match="fewer than two stocks"):
        _prepare_bench_panel(registry, ["fund"], {"close": frame}, "sp500", "2025-2025")


def test_substituted_loader_is_not_repeated_or_misnamed():
    calls = []
    class Yahoo:
        name = "yahoo"
        def fetch(self, *_args, **_kw):
            calls.append("yahoo")
            raise RuntimeError("network failure")
    class Stooq:
        name = "stooq"
        def fetch(self, *_args, **_kw):
            calls.append("stooq")
            return {}
    result = fetch_market_data(codes=["005930.KS"], start_date="2025-01-01", end_date="2026-01-01",
        loader_resolver=lambda name: Stooq if name == "stooq" else Yahoo,
        fallback_chain_provider=lambda _: ["pykrx", "yahoo", "stooq"])
    assert calls == ["yahoo", "stooq"]
    assert result["_diagnostics"]["005930.KS"]["attempts"] == [
        {"source": "yahoo", "reason": "fetch_failed"}, {"source": "stooq", "reason": "no_data"}]


def test_correlation_honors_the_configured_source_order(monkeypatch):
    from backtest.loaders import registry
    calls = []
    class Preferred:
        def is_available(self):
            return True
        def fetch(self, codes, **_kw):
            calls.append(codes)
            return {code: _frame() for code in codes}
    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {"configured": Preferred})
    monkeypatch.setattr(registry, "get_source_order_override", lambda _: ["configured"])
    output = correlation._fetch_price_series(["AAPL"], "2025-01-01", "2026-01-01")
    assert calls == [["AAPL.US"]]
    assert list(output) == ["AAPL"]


def test_unsupported_fundamental_universe_fails_before_fetching_prices(monkeypatch):
    from types import SimpleNamespace
    from src.factors.bench_runner import run_bench
    fetch = Mock()
    monkeypatch.setattr("src.factors.bench_runner._load_universe_panel", fetch)
    registry = SimpleNamespace(list=lambda **_kw: ["fund"], get=lambda _: SimpleNamespace(meta={"columns_required": ["fund:net_income"]}))
    result = run_bench(zoo="fundamental", universe="csi300", period="2025-2025", registry=registry)
    assert result["status"] == "error"
    assert "SEC US filings" in result["error"]
    fetch.assert_not_called()


def test_empty_after_resampling_does_not_stop_fallback(monkeypatch):
    class Primary:
        def fetch(self, codes, *_args, **_kw):
            return {code: _frame(1) for code in codes}
    class Secondary:
        def fetch(self, codes, *_args, **_kw):
            return {code: _frame(2) for code in codes}
    primary_value = _frame(1).iloc[0, 0]
    monkeypatch.setattr("backtest.loaders.base.resample_bars", lambda frame, _: pd.DataFrame() if frame.iloc[0, 0] == primary_value else frame)
    result = fetch_market_data(codes=["AAPL.US"], start_date="2025-01-01", end_date="2026-01-01", interval="1M",
        loader_resolver=lambda name: Primary if name == "yahoo" else Secondary, fallback_chain_provider=lambda _: ["yahoo", "stooq"])
    assert result["AAPL.US"]
    assert "_unresolved" not in result
