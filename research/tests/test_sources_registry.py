"""
Tests for research/lib/sources.py — SOURCE_REGISTRY and TRANSFORM_REGISTRY.

Covers:
  (a) All keys in SOURCE_REGISTRY and TRANSFORM_REGISTRY can be looked up
  (b) All "available" entries have a callable fetcher (callable(fetcher) is True)
  (c) All "unavailable" entries have fetcher = None
  (d) Each transform in TRANSFORM_REGISTRY applied to a 100-row random pd.Series
      produces output of the same length as input

These tests are network-free; no fetchers are called.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Bootstrap: add research/ to sys.path so lib.sources is importable directly.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from lib.sources import SOURCE_REGISTRY, TRANSFORM_REGISTRY, SourceSpec


# ---------------------------------------------------------------------------
# (a) Registry key lookup
# ---------------------------------------------------------------------------


class TestRegistryKeys:
    _EXPECTED_SOURCES = {
        "okx_funding",
        "okx_candles",
        "bybit_oi",
        "coinglass_liq",
        "glassnode_pub",
        "deribit_skew",
        "alt_fng",
        "okx_orderbook",
    }

    _EXPECTED_TRANSFORMS = {
        "raw",
        "z_30d",
        "z_90d",
        "pct_change_24h",
        "ma_diff_7d_30d",
    }

    def test_all_expected_source_keys_present(self) -> None:
        for key in self._EXPECTED_SOURCES:
            assert key in SOURCE_REGISTRY, f"SOURCE_REGISTRY missing key: {key!r}"

    def test_all_expected_transform_keys_present(self) -> None:
        for key in self._EXPECTED_TRANSFORMS:
            assert key in TRANSFORM_REGISTRY, f"TRANSFORM_REGISTRY missing key: {key!r}"

    def test_source_registry_has_exactly_8_entries(self) -> None:
        assert len(SOURCE_REGISTRY) == 8

    def test_transform_registry_has_exactly_5_entries(self) -> None:
        assert len(TRANSFORM_REGISTRY) == 5

    def test_source_registry_values_are_source_spec(self) -> None:
        for key, spec in SOURCE_REGISTRY.items():
            assert isinstance(spec, SourceSpec), (
                f"SOURCE_REGISTRY[{key!r}] is not a SourceSpec instance"
            )


# ---------------------------------------------------------------------------
# (b) Available entries have callable fetchers
# ---------------------------------------------------------------------------


class TestAvailableSources:
    def test_available_entries_have_callable_fetcher(self) -> None:
        for key, spec in SOURCE_REGISTRY.items():
            if spec.status == "available":
                assert callable(spec.fetcher), (
                    f"SOURCE_REGISTRY[{key!r}] is 'available' but fetcher is not callable"
                )

    def test_available_entries_have_non_none_fetcher(self) -> None:
        for key, spec in SOURCE_REGISTRY.items():
            if spec.status == "available":
                assert spec.fetcher is not None, (
                    f"SOURCE_REGISTRY[{key!r}] is 'available' but fetcher is None"
                )

    def test_exactly_3_available_sources(self) -> None:
        available = [k for k, v in SOURCE_REGISTRY.items() if v.status == "available"]
        assert len(available) == 3, f"Expected 3 available sources, got {len(available)}: {available}"

    def test_known_available_keys(self) -> None:
        available_keys = {k for k, v in SOURCE_REGISTRY.items() if v.status == "available"}
        assert available_keys == {"okx_funding", "okx_candles", "bybit_oi"}


# ---------------------------------------------------------------------------
# (c) Unavailable entries have fetcher = None
# ---------------------------------------------------------------------------


class TestUnavailableSources:
    def test_unavailable_entries_have_none_fetcher(self) -> None:
        for key, spec in SOURCE_REGISTRY.items():
            if spec.status == "unavailable":
                assert spec.fetcher is None, (
                    f"SOURCE_REGISTRY[{key!r}] is 'unavailable' but fetcher is not None"
                )

    def test_exactly_5_unavailable_sources(self) -> None:
        unavailable = [k for k, v in SOURCE_REGISTRY.items() if v.status == "unavailable"]
        assert len(unavailable) == 5, (
            f"Expected 5 unavailable sources, got {len(unavailable)}: {unavailable}"
        )

    def test_known_unavailable_keys(self) -> None:
        unavailable_keys = {k for k, v in SOURCE_REGISTRY.items() if v.status == "unavailable"}
        assert unavailable_keys == {
            "coinglass_liq",
            "glassnode_pub",
            "deribit_skew",
            "alt_fng",
            "okx_orderbook",
        }


# ---------------------------------------------------------------------------
# (d) Transforms preserve Series length
# ---------------------------------------------------------------------------


class TestTransformOutputLength:
    @pytest.fixture
    def random_series(self) -> pd.Series:
        rng = np.random.default_rng(42)
        return pd.Series(rng.standard_normal(100))

    @pytest.mark.parametrize("transform_key", list(TRANSFORM_REGISTRY.keys()))
    def test_transform_preserves_length(
        self, transform_key: str, random_series: pd.Series
    ) -> None:
        fn = TRANSFORM_REGISTRY[transform_key]
        result = fn(random_series)
        assert isinstance(result, pd.Series), (
            f"TRANSFORM_REGISTRY[{transform_key!r}] did not return a pd.Series"
        )
        assert len(result) == len(random_series), (
            f"TRANSFORM_REGISTRY[{transform_key!r}] changed Series length: "
            f"input={len(random_series)}, output={len(result)}"
        )

    def test_raw_transform_is_identity(self, random_series: pd.Series) -> None:
        result = TRANSFORM_REGISTRY["raw"](random_series)
        pd.testing.assert_series_equal(result, random_series)

    def test_z_30d_produces_nan_for_early_rows(self, random_series: pd.Series) -> None:
        """Rolling(90) on a 100-row series should have NaN for first 89 rows."""
        result = TRANSFORM_REGISTRY["z_30d"](random_series)
        assert result.iloc[:89].isna().all(), (
            "z_30d rolling(90) should produce NaN for first 89 rows on a 100-row series"
        )

    def test_z_90d_produces_nan_for_early_rows(self) -> None:
        """Rolling(270) on a 300-row series should have NaN for first 269 rows."""
        rng = np.random.default_rng(99)
        s = pd.Series(rng.standard_normal(300))
        result = TRANSFORM_REGISTRY["z_90d"](s)
        assert result.iloc[:269].isna().all(), (
            "z_90d rolling(270) should produce NaN for first 269 rows on a 300-row series"
        )
