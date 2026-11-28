"""The shipping service and worker tools share one SQLite search connection."""

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.session.events import EventBus
from src.session.search import SessionSearchIndex
from src.session.service import SessionService
from src.session.store import SessionStore
from src.tools.session_search_tool import SessionSearchTool


def test_service_admission_can_overlap_worker_session_search(
    tmp_path: Path, monkeypatch
):
    index = SessionSearchIndex(tmp_path / "search.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    monkeypatch.setattr("src.session.search.get_shared_index", lambda: index)
    service = SessionService(
        policy=ToolPolicy.from_config(get_env_config()),
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )
    session = service.create_session(title="Synthetic worker search")

    async def scenario():
        await service.send_message(session.session_id, "volatility", role="assistant")

        def search():
            return json.loads(SessionSearchTool().execute(query="volatility"))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(search) for _ in range(400)]
            for i in range(100):
                await service.send_message(
                    session.session_id, f"volatility {i}", role="assistant"
                )
            replies = [f.result() for f in futures]
        assert all(reply["status"] == "ok" for reply in replies), [
            reply for reply in replies if reply["status"] != "ok"
        ]
        assert all(
            reply["results"][0]["session_id"] == session.session_id for reply in replies
        )
        assert (
            index._get_conn().execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            == 101
        )
        assert len(service.store.get_messages(session.session_id, limit=200)) == 101

    try:
        asyncio.run(scenario())
    finally:
        index.close()


def test_writer_waits_for_native_search_cursor(tmp_path: Path):
    from threading import Event

    index = SessionSearchIndex(tmp_path / "cursor.db")
    index.index_session("session", "Owned test")
    index.index_message("session", "user", "volatility")
    real = index._get_conn()
    entered, release, writer_entered = Event(), Event(), Event()

    class Cursor:
        def fetchone(self):
            return self.cursor.fetchone()

        def fetchall(self):
            entered.set()
            assert release.wait(3)
            return self.cursor.fetchall()

        def __iter__(self):
            entered.set()
            assert release.wait(3)
            yield from self.cursor

    class Connection:
        def execute(self, sql, *args):
            if "INSERT INTO messages" in sql:
                writer_entered.set()
            cursor = real.execute(sql, *args)
            if "FROM messages_fts" in sql:
                wrapped = Cursor()
                wrapped.cursor = cursor
                return wrapped
            return cursor

        def commit(self):
            return real.commit()

    index._conn = Connection()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(index.search, "volatility")
            assert entered.wait(3)
            writer = pool.submit(
                index.index_message, "session", "user", "volatility new"
            )
            try:
                assert not writer_entered.wait(0.1)
            finally:
                release.set()
            assert reader.result(timeout=3)[0].session_id == "session"
            writer.result(timeout=3)
            assert writer_entered.is_set()
        assert real.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    finally:
        release.set()
        index._conn = real
        index.close()


def test_close_waits_for_native_search_cursor(tmp_path: Path):
    from threading import Event

    index = SessionSearchIndex(tmp_path / "close.db")
    index.index_session("session", "Owned test")
    index.index_message("session", "user", "volatility")
    real = index._get_conn()
    entered, release, closed = Event(), Event(), Event()

    class Cursor:
        def fetchone(self):
            return self.cursor.fetchone()

        def fetchall(self):
            entered.set()
            assert release.wait(3)
            return self.cursor.fetchall()

        def __iter__(self):
            entered.set()
            assert release.wait(3)
            yield from self.cursor

    class Connection:
        def execute(self, sql, *args):
            wrapped = Cursor()
            wrapped.cursor = real.execute(sql, *args)
            return wrapped

        def close(self):
            real.close()
            closed.set()

    index._conn = Connection()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(index.search, "volatility")
            assert entered.wait(3)
            closer = pool.submit(index.close)
            try:
                assert not closed.wait(0.1)
            finally:
                release.set()
            assert reader.result(timeout=3)[0].session_id == "session"
            closer.result(timeout=3)
        assert closed.is_set()
        assert index._conn is None
    finally:
        release.set()
        if not closed.is_set():
            real.close()
