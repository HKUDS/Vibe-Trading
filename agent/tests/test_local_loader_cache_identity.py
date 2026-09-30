"""Local cache entries must identify the configured file and schema."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from backtest.loaders import base, local_loader


def _source(path: Path) -> dict:
    return {"symbol": "AAA.US", "type": "csv", "path": str(path)}


def _write(path: Path, value: float) -> None:
    pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-03"],
            "open": [value, value],
            "high": [value + 1, value + 1],
            "low": [value - 1, value - 1],
            "close": [value, value],
            "volume": [100, 100],
        }
    ).to_csv(path, index=False)


def test_local_cache_does_not_reuse_another_configured_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing only a symbol's file must not serve the previous file's bars."""
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    config = tmp_path / "config.yaml"
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config)
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    _write(first, 10)
    _write(second, 20)

    def fetch(path: Path) -> pd.DataFrame:
        config.write_text(yaml.safe_dump({"sources": [_source(path)]}))
        return local_loader.DataLoader().fetch(["AAA.US"], "2025-01-02", "2025-01-03")[
            "AAA.US"
        ]

    assert fetch(first)["close"].tolist() == [10, 10]
    assert list((tmp_path / "cache").rglob("*.parquet")), "exercise the real cache"
    assert fetch(second)["close"].tolist() == [20, 20]


def test_identical_local_config_still_hits_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the existing opt-in settled-data cache contract for one source."""
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    path = tmp_path / "bars.csv"
    _write(path, 10)
    monkeypatch.setattr(
        local_loader, "_load_config", lambda: {"sources": [_source(path)]}
    )
    before = local_loader.DataLoader().fetch(["AAA.US"], "2025-01-02", "2025-01-03")

    def unexpected_read(*args: object) -> None:
        raise AssertionError("identical configured source should hit its cache")

    monkeypatch.setitem(local_loader._READERS, "csv", unexpected_read)
    after = local_loader.DataLoader().fetch(["AAA.US"], "2025-01-02", "2025-01-03")
    pd.testing.assert_frame_equal(before["AAA.US"], after["AAA.US"])


def test_local_cache_separates_queries_on_the_same_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two query declarations can select different bars for the same symbol."""
    import duckdb

    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    database = tmp_path / "bars.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE bars AS SELECT '2025-01-02' AS date, "
            "10 AS open, 21 AS high, 9 AS low, 10 AS close, "
            "20 AS alternate_close, 100 AS volume"
        )

    def fetch(close: str) -> pd.DataFrame:
        entry = {
            "symbol": "AAA.US",
            "type": "duckdb",
            "db_path": str(database),
            "query": f"SELECT date, open, high, low, {close} AS close, volume FROM bars",
        }
        monkeypatch.setattr(local_loader, "_load_config", lambda: {"sources": [entry]})
        return local_loader.DataLoader().fetch(["AAA.US"], "2025-01-02", "2025-01-03")[
            "AAA.US"
        ]

    assert fetch("close")["close"].tolist() == [10]
    assert fetch("alternate_close")["close"].tolist() == [20]


@pytest.mark.parametrize("cache_enabled", [False, True])
def test_ignored_yaml_metadata_does_not_break_local_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache_enabled: bool
) -> None:
    """YAML dates in source annotations aren't input fields or cache selectors."""
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: cache_enabled)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    path = tmp_path / "bars.csv"
    _write(path, 10)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump({"sources": [_source(path)]}) + "  updated_at: 2025-01-01\n"
    )
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config)

    frame = local_loader.DataLoader().fetch(["AAA.US"], "2025-01-02", "2025-01-03")

    assert frame["AAA.US"]["close"].tolist() == [10, 10]
