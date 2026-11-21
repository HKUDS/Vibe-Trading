"""Persistence and recovery tests for the read-only HK quote collector."""

from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from src.hk_data.collector import collect, load_symbols, main
from src.hk_data.storage import QuoteStore

NOW = datetime(2026, 11, 11, 7, 0, tzinfo=timezone.utc)


def envelope(
    *, observed=NOW, provider=None, price=400.0, source="yahoo", failure=False
):
    quote = {
        "symbol": "00700.HK",
        "source": source,
        "price": price,
        "currency": "HKD",
        "provider_time": (provider or observed - timedelta(minutes=15)).isoformat(),
        "observed_at_utc": observed.isoformat(),
        "status": "fresh",
        "volume": 1000,
        "volume_unit": "shares",
        "declared_delay_seconds": 900,
        "delay_status": "delayed",
    }
    return {
        "ok": not failure,
        "status": "error" if failure else "ok",
        "observed_at_utc": observed.isoformat(),
        "quotes": [] if failure else [quote],
        "missing": ["00700.HK"] if failure else [],
        "errors": [{"error": "Timeout"}] if failure else [],
    }


def test_resume_deduplicates_and_preserves_corrections(tmp_path):
    path = tmp_path / "quotes.sqlite3"
    first = envelope()
    with QuoteStore(path) as store:
        assert store.record_poll(first) == 1
    with QuoteStore(path) as store:
        assert (
            store.record_poll(
                envelope(
                    observed=NOW + timedelta(seconds=60),
                    provider=NOW - timedelta(minutes=15),
                )
            )
            == 0
        )
        assert (
            store.record_poll(
                envelope(
                    observed=NOW + timedelta(seconds=90),
                    provider=NOW - timedelta(minutes=15),
                    price=401,
                )
            )
            == 1
        )
        result = store.latest(["00700.HK"], now=NOW + timedelta(seconds=90))
        assert result["quotes"][0]["price"] == 401
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 2


def test_latest_does_not_relabel_failed_poll_as_fresh_quote(tmp_path):
    with QuoteStore(tmp_path / "quotes.sqlite3") as store:
        store.record_poll(envelope())
        store.record_poll(envelope(observed=NOW + timedelta(hours=1), failure=True))
        result = store.latest(["00700.HK"], now=NOW + timedelta(hours=1))
        assert result["quotes"][0]["status"] == "stale"
        assert result["quotes"][0]["age_seconds"] == 4500
        assert result["latest_poll"]["status"] == "error"
        assert result["status"] == "last_poll_failed"


def test_readonly_missing_archive_does_not_create_it(tmp_path):
    path = tmp_path / "missing" / "quotes.sqlite3"
    with pytest.raises((OSError, sqlite3.Error)):
        QuoteStore(path, readonly=True)
    assert not path.exists()


def test_retention_and_keep_all_mode(tmp_path):
    with QuoteStore(tmp_path / "retention.db") as store:
        store.record_poll(envelope(observed=NOW - timedelta(days=40)))
        store.record_poll(envelope())
        store.prune(0, now=NOW)
        assert store.latest(now=NOW)["stored_revisions"] == 2
        store.prune(30, now=NOW)
        assert store.latest(now=NOW)["stored_revisions"] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 1


def test_csv_missing_fields_and_text_universe(tmp_path):
    path = tmp_path / "symbols.csv"
    path.write_text(
        "name,yahoo_ticker\nTencent,0700.HK\nMissing\nHSBC,0005.HK\n", encoding="utf-8"
    )
    assert load_symbols(path) == ["00700.HK", "00005.HK"]
    path = tmp_path / "symbols.txt"
    path.write_text("# HK stocks\n700\n0700.HK\n5\n", encoding="utf-8")
    assert load_symbols(path) == ["00700.HK", "00005.HK"]


def test_failed_poll_backoff_recovers_and_persists_health(tmp_path):
    calls, sleeps, output = [], [], []

    def fetcher(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("Must not expose raw provider text")
        return envelope()

    with QuoteStore(tmp_path / "recovery.db") as store:
        collect(
            store,
            ["00700.HK"],
            cycles=3,
            retain_days=0,
            fetcher=fetcher,
            sleeper=sleeps.append,
            emit=lambda text, **kwargs: output.append(json.loads(text)),
        )
        assert store.connection.execute("SELECT COUNT(*) FROM polls").fetchone()[0] == 3
        assert store.latest(now=NOW)["latest_poll"]["ok"] is True
    assert len(sleeps) == 2
    assert 119 < sleeps[0] <= 120
    assert 59 < sleeps[1] <= 60
    assert [row["status"] for row in output] == ["error", "ok", "ok"]


def test_failure_never_shortens_a_long_poll_interval(tmp_path):
    sleeps = []
    with QuoteStore(tmp_path / "long.db") as store:
        collect(
            store,
            ["00700.HK"],
            cycles=2,
            interval_seconds=3600,
            retain_days=0,
            fetcher=lambda *args, **kwargs: envelope(failure=True),
            sleeper=sleeps.append,
            emit=lambda *args, **kwargs: None,
        )
    assert 3599 < sleeps[0] <= 3600


def test_latest_partial_filter_and_cli_readonly(tmp_path, capsys):
    path = tmp_path / "cli.db"
    with QuoteStore(path) as store:
        store.record_poll(envelope())
        result = store.latest(["700", "5"], now=NOW)
        assert result["status"] == "partial"
        assert result["missing"] == ["00005.HK"]
    assert main(["--db", str(path), "--latest", "--symbols", "700"]) == 0
    assert len(json.loads(capsys.readouterr().out)["quotes"]) == 1


def test_hsi_snapshot_cli_uses_full_roster_and_fast_defaults(tmp_path, monkeypatch):
    captured = {}

    def collector(store, symbols, **kwargs):
        captured.update(kwargs)
        captured["symbols"] = symbols
        return {"ok": True}

    monkeypatch.setattr("src.hk_data.collector.collect", collector)
    assert main(["--hsi-snapshot", "--once", "--db", str(tmp_path / "hsi.db")]) == 0
    assert len(set(captured["symbols"])) == 95
    assert captured["source"] == "tencent"
    assert captured["interval_seconds"] == 5
    assert captured["max_age_seconds"] == 60
