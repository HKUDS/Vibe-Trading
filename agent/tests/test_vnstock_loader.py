"""Tests for VNStockLoader — all vnstock API calls are mocked.

vnstock is not installed in CI, so we stub ``sys.modules['vnstock']`` for the
tests that exercise the lazy import path.  Every external call is mocked.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest.loaders.vnstock_loader import (
    VNStockLoader,
    _classify_vn_exchange,
    _strip_exchange,
)
from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    _ensure_registered,
)


# ---------------------------------------------------------------------------
# Helpers — fake vnstock module
# ---------------------------------------------------------------------------

def _default_history_df() -> pd.DataFrame:
    """A minimal vnstock-style OHLCV frame keyed by ``time``."""
    return pd.DataFrame({
        "time": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "open": [100.0, 101.0],
        "high": [102.0, 103.0],
        "low": [99.0, 100.0],
        "close": [101.0, 102.0],
        "volume": [10_000, 12_000],
    })


def _twenty_row_df() -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=20, freq="B")
    return pd.DataFrame({
        "time": dates,
        "open": range(100, 120),
        "high": range(101, 121),
        "low": range(99, 119),
        "close": range(100, 120),
        "volume": [10_000] * 20,
    })


def _make_mock_vnstock_module(history_return=None, history_raises=None):
    """Build a fake ``vnstock`` module with a ``Quote`` class.

    Any call to ``Quote(symbol=..., source=...)`` returns the same mock
    instance so the test can assert on call args.
    """
    fake_quote_instance = MagicMock()
    if history_raises is not None:
        fake_quote_instance.history.side_effect = history_raises
    else:
        df = _default_history_df() if history_return is None else history_return
        fake_quote_instance.history.return_value = df
    fake_quote_class = MagicMock(return_value=fake_quote_instance)
    fake_module = MagicMock()
    fake_module.Quote = fake_quote_class
    return fake_module, fake_quote_class, fake_quote_instance


def _patch_vnstock(fake_module):
    """Context manager: install ``fake_module`` as ``sys.modules['vnstock']``."""
    return patch.dict(sys.modules, {"vnstock": fake_module})


# ---------------------------------------------------------------------------
# Group A — Class metadata
# ---------------------------------------------------------------------------

class TestClassMetadata:
    def test_loader_name(self):
        assert VNStockLoader.name == "vnstock"

    def test_loader_markets(self):
        assert "vn_equity" in VNStockLoader.markets
        assert "vn_index" in VNStockLoader.markets
        assert "vn_futures" in VNStockLoader.markets

    def test_loader_no_auth(self):
        assert VNStockLoader.requires_auth is False


# ---------------------------------------------------------------------------
# Group B — Symbol normalization
# ---------------------------------------------------------------------------

class TestStripExchange:
    def test_strip_hose(self):
        assert _strip_exchange("VNM.HOSE") == "VNM"

    def test_strip_hnx(self):
        assert _strip_exchange("SHB.HNX") == "SHB"

    def test_strip_upcom(self):
        assert _strip_exchange("VEA.UPCOM") == "VEA"

    def test_strip_bare(self):
        assert _strip_exchange("VNM") == "VNM"

    def test_strip_case_insensitive(self):
        # The implementation upper-cases the result.
        assert _strip_exchange("vnm.hose") == "VNM"


# ---------------------------------------------------------------------------
# Group C — Exchange classification helper
# ---------------------------------------------------------------------------

class TestClassifyVnExchange:
    def test_hose_explicit(self):
        assert _classify_vn_exchange("VNM.HOSE") == "HOSE"

    def test_hnx_explicit(self):
        assert _classify_vn_exchange("SHB.HNX") == "HNX"

    def test_upcom_explicit(self):
        assert _classify_vn_exchange("VEA.UPCOM") == "UPCOM"

    def test_default_to_hose(self):
        assert _classify_vn_exchange("VNM") == "HOSE"

    def test_case_insensitive(self):
        assert _classify_vn_exchange("vnm.hnx") == "HNX"


# ---------------------------------------------------------------------------
# Group D — is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_is_available_no_vnstock(self):
        """Module not importable → False."""
        # Ensure vnstock is not in sys.modules and importing raises ImportError.
        with patch.dict(sys.modules, {"vnstock": None}):
            assert VNStockLoader().is_available() is False

    def test_is_available_vnstock_installed(self):
        """vnstock importable + health probe returns rows → True."""
        fake_module, _, _ = _make_mock_vnstock_module(history_return=_default_history_df())
        with _patch_vnstock(fake_module):
            assert VNStockLoader().is_available() is True

    def test_is_available_vnstock_health_probe_fails(self):
        """vnstock importable but health probe raises → False."""
        fake_module, _, _ = _make_mock_vnstock_module(
            history_raises=ConnectionError("boom"),
        )
        with _patch_vnstock(fake_module):
            assert VNStockLoader().is_available() is False

    def test_is_available_health_probe_empty(self):
        """vnstock returns empty DataFrame → False."""
        fake_module, _, _ = _make_mock_vnstock_module(
            history_return=pd.DataFrame(),
        )
        with _patch_vnstock(fake_module):
            assert VNStockLoader().is_available() is False


# ---------------------------------------------------------------------------
# Group E — fetch happy path
# ---------------------------------------------------------------------------

class TestFetchHappyPath:
    def test_fetch_success_vci(self):
        fake_module, fake_quote_cls, _ = _make_mock_vnstock_module(
            history_return=_twenty_row_df(),
        )
        with _patch_vnstock(fake_module):
            result = VNStockLoader().fetch(["VNM"], "2024-01-01", "2024-01-31")

        assert "VNM" in result
        df = result["VNM"]
        assert df.index.name == "trade_date"
        assert len(df) == 20
        assert {"open", "high", "low", "close", "volume"}.issubset(df.columns)
        # First call must hit VCI.
        first_call_kwargs = fake_quote_cls.call_args_list[0].kwargs
        assert first_call_kwargs["symbol"] == "VNM"
        assert first_call_kwargs["source"] == "VCI"

    def test_fetch_normalizes_symbol_with_suffix(self):
        fake_module, fake_quote_cls, _ = _make_mock_vnstock_module()
        with _patch_vnstock(fake_module):
            VNStockLoader().fetch(["VNM.HOSE"], "2024-01-01", "2024-01-31")

        # vnstock.Quote should be called with the bare ticker, not the suffixed one.
        first_call_kwargs = fake_quote_cls.call_args_list[0].kwargs
        assert first_call_kwargs["symbol"] == "VNM"


# ---------------------------------------------------------------------------
# Group F — fetch fallback chain
# ---------------------------------------------------------------------------

def _quote_factory_per_source(source_outcomes):
    """Return a side-effect callable for ``Quote(symbol=..., source=...)``.

    ``source_outcomes`` maps source name -> either a DataFrame or an Exception.
    Each call constructs a fresh MagicMock instance whose ``history`` either
    returns the DataFrame or raises the exception.
    """
    def _factory(*, symbol, source):
        outcome = source_outcomes[source]
        instance = MagicMock()
        if isinstance(outcome, Exception):
            instance.history.side_effect = outcome
        else:
            instance.history.return_value = outcome
        return instance
    return _factory


def _make_fallback_module(source_outcomes):
    fake_module = MagicMock()
    fake_quote_cls = MagicMock(side_effect=_quote_factory_per_source(source_outcomes))
    fake_module.Quote = fake_quote_cls
    return fake_module, fake_quote_cls


class TestFetchFallback:
    def test_fetch_falls_back_vci_to_tcbs(self):
        tcbs_df = pd.DataFrame({
            "time": pd.to_datetime(["2024-01-02"]),
            "open": [200.0], "high": [205.0], "low": [199.0],
            "close": [202.0], "volume": [55_555],
        })
        fake_module, fake_quote_cls = _make_fallback_module({
            "VCI": RuntimeError("VCI down"),
            "TCBS": tcbs_df,
            "MSN": pd.DataFrame(),  # never reached
        })
        with _patch_vnstock(fake_module):
            result = VNStockLoader().fetch(["VNM"], "2024-01-01", "2024-01-31")

        assert "VNM" in result
        assert result["VNM"]["volume"].iloc[0] == 55_555
        # Must have tried VCI then TCBS.
        sources_called = [c.kwargs["source"] for c in fake_quote_cls.call_args_list]
        assert sources_called[:2] == ["VCI", "TCBS"]

    def test_fetch_falls_back_to_msn(self):
        msn_df = pd.DataFrame({
            "time": pd.to_datetime(["2024-01-02"]),
            "open": [300.0], "high": [305.0], "low": [299.0],
            "close": [302.0], "volume": [77_777],
        })
        fake_module, fake_quote_cls = _make_fallback_module({
            "VCI": RuntimeError("VCI down"),
            "TCBS": RuntimeError("TCBS down"),
            "MSN": msn_df,
        })
        with _patch_vnstock(fake_module):
            result = VNStockLoader().fetch(["VNM"], "2024-01-01", "2024-01-31")

        assert "VNM" in result
        assert result["VNM"]["volume"].iloc[0] == 77_777
        sources_called = [c.kwargs["source"] for c in fake_quote_cls.call_args_list]
        assert sources_called == ["VCI", "TCBS", "MSN"]

    def test_fetch_all_sources_fail(self, caplog):
        fake_module, fake_quote_cls = _make_fallback_module({
            "VCI": RuntimeError("VCI"),
            "TCBS": RuntimeError("TCBS"),
            "MSN": RuntimeError("MSN"),
        })
        with _patch_vnstock(fake_module), caplog.at_level("WARNING"):
            result = VNStockLoader().fetch(["VNM"], "2024-01-01", "2024-01-31")

        # Symbol must be omitted, not raised.
        assert "VNM" not in result
        assert result == {}
        # Must have walked the entire chain.
        sources_called = [c.kwargs["source"] for c in fake_quote_cls.call_args_list]
        assert sources_called == ["VCI", "TCBS", "MSN"]
        # And logged a warning.
        assert any("vnstock failed for VNM" in rec.message for rec in caplog.records)

    def test_fetch_partial_success(self):
        good_df = pd.DataFrame({
            "time": pd.to_datetime(["2024-01-02"]),
            "open": [100.0], "high": [101.0], "low": [99.0],
            "close": [100.5], "volume": [1_234],
        })

        def factory(*, symbol, source):
            instance = MagicMock()
            if symbol == "VNM" and source == "VCI":
                instance.history.return_value = good_df
            else:
                instance.history.side_effect = RuntimeError(f"{source} down for {symbol}")
            return instance

        fake_module = MagicMock()
        fake_module.Quote = MagicMock(side_effect=factory)

        with _patch_vnstock(fake_module):
            result = VNStockLoader().fetch(
                ["VNM", "FAIL"], "2024-01-01", "2024-01-31",
            )

        assert "VNM" in result
        assert "FAIL" not in result
        assert result["VNM"]["volume"].iloc[0] == 1_234


# ---------------------------------------------------------------------------
# Group G — Date validation
# ---------------------------------------------------------------------------

class TestDateValidation:
    def test_fetch_invalid_date_raises(self):
        fake_module, _, _ = _make_mock_vnstock_module()
        with _patch_vnstock(fake_module):
            with pytest.raises(ValueError):
                VNStockLoader().fetch(["VNM"], "2024-12-31", "2024-01-01")


# ---------------------------------------------------------------------------
# Group H — Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_loader_registered(self):
        _ensure_registered()
        assert "vnstock" in LOADER_REGISTRY
        assert LOADER_REGISTRY["vnstock"] is VNStockLoader

    def test_fallback_chain_vn_equity(self):
        assert FALLBACK_CHAINS["vn_equity"] == ["vnstock"]

    def test_fallback_chain_vn_index(self):
        assert FALLBACK_CHAINS["vn_index"] == ["vnstock"]

    def test_fallback_chain_vn_futures(self):
        assert FALLBACK_CHAINS["vn_futures"] == ["vnstock"]
