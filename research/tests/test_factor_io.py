"""
Unit tests for research/lib/factor_io.py

(a) dump → load round-trip: data consistent
(b) meta.json has all required fields
(c) load missing file → FileNotFoundError with "run stage1_factors first"
(d) schema_version mismatch → ValueError

Run from research/ as:
    python -m pytest tests/test_factor_io.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Bootstrap: ensure research/ is on sys.path so lib.* is importable.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from lib.factor_io import SCHEMA_VERSION, dump_factor_values, load_factor_meta, load_factor_values


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_series(n: int = 100, seed: int = 42, name: str = "factor") -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.Series(rng.standard_normal(n), index=idx, name=name)


def _make_factor_dict(n: int = 100) -> dict[str, pd.Series]:
    return {
        "funding_rate": _make_series(n, seed=1, name="funding_rate"),
        "oi_change_24h": _make_series(n, seed=2, name="oi_change_24h"),
        "fng": _make_series(n, seed=3, name="fng"),
    }


# ---------------------------------------------------------------------------
# (a) dump → load round-trip: data consistent
# ---------------------------------------------------------------------------


class TestDumpLoadRoundTrip:
    def test_roundtrip_values_close(self, tmp_path: Path):
        """After dump then load, values match within float64 tolerance."""
        original = _make_factor_dict()
        dump_factor_values("eth", original, tmp_path)

        loaded = load_factor_values("eth", manifests_dir=tmp_path)

        assert set(loaded.columns) == set(original.keys())
        for col in original:
            # check_freq=False because parquet does not persist DatetimeIndex.freq
            pd.testing.assert_series_equal(
                loaded[col],
                original[col].rename(col).astype("float64"),
                check_names=False,
                check_freq=False,
                rtol=1e-9,
            )

    def test_roundtrip_index_is_utc_datetime(self, tmp_path: Path):
        """Loaded DataFrame has a UTC-aware DatetimeIndex."""
        dump_factor_values("eth", _make_factor_dict(), tmp_path)
        loaded = load_factor_values("eth", manifests_dir=tmp_path)

        assert isinstance(loaded.index, pd.DatetimeIndex)
        assert loaded.index.tz is not None
        assert str(loaded.index.tz) == "UTC"

    def test_roundtrip_shape_preserved(self, tmp_path: Path):
        n = 150
        original = _make_factor_dict(n)
        dump_factor_values("eth", original, tmp_path)
        loaded = load_factor_values("eth", manifests_dir=tmp_path)

        assert loaded.shape == (n, len(original))

    def test_accepts_full_ticker_symbol(self, tmp_path: Path):
        """dump and load both accept 'ETH-USDT-SWAP' and normalize to 'eth'."""
        original = _make_factor_dict()
        dump_factor_values("ETH-USDT-SWAP", original, tmp_path)

        # Parquet should be at factor_values_eth.parquet
        assert (tmp_path / "factor_values_eth.parquet").exists()

        # Load also accepts the full ticker form
        loaded = load_factor_values("ETH-USDT-SWAP", manifests_dir=tmp_path)
        assert loaded.shape[0] > 0

    def test_naive_index_localized_to_utc(self, tmp_path: Path):
        """Series with naive DatetimeIndex is coerced to UTC on dump."""
        idx = pd.date_range("2024-01-01", periods=50, freq="1h")  # no tz
        s = pd.Series(np.ones(50), index=idx, name="factor_x")
        dump_factor_values("btc", {"factor_x": s}, tmp_path)

        loaded = load_factor_values("btc", manifests_dir=tmp_path)
        assert loaded.index.tz is not None


# ---------------------------------------------------------------------------
# (b) meta.json has all required fields
# ---------------------------------------------------------------------------


class TestMetaRequiredFields:
    REQUIRED_FIELDS = {
        "schema_version",
        "symbol",
        "generated_at",
        "factor_names",
        "index_start",
        "index_end",
        "n_rows",
    }

    def test_all_required_fields_present(self, tmp_path: Path):
        dump_factor_values("eth", _make_factor_dict(), tmp_path)
        meta = load_factor_meta("eth", manifests_dir=tmp_path)
        for field in self.REQUIRED_FIELDS:
            assert field in meta, f"missing field: {field}"

    def test_meta_schema_version_correct(self, tmp_path: Path):
        dump_factor_values("eth", _make_factor_dict(), tmp_path)
        meta = load_factor_meta("eth", manifests_dir=tmp_path)
        assert meta["schema_version"] == SCHEMA_VERSION

    def test_meta_factor_names_match(self, tmp_path: Path):
        original = _make_factor_dict()
        dump_factor_values("eth", original, tmp_path)
        meta = load_factor_meta("eth", manifests_dir=tmp_path)
        assert set(meta["factor_names"]) == set(original.keys())

    def test_meta_n_rows_correct(self, tmp_path: Path):
        n = 77
        dump_factor_values("eth", _make_factor_dict(n), tmp_path)
        meta = load_factor_meta("eth", manifests_dir=tmp_path)
        assert meta["n_rows"] == n

    def test_meta_generated_at_is_iso8601(self, tmp_path: Path):
        """generated_at should be parseable as an ISO-8601 datetime string."""
        from datetime import datetime
        dump_factor_values("eth", _make_factor_dict(), tmp_path)
        meta = load_factor_meta("eth", manifests_dir=tmp_path)
        # Should not raise:
        dt = datetime.fromisoformat(meta["generated_at"])
        assert dt.tzinfo is not None  # UTC-aware


# ---------------------------------------------------------------------------
# (c) load missing file → FileNotFoundError with "run stage1_factors first"
# ---------------------------------------------------------------------------


class TestLoadMissingFile:
    def test_load_factor_values_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="run stage1_factors first"):
            load_factor_values("eth", manifests_dir=tmp_path)

    def test_load_factor_meta_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_factor_meta("eth", manifests_dir=tmp_path)

    def test_load_accepts_full_ticker_missing(self, tmp_path: Path):
        """FileNotFoundError is raised for full ticker when file missing."""
        with pytest.raises(FileNotFoundError, match="run stage1_factors first"):
            load_factor_values("ETH-USDT-SWAP", manifests_dir=tmp_path)


# ---------------------------------------------------------------------------
# (d) schema_version mismatch → ValueError
# ---------------------------------------------------------------------------


class TestSchemaVersionMismatch:
    def test_wrong_schema_version_raises_value_error(self, tmp_path: Path):
        # Write a meta.json with incorrect schema_version.
        bad_meta = {
            "schema_version": 999,
            "symbol": "eth",
            "generated_at": "2024-01-01T00:00:00+00:00",
            "factor_names": ["funding_rate"],
            "index_start": "2024-01-01T00:00:00+00:00",
            "index_end": "2024-01-01T10:00:00+00:00",
            "n_rows": 10,
        }
        meta_path = tmp_path / "factor_values_eth.meta.json"
        meta_path.write_text(json.dumps(bad_meta), encoding="utf-8")

        with pytest.raises(ValueError, match="schema_version"):
            load_factor_meta("eth", manifests_dir=tmp_path)

    def test_correct_schema_version_does_not_raise(self, tmp_path: Path):
        dump_factor_values("eth", _make_factor_dict(), tmp_path)
        # Should not raise:
        meta = load_factor_meta("eth", manifests_dir=tmp_path)
        assert meta["schema_version"] == SCHEMA_VERSION
