"""
Tests for features store and evidence helpers added to factor_io.py.

Covers tasks 3.1–3.4:
  - dump_features / load_features / load_features_meta
  - dump_evidence / load_evidence
  - append_feature_column
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lib.factor_io import (
    FEATURES_SCHEMA_VERSION,
    append_feature_column,
    dump_evidence,
    dump_features,
    load_evidence,
    load_features,
    load_features_meta,
)


def _make_series(n: int = 10) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.Series(range(n), index=idx, dtype="float64")


# ---------------------------------------------------------------------------
# 3.1 / 3.2 — features roundtrip
# ---------------------------------------------------------------------------


def test_dump_load_features_roundtrip(tmp_path: Path) -> None:
    s1 = _make_series(10)
    s2 = _make_series(10) * 2.0
    dump_features("ETH-USDT-SWAP", {"feat_a": s1, "feat_b": s2}, tmp_path)

    df = load_features("ETH-USDT-SWAP", manifests_dir=tmp_path)
    assert list(df.columns) == ["feat_a", "feat_b"]
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert len(df) == 10


def test_load_features_missing_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="features"):
        load_features("eth", manifests_dir=tmp_path)


def test_load_features_meta_schema_version_mismatch_raises_value_error(tmp_path: Path) -> None:
    # Write a valid parquet first so meta path resolves correctly.
    s = _make_series()
    dump_features("eth", {"x": s}, tmp_path)

    # Overwrite meta with a wrong schema version.
    meta_path = tmp_path / "features_eth.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["schema_version"] = 999
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_features_meta("eth", manifests_dir=tmp_path)


def test_dump_features_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        dump_features("eth", {}, tmp_path)


def test_dump_features_meta_content(tmp_path: Path) -> None:
    s = _make_series(5)
    dump_features("BTC-USDT-SWAP", {"vol": s}, tmp_path)
    meta = load_features_meta("BTC-USDT-SWAP", manifests_dir=tmp_path)
    assert meta["schema_version"] == FEATURES_SCHEMA_VERSION
    assert meta["n_rows"] == 5
    assert "vol" in meta["feature_names"]


# ---------------------------------------------------------------------------
# 3.3 — evidence roundtrip
# ---------------------------------------------------------------------------


def test_dump_evidence_load_evidence_roundtrip(tmp_path: Path) -> None:
    records = [
        {"factor": "funding_rate", "ic": 0.12, "rank": 1},
        {"factor": "momentum_24h", "ic": 0.08, "rank": 2},
    ]
    dump_evidence("eth", records, tmp_path)
    loaded = load_evidence("eth", manifests_dir=tmp_path)
    assert loaded == records


def test_load_evidence_missing_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_evidence("eth", manifests_dir=tmp_path)


def test_dump_evidence_deterministic_json(tmp_path: Path) -> None:
    """dump_evidence must write sorted-key, ensure_ascii=False, indent=2 JSON."""
    records = [{"z_key": 1, "a_key": 2}]
    path = dump_evidence("eth", records, tmp_path)
    raw = path.read_text(encoding="utf-8")
    # Keys should appear in sorted order.
    assert raw.index('"a_key"') < raw.index('"z_key"')


# ---------------------------------------------------------------------------
# 3.4 — append_feature_column
# ---------------------------------------------------------------------------


def test_append_feature_column_adds_column(tmp_path: Path) -> None:
    s = _make_series(10)
    dump_features("eth", {"existing": s}, tmp_path)

    new_col = _make_series(10) * 3.0
    append_feature_column("eth", "new_feat", new_col, manifests_dir=tmp_path)

    df = load_features("eth", manifests_dir=tmp_path)
    assert "new_feat" in df.columns
    assert "existing" in df.columns


def test_append_feature_column_overwrites_existing(tmp_path: Path) -> None:
    s = _make_series(10)
    dump_features("eth", {"col_a": s}, tmp_path)

    updated = _make_series(10) * 99.0
    append_feature_column("eth", "col_a", updated, manifests_dir=tmp_path)

    df = load_features("eth", manifests_dir=tmp_path)
    assert "col_a" in df.columns
    # Values should reflect the update.
    assert (df["col_a"] == updated.values).all()


def test_append_feature_column_all_nan_raises(tmp_path: Path) -> None:
    s = _make_series(10)
    dump_features("eth", {"existing": s}, tmp_path)

    nan_series = pd.Series(
        [float("nan")] * 10,
        index=s.index,
    )
    with pytest.raises(ValueError, match="All-NaN"):
        append_feature_column("eth", "bad", nan_series, manifests_dir=tmp_path)


def test_append_feature_column_low_coverage_raises(tmp_path: Path) -> None:
    n = 20
    s = _make_series(n)
    dump_features("eth", {"existing": s}, tmp_path)

    # Only 2 out of 20 non-NaN → 10% coverage < 50% threshold.
    import numpy as np

    vals = [float("nan")] * n
    vals[0] = 1.0
    vals[1] = 2.0
    low_cov = pd.Series(vals, index=s.index)

    with pytest.raises(ValueError, match="Coverage too low"):
        append_feature_column("eth", "sparse", low_cov, manifests_dir=tmp_path, coverage_threshold=0.5)


def test_append_feature_column_updates_meta(tmp_path: Path) -> None:
    s = _make_series(10)
    dump_features("eth", {"feat_x": s}, tmp_path)

    new_col = _make_series(10) * 5.0
    append_feature_column("eth", "feat_y", new_col, manifests_dir=tmp_path)

    meta = load_features_meta("eth", manifests_dir=tmp_path)
    assert "feat_y" in meta["feature_names"]
    assert "feat_x" in meta["feature_names"]
    assert meta["n_rows"] == 10
