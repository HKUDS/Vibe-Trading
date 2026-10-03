"""Upgrade, filesystem, price-basis and report-delivery acceptance cases."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.session.search import SessionSearchIndex
from src.tools.path_utils import resolve_safe_path
from src.tools.swarm_tool import _build_variables, _match_preset, _merge_variables
from src.tools.write_file_tool import WriteFileTool


@pytest.mark.parametrize("text,query", [
    ("我想了解比特币价格价格及交易策略", "价格"),
    ("ビットコインの投資について調べます", "投資"),
    ("ビットコインについて調べます", "ビットコイン"),
    ("비트코인의 투자 전략을 분석합니다", "투자"),
    ("ação e análise de ações", "análise"),
])
def test_existing_session_database_upgrade_preserves_original_snippets(tmp_path, text, query):
    path = tmp_path / "sessions.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT,started_at REAL,message_count INTEGER);
            CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,role TEXT,
                                  content TEXT,tool_name TEXT,timestamp REAL);
            CREATE VIRTUAL TABLE messages_fts USING fts5(content,content=messages,content_rowid=id);
        """)
        connection.execute("INSERT INTO sessions VALUES ('old','History',1700000000,1)")
        connection.execute("INSERT INTO messages VALUES (1,'old','user',?,NULL,1700000000)", (text,))
        connection.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    for _ in range(2):
        index = SessionSearchIndex(path)
        matches = index.search(query)
        assert [match.session_id for match in matches] == ["old"]
        assert matches[0].snippet.replace(">>>", "").replace("<<<", "") == text
        assert index._get_conn().execute("SELECT content FROM messages").fetchone()[0] == text
        assert matches[0].message_count == 1
        index.close()


def test_cjk_query_does_not_match_unrelated_shared_character(tmp_path):
    index = SessionSearchIndex(tmp_path / "search.db")
    index.index_session("wrong", "Unrelated")
    index.index_message("wrong", "user", "比大小和特长")
    assert index.search("比特币") == []
    index.close()


def test_case_alias_and_symlink_paths_use_real_directory_identity(tmp_path):
    root = tmp_path / "Dropbox"
    root.mkdir()
    lower = tmp_path / "dropbox"
    if lower.exists() and lower.samefile(root):
        output = resolve_safe_path(str(lower / "report.txt"), None, [root], purpose="write")
        assert output == root.resolve() / "report.txt"
    else:
        lower.mkdir()
        with pytest.raises(ValueError):
            resolve_safe_path(str(lower / "report.txt"), None, [root], purpose="write")
    alias = tmp_path / "cloud-alias"
    alias.symlink_to(root, target_is_directory=True)
    assert resolve_safe_path(str(alias / "report.txt"), None, [root]) == root.resolve() / "report.txt"
    outside = tmp_path / "private"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        resolve_safe_path(str(root / "escape" / "secret.txt"), None, [root])


@pytest.mark.parametrize("prompt,preset,asset,key,duration", [
    ("Analyze XRP for the next 7 days", "crypto_research_lab", "XRP", "timeframe", "7 days"),
    ("分析铜，未来两周", "commodity_research_team", "copper", "horizon", "2 weeks"),
    ("分析铁矿石未来七天", "commodity_research_team", "iron ore", "horizon", "7 days"),
    ("Analyze copper for the next six months", "commodity_research_team", "copper", "horizon", "6 months"),
])
def test_swarm_actual_worker_templates_retain_explicit_assets_and_duration(prompt, preset, asset, key, duration):
    from src.swarm.presets import load_preset
    assert _match_preset(prompt) == preset
    variables = _build_variables(preset, prompt)
    assert variables[key] == duration
    for task in load_preset(preset)["tasks"]:
        rendered = task["prompt_template"].format_map(variables)
        assert asset in rendered and duration in rendered


def test_swarm_unknown_asset_is_not_replaced_by_default_crypto_basket():
    variables = _build_variables("crypto_research_lab", "Analyze SUI crypto for seven days")
    assert "SUI" in variables["target"]
    assert variables["timeframe"] == "7 days"
    assert _merge_variables(variables, {"target": ["SUI"]})[1] is not None


@pytest.mark.parametrize("parser", ["fmp", "tiingo"])
def test_adjustment_gap_never_fabricates_a_doubling_return(parser, caplog):
    from backtest.loaders.fmp_loader import _parse_historical
    from backtest.loaders.tiingo_loader import _rows_to_frame
    parse = (lambda rows: _parse_historical({"historical": rows})) if parser == "fmp" else _rows_to_frame
    rows = [{"date": date, "open": 100, "high": 110, "low": 90, "close": 100, "volume": 10,
             **adjustment} for date, adjustment in [
        ("2024-01-02", {"adjClose": 50}), ("2024-01-03", {}), ("2024-01-04", {"adjClose": 50})]]
    frame = parse(rows)
    assert list(frame.close) == [50, 50]
    assert frame.close.pct_change().dropna().tolist() == [0]
    assert "dropped 1" in caplog.text
    assert frame.attrs["adjustment"] == "split_dividend"
    raw = parse([{**rows[1]}, {**rows[0], "date": "invalid"}])
    assert list(raw.close) == [100]
    assert raw.attrs["adjustment"] == "raw"
    assert parse([{**rows[1], "close": float("inf")}]) is None


@pytest.mark.parametrize("field", ["current_price", "ltp", "market_val"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, "invalid"])
def test_sdk_aliases_still_refuse_nonfinite_or_malformed_positions(field, invalid):
    from src.live.enforcement import _post_trade_gross_exposure
    row = {"symbol": "AAPL", "quantity": 2, field: invalid}
    assert _post_trade_gross_exposure([row], symbol="AAPL", signed_order_notional=50) is None


def test_pdf_write_authenticated_download_and_im_delivery_share_real_file(tmp_path, monkeypatch):
    from src.api.uploads_routes import register_uploads_routes
    from src.channels.runtime import ChannelRuntime
    from src.session.models import Message
    from src.tools import report_artifacts
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(tmp_path))
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))
    from src.config.accessor import reset_env_config
    reset_env_config()
    payload = json.loads(WriteFileTool().execute(path=str(tmp_path / "研究报告.pdf"), content=(
        "# 研究报告\n\n投资策略 < & >\n\n| 指标 | 观察 |\n| --- | --- |\n| 样本 | 完整 |\n")))
    assert payload["status"] == "ok"
    path = report_artifacts.report_path(payload["report_id"])
    assert path.read_bytes() == (tmp_path / "研究报告.pdf").read_bytes()
    assert path.read_bytes().startswith(b"%PDF-") and path.read_bytes().rstrip().endswith(b"%%EOF")
    assert payload["bytes_written"] == path.stat().st_size
    def auth(request: Request):
        if request.headers.get("authorization") != "Bearer test-token":
            raise HTTPException(401)
    app = FastAPI()
    register_uploads_routes(app, auth)
    client = TestClient(app)
    assert client.get(payload["download_url"]).status_code == 401
    response = client.get(payload["download_url"], headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content == path.read_bytes()
    message = Message(metadata={"generated_reports": [payload, payload, {"report_id": "../secret"}]})
    assert ChannelRuntime._report_media(message) == [str(path)]
    path.unlink()
    path.symlink_to(tmp_path / "研究报告.pdf")
    assert client.get(payload["download_url"], headers={"Authorization": "Bearer test-token"}).status_code == 404


def test_pdf_render_failure_preserves_existing_file_and_reports_error(tmp_path, monkeypatch):
    from src.tools import pdf_report
    monkeypatch.setattr("src.tools.write_file_tool.allowed_write_roots", lambda: [tmp_path])
    target = tmp_path / "report.pdf"
    target.write_bytes(b"previous version")
    def fail(*args):
        raise RuntimeError("render failed")
    monkeypatch.setattr(pdf_report, "render_markdown_pdf", fail)
    result = json.loads(WriteFileTool().execute(path=str(target), content="# A report"))
    assert result["status"] == "error"
    assert target.read_bytes() == b"previous version"


def test_cache_upgrade_invalidates_old_basis_and_preserves_adjustment_stamp():
    from backtest.loaders import base
    import pandas as pd
    assert base._LOADER_CACHE_VERSION >= 8
    frame = pd.DataFrame({"close": [100.]}, index=pd.to_datetime(["2024-01-02"]))
    frame.attrs["adjustment"] = "raw"
    _, metadata = base._frame_for_loader_cache(frame)
    assert metadata["frame_attrs"]["adjustment"] == "raw"
