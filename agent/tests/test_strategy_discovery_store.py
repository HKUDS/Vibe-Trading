"""Frozen-contract tests for ``src.strategy_discovery.store`` — issue #969.

``EvidenceStore`` is the facade-owned SQLite cache keyed by
``(strategy_id, regime)``. These tests pin: explicit tmp-path initialization,
auto table creation, upsert-replace semantics, filtered+sorted reads,
``clear()`` / ``row_count()``, NaN rejection, tuple→JSON→tuple
round-tripping of ``date_ranges`` / ``warnings``, and skip-with-warning for
rows carrying an unknown regime (externally tampered database). A fresh
database MUST be empty (AC7: no seed corpus is baked into the package).

No network, no wall clock: every row carries an explicit ``last_verified``.
"""

from __future__ import annotations

import sqlite3

import pytest

try:
    from src.strategy_discovery import models as sd_models
    from src.strategy_discovery.evidence_store import EvidenceStore

    STORE_AVAILABLE = True
except ImportError:
    sd_models = None
    EvidenceStore = None
    STORE_AVAILABLE = False

requires_store = pytest.mark.skipif(
    not STORE_AVAILABLE,
    reason="waiting on sibling A: src.strategy_discovery.evidence_store not landed yet (issue #969)",
)


def _make_store(db_file):
    """Construct EvidenceStore tolerantly across positional/keyword db path."""
    try:
        return EvidenceStore(db_file)
    except TypeError:
        for kw in ("db_path", "path", "db_file", "database"):
            try:
                return EvidenceStore(**{kw: db_file})
            except TypeError:
                continue
        raise


def _row(strategy_id="alpha_zoo:a1", regime="bear_market", trades=12, **overrides):
    fields = dict(
        strategy_id=strategy_id,
        regime=regime,
        trades_in_regime=trades,
        position_size=1.0,
        return_in_regime=0.083,
        benchmark_in_regime=-0.246,
        excess_in_regime=0.329,
        sharpe_in_regime=0.72,
        max_drawdown_in_regime=-0.152,
        date_ranges=("2018-01 to 2018-12", "2022-01 to 2022-12"),
        breakeven_fee_bps=45.2,
        cost_sensitive=False,
        evidence_quality="adequate",
        warnings=("insufficient-trades: sample", "short-coverage: sample"),
        last_verified="2026-08-01",
        evidence_stage="backtest",
        provenance="/tmp/runs/fixture_run",
        regime_definition='{"bear_threshold": -0.1, "benchmark_window": 252}',
    )
    fields.update(overrides)
    return sd_models.EvidenceRow(**fields)


@requires_store
class TestInitialization:
    def test_explicit_tmp_path_db_and_table_auto_created(self, tmp_path) -> None:
        db_file = tmp_path / "evidence.db"
        store = _make_store(db_file)
        assert db_file.exists()
        with sqlite3.connect(db_file) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert any(
            "strategy_regime_evidence" in t for t in tables
        ), f"expected the strategy_regime_evidence table to be auto-created, found {tables}"
        assert store.row_count() == 0

    def test_fresh_db_is_empty_no_seed_corpus(self, tmp_path) -> None:
        # AC7: a brand-new store has no rows — evidence only comes from
        # reproducible runs written through upsert_rows/rebuild_evidence.
        store = _make_store(tmp_path / "fresh.db")
        assert store.row_count() == 0
        assert store.get_rows() == []


@requires_store
class TestUpsertAndRead:
    def test_upsert_then_get_roundtrip_all_fields(self, tmp_path) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows([_row()])
        rows = store.get_rows()
        assert len(rows) == 1
        got = rows[0]
        src = _row()
        for field in (
            "strategy_id",
            "regime",
            "trades_in_regime",
            "position_size",
            "return_in_regime",
            "benchmark_in_regime",
            "excess_in_regime",
            "sharpe_in_regime",
            "max_drawdown_in_regime",
            "date_ranges",
            "breakeven_fee_bps",
            "cost_sensitive",
            "evidence_quality",
            "warnings",
            "last_verified",
            "evidence_stage",
            "provenance",
            "regime_definition",
        ):
            assert getattr(got, field) == getattr(
                src, field
            ), f"field {field} did not round-trip"

    def test_upsert_replaces_on_same_key(self, tmp_path) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows([_row(trades=12)])
        store.upsert_rows([_row(trades=99, sharpe_in_regime=1.5)])
        assert store.row_count() == 1
        got = store.get_rows()[0]
        assert got.trades_in_regime == 99
        assert got.sharpe_in_regime == 1.5

    def test_get_rows_filters_by_strategy_id_and_regime(self, tmp_path) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows(
            [
                _row(strategy_id="alpha_zoo:a1", regime="bear_market"),
                _row(strategy_id="sdm:s1", regime="bull_market"),
            ]
        )
        by_strategy = store.get_rows(strategy_id="alpha_zoo:a1")
        assert len(by_strategy) == 1
        assert by_strategy[0].strategy_id == "alpha_zoo:a1"
        by_regime = store.get_rows(regime="bull_market")
        assert len(by_regime) == 1
        assert by_regime[0].regime == "bull_market"

    def test_get_rows_sorted_by_strategy_then_regime(self, tmp_path) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows(
            [
                _row(strategy_id="sdm:z", regime="structural"),
                _row(strategy_id="alpha_zoo:a", regime="bull_market"),
                _row(strategy_id="alpha_zoo:a", regime="bear_market"),
            ]
        )
        rows = store.get_rows()
        keys = [(r.strategy_id, r.regime) for r in rows]
        assert keys == sorted(keys)

    def test_clear_empties_store(self, tmp_path) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows([_row(), _row(strategy_id="sdm:s1")])
        assert store.row_count() == 2
        store.clear()
        assert store.row_count() == 0
        assert store.get_rows() == []


@requires_store
class TestValidationAndSerialization:
    def test_nan_in_row_raises_value_error(self, tmp_path) -> None:
        store = _make_store(tmp_path / "s.db")
        bad = _row(sharpe_in_regime=float("nan"))
        with pytest.raises(ValueError):
            store.upsert_rows([bad])
        assert store.row_count() == 0

    def test_date_ranges_and_warnings_roundtrip_tuple_json_tuple(
        self, tmp_path
    ) -> None:
        store = _make_store(tmp_path / "s.db")
        date_ranges = ("2018-01 to 2018-12", "2022-01 to 2022-12")
        warnings = (
            "insufficient-trades: only 7 trades",
            "cost-sensitive: breakeven 3.1 bps",
        )
        store.upsert_rows([_row(date_ranges=date_ranges, warnings=warnings)])
        got = store.get_rows()[0]
        assert got.date_ranges == date_ranges
        assert isinstance(got.date_ranges, tuple)
        assert got.warnings == warnings
        assert isinstance(got.warnings, tuple)

        store.upsert_rows([_row(strategy_id="sdm:empty", date_ranges=(), warnings=())])
        empty = store.get_rows(strategy_id="sdm:empty")[0]
        assert empty.date_ranges == ()
        assert empty.warnings == ()


@requires_store
class TestUnknownRegimeSkip:
    """Rows with an off-vocabulary regime can only reach the SQLite file via
    external tampering (``EvidenceRow`` rejects unknown regimes on the write
    path). The never-invent contract drops them from reads with a warning —
    never remaps them onto a documented regime."""

    _TAMPERED_INSERT = (
        "INSERT INTO strategy_regime_evidence ("
        "strategy_id, regime, trades_in_regime, date_ranges, "
        "breakeven_fee_bps, cost_sensitive, evidence_quality, warnings, "
        "last_verified"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    def _tamper_row(self, store, strategy_id, regime) -> None:
        """Bypass the validated write path exactly like an external editor."""
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                self._TAMPERED_INSERT,
                (strategy_id, regime, 42, "[]", None, 0, "adequate", "[]", ""),
            )
            conn.commit()

    def test_unknown_regime_row_is_skipped_not_remapped(self, tmp_path, caplog) -> None:
        store = _make_store(tmp_path / "s.db")
        self._tamper_row(store, "sdm:tampered", "sideways")
        with caplog.at_level("WARNING"):
            rows = store.get_rows()
        assert rows == [], (
            "unknown-regime rows must be dropped from reads, never remapped "
            f"onto a documented regime: {rows!r}"
        )
        assert any(
            "sideways" in record.message for record in caplog.records
        ), "skipping a tampered row must log a warning naming the regime"

    def test_valid_rows_survive_alongside_tampered_row(self, tmp_path, caplog) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows([_row(strategy_id="alpha_zoo:ok", regime="bear_market")])
        self._tamper_row(store, "sdm:tampered", "monsoon")
        with caplog.at_level("WARNING"):
            rows = store.get_rows()
        assert [(r.strategy_id, r.regime) for r in rows] == [
            ("alpha_zoo:ok", "bear_market")
        ]
        assert rows[0].regime == "bear_market"
        assert any("monsoon" in record.message for record in caplog.records)

    def test_row_count_still_counts_physical_rows(self, tmp_path) -> None:
        # row_count() is a raw COUNT(*) over the file — the skip happens in
        # row hydration, so it reflects physical rows including tampered ones.
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows([_row(strategy_id="alpha_zoo:ok")])
        self._tamper_row(store, "sdm:tampered", "sideways")
        assert store.row_count() == 2
        assert store.get_rows() != []
        assert store.get_rows()[0].strategy_id == "alpha_zoo:ok"

    def test_unknown_evidence_stage_row_is_skipped(self, tmp_path, caplog) -> None:
        store = _make_store(tmp_path / "s.db")
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                "INSERT INTO strategy_regime_evidence ("
                "strategy_id, regime, trades_in_regime, date_ranges, "
                "cost_sensitive, evidence_quality, warnings, last_verified, "
                "evidence_stage"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "sdm:tampered",
                    "bear_market",
                    42,
                    "[]",
                    0,
                    "adequate",
                    "[]",
                    "",
                    "rumor",
                ),
            )
            conn.commit()
        with caplog.at_level("WARNING"):
            rows = store.get_rows()
        assert rows == []
        assert any(
            "rumor" in record.message for record in caplog.records
        ), "skipping an unknown-stage row must log a warning naming the stage"


@requires_store
class TestSchemaMigration:
    """A cache DB written before the provenance/stage columns existed is
    disposable: opening it drops and recreates the table rather than serving
    rows that cannot carry the #969 contract."""

    _LEGACY_SCHEMA = """
    CREATE TABLE strategy_regime_evidence (
        strategy_id            TEXT NOT NULL,
        regime                 TEXT NOT NULL,
        trades_in_regime       INTEGER NOT NULL,
        position_size          REAL,
        return_in_regime       REAL,
        benchmark_in_regime    REAL,
        excess_in_regime       REAL,
        sharpe_in_regime       REAL,
        max_drawdown_in_regime REAL,
        date_ranges            TEXT NOT NULL,
        breakeven_fee_bps      REAL,
        cost_sensitive         INTEGER NOT NULL DEFAULT 0,
        evidence_quality       TEXT NOT NULL,
        warnings               TEXT NOT NULL,
        last_verified          TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (strategy_id, regime)
    )
    """

    def test_stale_cache_is_dropped_and_recreated_empty(self, tmp_path, caplog) -> None:
        db_file = tmp_path / "stale.db"
        with sqlite3.connect(db_file) as conn:
            conn.execute(self._LEGACY_SCHEMA)
            conn.execute(
                "INSERT INTO strategy_regime_evidence ("
                "strategy_id, regime, trades_in_regime, date_ranges, "
                "cost_sensitive, evidence_quality, warnings"
                ") VALUES ('sdm:legacy', 'bear_market', 12, '[]', 0, "
                "'adequate', '[]')"
            )
            conn.commit()

        with caplog.at_level("WARNING"):
            store = _make_store(db_file)
        assert (
            store.row_count() == 0
        ), "a pre-provenance cache must be dropped, not served"
        with sqlite3.connect(db_file) as conn:
            columns = {
                r[1]
                for r in conn.execute(
                    "PRAGMA table_info(strategy_regime_evidence)"
                ).fetchall()
            }
        for column in ("evidence_stage", "provenance", "regime_definition"):
            assert column in columns, f"recreated table missing {column}"
        assert any(
            "predates columns" in record.message for record in caplog.records
        ), "dropping a stale cache must log a warning"

        store.upsert_rows([_row()])
        assert store.row_count() == 1

    def test_current_schema_is_not_dropped(self, tmp_path, caplog) -> None:
        store = _make_store(tmp_path / "s.db")
        store.upsert_rows([_row()])
        with caplog.at_level("WARNING"):
            reopened = _make_store(tmp_path / "s.db")
        assert (
            reopened.row_count() == 1
        ), "a current-schema cache must survive re-open untouched"
        assert not any(
            "predates columns" in record.message for record in caplog.records
        )
