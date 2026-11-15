"""History lifecycle: actual compressed storage, quota, integrity and resumption."""

import json
import threading
import time
import pytest
from src.data_gateway.history_store import HistoryStore


def fake(symbol, start, end, interval):
    return [{"symbol": symbol, "time": start + "T09:35:00", "close": 100}], {
        "source": "fixture",
        "coverage": "fixture",
        "coverage_verified": True,
    }


@pytest.fixture
def store(tmp_path):
    result = HistoryStore(tmp_path, fetcher=fake)
    yield result
    result.close()


def spec():
    return dict(codes=["601398.SH", "600519.SH"], start_date="2021-01-01", end_date="2021-03-31", interval="5m")


def test_complete_rows_paginate_without_sampling_and_resume_skips_valid_chunks(store):
    calls = []
    store.fetcher = lambda *args: calls.append(args) or fake(*args)
    job = store.create(**spec())["id"]
    assert store.run(job)["completed_chunks"] == 6
    assert len(calls) == 6
    assert store.run(job)["rows"] == 6 and len(calls) == 6
    result = store.read(job, 1, 3)
    assert len(result["rows"]) == 3 and result["next_offset"] == 4 and not result["sampled"]
    store._path(job, 1).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        store.read(job, 1, 1)
    assert store.run(job)["state"] == "complete" and len(calls) == 7


def test_failure_preserves_completed_chunks_and_retry_resumes(store):
    calls = []

    def fetch(*args):
        calls.append(args)
        if len(calls) == 3:
            raise ValueError("known gap")
        return fake(*args)

    store.fetcher = fetch
    job = store.create(**spec())["id"]
    assert store.run(job)["state"] == "failed"
    assert store.status(job)["completed_chunks"] == 2
    assert store.run(job)["state"] == "complete"
    assert len(calls) == 7


def test_pin_idle_eviction_and_quota_reservations(store):
    a = store.create(**spec())["id"]
    store.run(a)
    store.pin(a, True)
    b = store.create(**spec())["id"]
    store.run(b)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET accessed=0")
    store.prune()
    assert store.status(a)["pinned"] == 1
    with pytest.raises(ValueError):
        store.status(b)
    store.settings(quota_bytes=4 * 1024**2)
    (store.directory / "quota-test.bin").write_bytes(b"x" * (3 * 1024**2))
    with pytest.raises(ValueError, match="quota"):
        store.create(**spec())
    assert store.status(a)["pinned"] == 1


def test_running_lease_blocks_delete_and_cancel_keeps_committed_prefix(store):
    entered, release = threading.Event(), threading.Event()

    def fetch(*args):
        entered.set()
        release.wait(3)
        return fake(*args)

    store.fetcher = fetch
    job = store.create(**spec())["id"]
    store.start(job)
    assert entered.wait(2)
    with pytest.raises(ValueError, match="running"):
        store.delete(job)
    store.cancel(job)
    release.set()
    deadline = time.monotonic() + 4
    while job in store.futures and time.monotonic() < deadline:
        time.sleep(0.02)
    status = store.status(job)
    assert status["state"] == "paused" and status["completed_chunks"] == 1
    assert status["reserved"] == 0


def test_lease_lookup_closes_sqlite_before_yield_even_on_missing_job(store, monkeypatch):
    """Lease lifetime must not retain a catalog connection or rely on GC."""
    import sqlite3

    job = store.create(**spec())["id"]
    connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)  # Keep alive to rule out GC as cleanup.
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    for _ in range(20):
        with store.lease(job):
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connections[-1].execute("SELECT 1")
    with pytest.raises(ValueError, match="Unknown history job"):
        with store.lease("f" * 32):
            pytest.fail("Missing job must not acquire a lease")
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_interrupted_reservation_is_reclaimed_on_reopen(store):
    job = store.create(**spec())["id"]
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='running',reserved=2000000 WHERE id=?", (job,))
    other = HistoryStore(store.directory, fetcher=fake)
    try:
        assert other.status(job)["state"] == "paused" and other.settings()["reserved_bytes"] == 0
        assert other.run(job)["state"] == "complete"
    finally:
        other.close()


def test_invalid_market_and_range_rejected_before_any_job(store):
    for replacement in (
        {"codes": ["NOT-A-MARKET"]},
        {"interval": "2seconds"},
        {"codes": ["601398.SH"] * 10},
        {"end_date": "2040-01-01"},
    ):
        with pytest.raises(ValueError):
            store.create(**(spec() | replacement))
    assert store.status() == []


def test_history_api_uses_auth_and_validates_quota(store, monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from src.data_gateway.history_api import register_history_routes

    monkeypatch.setattr("src.data_gateway.history_api.get_history_store", lambda: store)
    app = FastAPI()
    register_history_routes(app, lambda: None)
    with TestClient(app) as client:
        assert client.post("/data/history/plan", json=spec()).json()["chunks"] == 6
        assert client.put("/data/history/storage", json={"quota_bytes": 1, "retention_days": 30}).status_code == 422
        assert client.post("/data/history/jobs", json=spec()).status_code == 200

    def deny():
        raise HTTPException(401)

    app = FastAPI()
    register_history_routes(app, deny)
    with TestClient(app) as client:
        assert client.post("/data/history/jobs", json=spec()).status_code == 401
        assert client.get("/data/history/storage").status_code == 401


def test_cross_instance_start_does_not_overwrite_running_job(store):
    entered, release = threading.Event(), threading.Event()

    def fetch(*args):
        entered.set()
        release.wait(3)
        return fake(*args)

    store.fetcher = fetch
    job = store.create(**spec())["id"]
    store.start(job)
    assert entered.wait(2)
    other = HistoryStore(store.directory, fetcher=fake)
    try:
        with pytest.raises(ValueError, match="running"):
            other.start(job)
        assert other.status(job)["state"] == "running"
    finally:
        release.set()
        other.close()


def test_gzip_writer_refuses_before_crossing_reservation(store):
    import secrets

    store.fetcher = lambda *args: ([{"value": secrets.token_hex(900)} for _ in range(3000)], {})
    job = store.create(**spec())["id"]
    result = store.run(job)
    assert result["state"] == "failed" and "reserved limit" in result["error"]
    assert result["completed_chunks"] == 0 and result["reserved"] == 0
    assert not list(store.directory.rglob("*.tmp"))


def test_tool_pages_complete_rows_and_omits_large_manifest(store, monkeypatch):
    from src.tools.history_data_tool import HistoryDataTool

    monkeypatch.setattr("src.data_gateway.history_store.get_history_store", lambda: store)
    tool = HistoryDataTool()
    job = json.loads(tool.execute(action="create", **spec()))["data"]
    assert "chunks" not in job and job["total_chunks"] == 6
    assert not json.loads(tool.execute(action="rows", job=job["id"]))["ok"]
    store.run(job["id"])
    assert len(json.loads(tool.execute(action="rows", job=job["id"]))["data"]["rows"]) == 6


def test_row_page_keeps_each_markets_units_and_does_not_guess_missing_currency(store):
    def fetch(symbol, start, end, interval):
        rows, meta = fake(symbol, start, end, interval)
        return rows, {
            **meta,
            "quote_currency": {"AAPL.US": "USD", "00700.HK": "HKD"}.get(symbol),
            "volume_unit": "shares",
            "adjustment": "raw",
            "timezone": "source_timezone_unverified",
        }

    store.fetcher = fetch
    job = store.create(
        codes=["AAPL.US", "00700.HK", "VOD.L"], start_date="2026-01-05", end_date="2026-01-05", interval="1D"
    )["id"]
    store.run(job)
    page = store.read(job, 1, 2)
    assert page["interval"] == "1D"
    assert set(page["provenance"]) == {"00700.HK", "VOD.L"}
    assert page["provenance"]["00700.HK"][0]["quote_currency"] == "HKD"
    assert page["provenance"]["VOD.L"][0]["quote_currency"] is None
    assert page["provenance"]["00700.HK"][0]["volume_unit"] == "shares"
    assert page["provenance"]["00700.HK"][0]["timezone"] == "source_timezone_unverified"
    assert store.read(job, 0, 1)["provenance"]["AAPL.US"][0]["quote_currency"] == "USD"


def test_row_page_keeps_chunk_provenance_when_one_symbol_changes_source(store):
    def fetch(symbol, start, end, interval):
        rows, meta = fake(symbol, start, end, interval)
        return rows, {**meta, "source": "first" if start.endswith("01-01") else "second", "quote_currency": "CNY"}

    store.fetcher = fetch
    job = store.create(codes=["601398.SH"], start_date="2021-01-01", end_date="2021-02-28")["id"]
    store.run(job)
    page = store.read(job, 0, 2)
    entries = page["provenance"]["601398.SH"]
    assert [entry["source"] for entry in entries] == ["first", "second"]
    assert [entry["start_date"] for entry in entries] == ["2021-01-01", "2021-02-01"]


def test_tool_wide_rows_page_whole_records_with_provenance_and_no_missing_tail(store, monkeypatch):
    from src.config.limits import TOOL_RESULT_LIMIT
    from src.tools.history_data_tool import HistoryDataTool

    def fetch(symbol, start, end, interval):
        from datetime import date, timedelta

        rows = [
            {
                "symbol": symbol,
                "time": str(date(2026, 1, 1) + timedelta(days=i)),
                **{f"numeric_field_{j}": 12345.6789 for j in range(40)},
            }
            for i in range(40)
        ]
        return rows, {"source": "fixture", "quote_currency": "USD", "coverage_verified": True}

    store.fetcher = fetch
    monkeypatch.setattr("src.data_gateway.history_store.get_history_store", lambda: store)
    job = store.create(codes=["AAPL.US"], start_date="2026-01-01", end_date="2026-02-09", interval="1D")["id"]
    store.run(job)
    offset, rows, pages = 0, [], 0
    while True:
        encoded = HistoryDataTool().execute(action="rows", job=job, offset=offset)
        assert len(encoded) <= TOOL_RESULT_LIMIT
        page = json.loads(encoded)["data"]
        assert page["rows"] and not page["sampled"]
        assert page["provenance"]["AAPL.US"][0]["quote_currency"] == "USD"
        rows.extend(page["rows"])
        pages += 1
        if page["next_offset"] is None:
            break
        assert page["next_offset"] == len(rows)
        offset = page["next_offset"]
    assert pages > 2 and rows == store.read(job, 0, 1000)["rows"]


def test_tool_refuses_a_single_oversized_row_instead_of_truncating_json():
    from src.config.limits import TOOL_RESULT_LIMIT
    from src.tools.history_data_tool import row_page

    with pytest.raises(ValueError, match="API or CLI"):
        row_page(
            {
                "offset": 0,
                "total_rows": 1,
                "rows": [{"symbol": "AAPL.US", "note": "x" * TOOL_RESULT_LIMIT}],
                "provenance": {},
            }
        )


def test_two_process_style_stores_share_disk_reservations(store):
    store.settings(quota_bytes=4 * 1024**2)
    first = store.create(**spec())["id"]
    second = store.create(**spec())["id"]
    entered, release = threading.Event(), threading.Event()

    def fetch(*args):
        entered.set()
        release.wait(3)
        return fake(*args)

    store.fetcher = fetch
    store.start(first)
    assert entered.wait(2)
    other = HistoryStore(store.directory, fetcher=lambda *a: pytest.fail("Quota must be reserved before fetch"))
    try:
        result = other.run(second)
        assert result["state"] == "paused" and "quota exhausted" in result["error"]
        assert store.status(first)["state"] == "running"
        assert other.settings()["reserved_bytes"] == store.chunk_limit + 65536
        assert other.settings()["used_bytes"] < 4 * 1024**2
    finally:
        release.set()
        other.close()


def test_low_disk_pauses_without_fetch_and_preserves_catalog(store, monkeypatch):
    from types import SimpleNamespace

    job = store.create(**spec())["id"]
    monkeypatch.setattr("src.data_gateway.history_store.shutil.disk_usage", lambda path: SimpleNamespace(free=100))
    store.fetcher = lambda *a: pytest.fail("Disk check must precede fetch")
    result = store.run(job)
    assert result["state"] == "paused" and "Insufficient free disk" in result["error"]
    assert result["reserved"] == 0 and result["total_chunks"] == 6


def test_foreign_metadata_lock_has_bounded_wait(store):
    from src.data_gateway.cache import Cache

    store.lock_timeout = 0.05
    with Cache.disk_lock(store):
        started = time.monotonic()
        assert store.settings()["quota_bytes"] == 256 * 1024**2
        with pytest.raises(ValueError, match="busy"):
            store.settings(retention_days=17)
        assert time.monotonic() - started < 0.5
    assert store.settings()["quota_bytes"] == 256 * 1024**2


def test_agent_job_listing_is_bounded_and_paged(store, monkeypatch):
    from src.tools.history_data_tool import HistoryDataTool

    monkeypatch.setattr("src.data_gateway.history_store.get_history_store", lambda: store)
    for _ in range(11):
        store.create(**spec())
    tool = HistoryDataTool()
    first = json.loads(tool.execute(action="status"))["data"]
    last = json.loads(tool.execute(action="status", offset=first["next_offset"]))["data"]
    assert len(first["jobs"]) == 10 and len(last["jobs"]) == 1 and last["next_offset"] is None
    assert len({job["id"] for job in first["jobs"] + last["jobs"]}) == 11


def test_application_cli_supports_global_flags_and_sequential_invocations(tmp_path, monkeypatch, capsys):
    from cli._legacy import main
    import src.data_gateway.history_store as module

    monkeypatch.setattr(module, "history_directory", lambda: tmp_path)
    monkeypatch.setattr(module, "HistoryStore", lambda directory: HistoryStore(directory, fetcher=fake))
    assert (
        main(
            [
                "--no-rich",
                "data",
                "history",
                "create",
                "--codes",
                "601398.SH",
                "--start",
                "2021-01-01",
                "--end",
                "2021-02-28",
            ]
        )
        == 0
    )
    job = json.loads(capsys.readouterr().out)["id"]
    assert main(["data", "history", "run", "--job", job]) == 0
    assert json.loads(capsys.readouterr().out)["completed_chunks"] == 2
    assert (
        main(["data", "history", "plan", "--codes", "NOT-A-MARKET", "--start", "2021-01-01", "--end", "2021-02-28"])
        == 1
    )


def test_repair_paused_by_quota_does_not_claim_deleted_chunk_is_complete(store):
    job = store.create(**spec())["id"]
    assert store.run(job)["completed_chunks"] == 6
    store.settings(quota_bytes=4 * 1024**2)
    store._path(job, 0).write_bytes(b"corrupt")
    (store.directory / "quota-test.bin").write_bytes(b"x" * (3 * 1024**2))
    state = store.run(job)
    assert state["state"] == "paused"
    assert state["completed_chunks"] == 5 and state["chunks"][0]["state"] == "pending"
    assert state["reserved"] == 0


def test_default_dataset_path_never_collides_with_cli_history(tmp_path, monkeypatch):
    from pathlib import Path
    from src.data_gateway.history_store import history_directory

    monkeypatch.delenv("VIBE_GATEWAY_HISTORY_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / ".vibe-trading"
    root.mkdir()
    history = root / "history"
    history.write_text("user command history")
    assert history_directory() == root / "datasets" / "history"
    assert history.read_text() == "user command history"


def test_legacy_dataset_directory_remains_readable(tmp_path, monkeypatch):
    from pathlib import Path
    from src.data_gateway.history_store import history_directory

    monkeypatch.delenv("VIBE_GATEWAY_HISTORY_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".vibe-trading" / "history"
    legacy.mkdir(parents=True)
    (legacy / "catalog.sqlite").touch()
    assert history_directory() == legacy
    monkeypatch.setenv("VIBE_GATEWAY_HISTORY_DIR", str(tmp_path / "custom"))
    assert history_directory() == tmp_path / "custom"


def test_distinct_jobs_with_colliding_old_hashes_have_independent_leases(store, monkeypatch):
    from types import SimpleNamespace
    import src.data_gateway.history_store as module

    ids = iter(["00000000" + "a" * 24, "00000040" + "b" * 24])
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=next(ids)))
    first = store.create(**spec())["id"]
    second = store.create(**spec())["id"]
    with store.lease(first), store.lease(second):
        with pytest.raises(ValueError, match="already running"):
            with store.lease(first):
                pass
    with store.transaction() as db:
        assert len({r[0] for r in db.execute("SELECT lease_slot FROM jobs")}) == 2


def test_cancel_between_status_snapshot_and_running_transition_is_not_lost(store, monkeypatch):
    job = store.create(**spec())["id"]
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='queued',cancel=0 WHERE id=?", (job,))
    original, reads, fetched = store.status, [0], []

    def status(identity=None):
        value = original(identity)
        reads[0] += 1
        if reads[0] == 2:
            store.cancel(job)
        return value

    monkeypatch.setattr(store, "status", status)
    store.fetcher = lambda *args: (fetched.append(args), {})
    value = store.run(job)
    assert value["state"] == "paused" and value["cancel"] and not fetched


def test_status_and_storage_read_committed_snapshot_while_writer_holds_lock(store):
    job = store.create(**spec())["id"]
    locked, release = threading.Event(), threading.Event()

    def writer():
        with store.transaction() as db:
            db.execute("UPDATE jobs SET state='queued' WHERE id=?", (job,))
            db.execute("UPDATE settings SET retention=17")
            locked.set()
            assert release.wait(5)

    thread = threading.Thread(target=writer)
    thread.start()
    assert locked.wait(2)
    try:
        before = time.monotonic()
        assert store.status(job)["state"] == "paused"
        assert store.status()[0]["state"] == "paused"
        assert store.settings()["retention_days"] == 30
        assert time.monotonic() - before < store.lock_timeout
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert store.status(job)["state"] == "queued"
    assert store.settings()["retention_days"] == 17


def test_concurrent_page_reader_waits_within_existing_lock_budget(store):
    job = store.create(**spec())["id"]
    store.run(job)
    result = []
    started = threading.Event()

    def reader():
        started.set()
        result.append(store.read(job, 0, 2))

    with store.lease(job):
        thread = threading.Thread(target=reader)
        thread.start()
        assert started.wait(1)
        time.sleep(0.05)
        assert not result
    thread.join(2)
    assert not thread.is_alive() and len(result[0]["rows"]) == 2


def _hold_history_from_spawned_process(directory, job, entered, release, result):
    """Hold a real cross-process file lease while a source is in flight."""

    def fetch(*args):
        entered.set()
        if not release.wait(15):
            raise RuntimeError("Cross-process test source was never released")
        return fake(*args)

    child = HistoryStore(directory, fetcher=fetch)
    try:
        result.put(child.run(job))
    finally:
        child.close()


def test_spawned_writer_preserves_ownership_and_observes_foreign_cancel(store):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    entered, release, result = context.Event(), context.Event(), context.Queue()
    job = store.create(**spec())["id"]
    process = context.Process(
        target=_hold_history_from_spawned_process,
        args=(store.directory, job, entered, release, result),
    )
    process.start()
    other = None
    try:
        assert entered.wait(10)
        other = HistoryStore(store.directory, fetcher=fake)
        state = other.status(job)
        assert state["state"] == "running" and state["reserved"] > 0
        # Construction must not recover an actively owned job as interrupted.
        with pytest.raises(ValueError, match="running"):
            other.start(job)
        with pytest.raises(ValueError, match="running"):
            other.delete(job)
        assert other.status(job)["reserved"] == state["reserved"]
        other.cancel(job)
        release.set()
        terminal = result.get(timeout=10)
        process.join(10)
        assert process.exitcode == 0
        assert terminal["state"] == "paused" and terminal["reserved"] == 0
        assert terminal["completed_chunks"] == 1
        assert other.run(job)["state"] == "complete"
        assert len(other.read(job, 0, 10)["rows"]) == 6
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        if other:
            other.close()
        result.close()
        result.join_thread()
