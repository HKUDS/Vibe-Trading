"""Search context must follow real SQLite token matches in original text."""

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import asyncio
import json

import pytest

from src.session.events import EventBus
from src.session.search import SessionSearchIndex
from src.session.service import SessionService
from src.session.store import SessionStore
from src.tools.session_search_tool import SessionSearchTool


@pytest.mark.parametrize(
    "query,content,expected",
    [
        (
            "alpha",
            "alphabet filler " * 40 + "alpha genuine context",
            ">>>alpha<<< genuine context",
        ),
        (
            "cafe",
            "padding " * 90 + "café genuine context",
            ">>>café<<< genuine context",
        ),
        (
            "alpha",
            "alphabet filler " * 40 + "alpha_beta genuine context",
            ">>>alpha<<<_beta genuine context",
        ),
        (
            "北京",
            "padding " * 90 + "北 京 genuine context",
            ">>>北 京<<< genuine context",
        ),
        (
            "alpha",
            "alphabet filler " * 2500 + "alpha long-message context",
            ">>>alpha<<< long-message context",
        ),
        (
            "東京",
            "padding " * 90 + "東京都 original context",
            ">>>東京<<<都 original context",
        ),
        (
            "서울",
            "padding " * 90 + "서울 original context",
            ">>>서울<<< original context",
        ),
        (
            "alpha",
            "original <\x01> controls alpha genuine <\x02> tail",
            "original <\x01> controls >>>alpha<<< genuine <\x02> tail",
        ),
    ],
    ids=[
        "word-landmark",
        "diacritics",
        "underscore",
        "CJK-whitespace",
        "long-Latin",
        "Japanese",
        "Korean",
        "literal-markers",
    ],
)
def test_shipping_search_context_follows_native_tokens(
    tmp_path, monkeypatch, query, content, expected
):
    index = SessionSearchIndex(tmp_path / "owned.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    monkeypatch.setattr("src.session.search.get_shared_index", lambda: index)
    service = SessionService(
        policy=ToolPolicy.from_config(get_env_config()),
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )
    session = service.create_session(title="Synthetic original context")
    asyncio.run(service.send_message(session.session_id, content, role="assistant"))
    # Native FTS MATCH is the independent admission oracle. It must match this
    # source message before any expectation about its displayed snippet runs.
    native = (
        index._get_conn()
        .execute(
            "SELECT highlight(messages_fts,0,'[MATCH]','[/MATCH]') "
            "FROM messages_fts WHERE messages_fts MATCH ?",
            (index._sanitize_fts_query(query),),
        )
        .fetchone()
    )
    assert native is not None and "[MATCH]" in native[0]
    try:
        result = json.loads(SessionSearchTool().execute(query=query))
        assert result["status"] == "ok", result
        assert len(result["results"]) == 1
        match = result["results"][0]
        assert match["session_id"] == session.session_id
        assert expected in match["snippet"]
        assert ">>>alpha<<<bet" not in match["snippet"]
        readable = match["snippet"].replace(">>>", "").replace("<<<", "").strip(".")
        assert len(readable) <= 400
        assert readable in content
        assert match["message_count"] == 1
        assert service.store.get_messages(session.session_id)[0].content == content
    finally:
        index.close()
