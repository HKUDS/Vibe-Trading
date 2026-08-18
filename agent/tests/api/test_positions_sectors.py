"""Tests for GET /runs/{run_id}/positions/sectors and resolve_industry_board.

All Eastmoney HTTP is mocked at the import sites in ``src.tools.sector_tool``
(:func:`get_json` / :func:`resolve_secid`), so no test touches a live endpoint.
Run directories are fabricated under ``tmp_path`` mirroring the layout the
run-detail handler expects (``RUNS_DIR/<run_id>/artifacts/positions.csv``).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_server
from src.api import runs_routes
from src.tools.sector_tool import resolve_industry_board

RUN_ID = "run_20260801_120000"

# Verified spt=1 shape: diff keyed by string index, row "0" the stock itself
# (f13 = 1/0), row "1" the industry board (f13 = 90).
_SLIST_600519 = {
    "data": {
        "diff": {
            "0": {"f12": "600519", "f13": 1, "f14": "贵州茅台"},
            "1": {"f12": "BK1277", "f13": 90, "f14": "白酒Ⅱ"},
        }
    }
}

# A-share payload with no board row -> industry stays unresolved.
_SLIST_159913_NO_BOARD = {
    "data": {"diff": {"0": {"f12": "159913", "f13": 0, "f14": "创业板ETF"}}}
}

_SECIDS = {"600519.SH": "1.600519", "159913.SZ": "0.159913"}


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _make_run(tmp_path: Path, header: str, rows: list[str] | None = None) -> Path:
    run_dir = tmp_path / "runs" / RUN_ID
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    lines = [header, *(rows or [])]
    (artifacts / "positions.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def _fake_resolve_secid(symbol: str) -> str | None:
    return _SECIDS.get(symbol)


def _fake_get_json(url: str, *, params: dict) -> dict:
    secid = params["secid"]
    if secid == "1.600519":
        return _SLIST_600519
    if secid == "0.159913":
        return _SLIST_159913_NO_BOARD
    raise AssertionError(f"unexpected secid: {secid}")


# ============================================================================
# Endpoint: happy path
# ============================================================================


def test_positions_sectors_happy_path(tmp_path: Path, monkeypatch) -> None:
    _make_run(
        tmp_path,
        "timestamp,600519.SH,AAPL.US,159913.SZ",
        ["2026-08-01T00:00:00,0.5,0.3,0.2"],
    )
    client = _client(tmp_path, monkeypatch)

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=_fake_resolve_secid
    ) as resolve, patch("src.tools.sector_tool.get_json", side_effect=_fake_get_json) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["run_id"] == RUN_ID
    assert payload["cached"] is False
    assert payload["resolved_at"].endswith("Z")
    assert payload["symbols"]["600519.SH"] == {
        "asset_class": "a_share",
        "industry": "白酒Ⅱ",
        "industry_source": "eastmoney",
    }
    assert payload["symbols"]["AAPL.US"] == {
        "asset_class": "us_equity",
        "industry": None,
        "industry_source": None,
    }
    assert payload["symbols"]["159913.SZ"]["industry"] is None
    assert payload["symbols"]["159913.SZ"]["industry_source"] is None
    assert payload["unresolved"] == ["159913.SZ"]
    assert payload["total_symbols"] == 3
    assert payload["symbol_limit"] == 200

    # One spt=1 industry request per A-share symbol; US symbols never resolve.
    assert get.call_count == 2
    for call in get.call_args_list:
        assert call.kwargs["params"]["spt"] == "1"
        assert "slist/get" in call.args[0]
    assert resolve.call_count == 2

    cache_path = tmp_path / "runs" / RUN_ID / "artifacts" / "sector_map.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["symbols"]["600519.SH"]["industry"] == "白酒Ⅱ"


def test_non_a_share_symbols_never_call_eastmoney(tmp_path: Path, monkeypatch) -> None:
    _make_run(
        tmp_path,
        "timestamp,AAPL.US,00700.HK,BTC-USDT",
        ["2026-08-01T00:00:00,0.4,0.3,0.3"],
    )
    client = _client(tmp_path, monkeypatch)

    with patch("src.tools.sector_tool.resolve_secid") as resolve, patch(
        "src.tools.sector_tool.get_json"
    ) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbols"]["AAPL.US"]["asset_class"] == "us_equity"
    assert payload["symbols"]["00700.HK"] == {
        "asset_class": "hk_equity",
        "industry": None,
        "industry_source": None,
    }
    assert payload["symbols"]["BTC-USDT"]["asset_class"] == "crypto"
    assert payload["unresolved"] == []
    resolve.assert_not_called()
    get.assert_not_called()


# ============================================================================
# Endpoint: cache behaviour
# ============================================================================


def test_positions_sectors_cache_hit_makes_zero_network_calls(tmp_path: Path, monkeypatch) -> None:
    _make_run(tmp_path, "timestamp,600519.SH", ["2026-08-01T00:00:00,1.0"])
    client = _client(tmp_path, monkeypatch)

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=_fake_resolve_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=_fake_get_json):
        first = client.get(f"/runs/{RUN_ID}/positions/sectors")
    assert first.status_code == 200
    assert first.json()["cached"] is False

    with patch("src.tools.sector_tool.resolve_secid") as resolve, patch(
        "src.tools.sector_tool.get_json"
    ) as get:
        second = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert second.status_code == 200
    payload = second.json()
    assert payload["cached"] is True
    assert payload["resolved_at"] == first.json()["resolved_at"]
    assert payload["symbols"]["600519.SH"]["industry"] == "白酒Ⅱ"
    resolve.assert_not_called()
    get.assert_not_called()


def test_positions_sectors_refresh_bypasses_cache(tmp_path: Path, monkeypatch) -> None:
    _make_run(tmp_path, "timestamp,600519.SH", ["2026-08-01T00:00:00,1.0"])
    client = _client(tmp_path, monkeypatch)

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=_fake_resolve_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=_fake_get_json) as get:
        first = client.get(f"/runs/{RUN_ID}/positions/sectors")
        second = client.get(f"/runs/{RUN_ID}/positions/sectors?refresh=1")

    assert first.json()["cached"] is False
    assert second.json()["cached"] is False
    assert second.json()["symbols"]["600519.SH"]["industry"] == "白酒Ⅱ"
    assert get.call_count == 2


def test_positions_sectors_corrupt_cache_recomputes(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "timestamp,600519.SH", ["2026-08-01T00:00:00,1.0"])
    (run_dir / "artifacts" / "sector_map.json").write_text("{not json", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=_fake_resolve_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=_fake_get_json) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cached"] is False
    assert payload["symbols"]["600519.SH"]["industry"] == "白酒Ⅱ"
    assert get.call_count == 1


# ============================================================================
# Endpoint: degenerate runs
# ============================================================================


def test_missing_positions_csv_returns_note(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }


def test_empty_positions_csv_returns_note(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / RUN_ID
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "positions.csv").write_text("", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbols"] == {}
    assert payload["note"] == "no positions artifact"


def test_unknown_run_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/runs/no-such-run/positions/sectors")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run no-such-run not found"


def test_symlinked_artifacts_dir_returns_no_positions_note(tmp_path: Path, monkeypatch) -> None:
    """A symlinked artifacts dir is rejected, mirroring the factor scan."""
    real_artifacts = tmp_path / "real_artifacts"
    real_artifacts.mkdir()
    (real_artifacts / "positions.csv").write_text(
        "timestamp,600519.SH\n2026-08-01T00:00:00,1.0\n", encoding="utf-8"
    )
    run_dir = tmp_path / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "artifacts").symlink_to(real_artifacts)
    client = _client(tmp_path, monkeypatch)

    with patch("src.tools.sector_tool.resolve_secid") as resolve, patch(
        "src.tools.sector_tool.get_json"
    ) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }
    resolve.assert_not_called()
    get.assert_not_called()


def test_symlinked_cache_file_rejected_without_write_through(tmp_path: Path, monkeypatch) -> None:
    """A symlinked ``sector_map.json`` is rejected like a symlinked artifacts dir.

    The artifacts directory itself is real here; only the cache file is a
    symlink. Neither the cache read nor the cache rewrite may follow it, or a
    planted symlink becomes a write primitive outside the run directory.
    """
    run_dir = _make_run(tmp_path, "timestamp,600519.SH", ["2026-08-01T00:00:00,1.0"])
    target = tmp_path / "elsewhere.json"
    target.write_text("sentinel", encoding="utf-8")
    (run_dir / "artifacts" / "sector_map.json").symlink_to(target)
    client = _client(tmp_path, monkeypatch)

    with patch("src.tools.sector_tool.resolve_secid") as resolve, patch(
        "src.tools.sector_tool.get_json"
    ) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }
    resolve.assert_not_called()
    get.assert_not_called()
    assert target.read_text(encoding="utf-8") == "sentinel"


def test_symlinked_positions_csv_rejected_without_read(tmp_path: Path, monkeypatch) -> None:
    """A symlinked ``positions.csv`` is rejected like a symlinked artifacts dir.

    The artifacts directory itself is real here; only positions.csv is a
    symlink. Following it would disclose the target file's header line in the
    response, so the endpoint must treat it as having no positions artifact.
    """
    run_dir = tmp_path / "runs" / RUN_ID
    (run_dir / "artifacts").mkdir(parents=True)
    target = tmp_path / "secret.csv"
    target.write_text("timestamp,LEAKED.SECRET\n2026-08-01T00:00:00,1.0\n", encoding="utf-8")
    (run_dir / "artifacts" / "positions.csv").symlink_to(target)
    client = _client(tmp_path, monkeypatch)

    with patch("src.tools.sector_tool.resolve_secid") as resolve, patch(
        "src.tools.sector_tool.get_json"
    ) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }
    resolve.assert_not_called()
    get.assert_not_called()
    assert target.read_text(encoding="utf-8").startswith("timestamp,LEAKED.SECRET")


# ============================================================================
# Endpoint: bounded contract for large books
# ============================================================================


def test_large_symbol_list_caps_network_lookups(tmp_path: Path, monkeypatch) -> None:
    total = 250
    symbols = [f"6{i:05d}.SH" for i in range(total)]
    _make_run(
        tmp_path,
        "timestamp," + ",".join(symbols),
        ["2026-08-01T00:00:00," + ",".join(["0.004"] * total)],
    )
    client = _client(tmp_path, monkeypatch)

    def any_secid(symbol: str) -> str | None:
        return f"1.{symbol.split('.')[0]}"

    def any_get_json(url: str, *, params: dict) -> dict:
        code = params["secid"].split(".")[1]
        return {
            "data": {
                "diff": {
                    "0": {"f12": code, "f13": 1, "f14": "S"},
                    "1": {"f12": "BK0001", "f13": 90, "f14": "银行Ⅱ"},
                }
            }
        }

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=any_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=any_get_json) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_symbols"] == total
    assert payload["symbol_limit"] == 200
    # Bounded: the capped tail never reaches the network.
    assert get.call_count == 200
    # Asset-class grouping still covers every symbol.
    assert len(payload["symbols"]) == total
    assert payload["symbols"][symbols[0]]["industry"] == "银行Ⅱ"
    assert payload["symbols"][symbols[-1]]["industry"] is None
    # The capped tail degrades to unresolved instead of aborting.
    assert len(payload["unresolved"]) == total - 200
    assert payload["unresolved"] == symbols[200:]


def _us_symbols(count: int) -> list[str]:
    return [f"{chr(65 + i // 26)}{chr(65 + i % 26)}.US" for i in range(count)]


def _any_secid(symbol: str) -> str | None:
    return f"1.{symbol.split('.')[0]}"


def _any_get_json(url: str, *, params: dict) -> dict:
    code = params["secid"].split(".")[1]
    return {
        "data": {
            "diff": {
                "0": {"f12": code, "f13": 1, "f14": "S"},
                "1": {"f12": "BK0001", "f13": 90, "f14": "银行Ⅱ"},
            }
        }
    }


def test_mixed_book_resolves_a_shares_after_non_a_share_prefix(tmp_path: Path, monkeypatch) -> None:
    """The lookup budget counts A-share lookups, not list position.

    Regression: gating on the symbol's index in the full list pushed every
    A-share past the cap once 200+ non-A-share names came first, leaving the
    whole book unresolved while the 200-lookup budget sat unused.
    """
    us = _us_symbols(205)
    a_shares = [f"6{i:05d}.SH" for i in range(5)]
    symbols = us + a_shares
    _make_run(
        tmp_path,
        "timestamp," + ",".join(symbols),
        ["2026-08-01T00:00:00," + ",".join(["0.001"] * len(symbols))],
    )
    client = _client(tmp_path, monkeypatch)

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=_any_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=_any_get_json) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_symbols"] == len(symbols)
    # Every A-share resolves despite sitting at list indices 205-209.
    assert get.call_count == len(a_shares)
    for symbol in a_shares:
        assert payload["symbols"][symbol]["industry"] == "银行Ⅱ"
    assert payload["unresolved"] == []
    for symbol in us:
        assert payload["symbols"][symbol]["asset_class"] == "us_equity"
        assert payload["symbols"][symbol]["industry"] is None


def test_mixed_book_cap_still_bounds_a_share_lookups(tmp_path: Path, monkeypatch) -> None:
    us = _us_symbols(205)
    a_shares = [f"6{i:05d}.SH" for i in range(250)]
    symbols = us + a_shares
    _make_run(
        tmp_path,
        "timestamp," + ",".join(symbols),
        ["2026-08-01T00:00:00," + ",".join(["0.001"] * len(symbols))],
    )
    client = _client(tmp_path, monkeypatch)

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=_any_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=_any_get_json) as get:
        response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_symbols"] == len(symbols)
    assert payload["symbol_limit"] == 200
    assert get.call_count == 200
    assert payload["symbols"][a_shares[0]]["industry"] == "银行Ⅱ"
    assert payload["symbols"][a_shares[-1]]["industry"] is None
    assert payload["unresolved"] == a_shares[200:]


def test_shared_executor_created_once_and_bounded(tmp_path: Path, monkeypatch) -> None:
    """One process-lifetime executor serves every request; the 200 cap holds.

    Regression for the per-request ``ThreadPoolExecutor`` replacement: the
    shared pool must be created lazily exactly once, carry
    ``_POSITIONS_SECTOR_WORKERS`` workers, stay un-shutdown across requests,
    and still cap network lookups at ``_POSITIONS_SECTOR_MAX_SYMBOLS``.
    """
    total = 250
    symbols = [f"6{i:05d}.SH" for i in range(total)]
    _make_run(
        tmp_path,
        "timestamp," + ",".join(symbols),
        ["2026-08-01T00:00:00," + ",".join(["0.004"] * total)],
    )
    client = _client(tmp_path, monkeypatch)

    monkeypatch.setattr(runs_routes, "_POSITIONS_SECTOR_EXECUTOR", None)
    created: list[dict] = []
    real_executor = runs_routes.ThreadPoolExecutor

    def counting_executor(*args, **kwargs):
        created.append(kwargs)
        return real_executor(*args, **kwargs)

    monkeypatch.setattr(runs_routes, "ThreadPoolExecutor", counting_executor)

    def any_secid(symbol: str) -> str | None:
        return f"1.{symbol.split('.')[0]}"

    def any_get_json(url: str, *, params: dict) -> dict:
        code = params["secid"].split(".")[1]
        return {
            "data": {
                "diff": {
                    "0": {"f12": code, "f13": 1, "f14": "S"},
                    "1": {"f12": "BK0001", "f13": 90, "f14": "银行Ⅱ"},
                }
            }
        }

    with patch(
        "src.tools.sector_tool.resolve_secid", side_effect=any_secid
    ), patch("src.tools.sector_tool.get_json", side_effect=any_get_json) as get:
        first = client.get(f"/runs/{RUN_ID}/positions/sectors")
        second = client.get(f"/runs/{RUN_ID}/positions/sectors?refresh=1")

    assert first.status_code == 200
    assert second.status_code == 200
    # The shared executor still caps lookups at 200 on every request.
    assert get.call_count == 2 * runs_routes._POSITIONS_SECTOR_MAX_SYMBOLS
    assert first.json()["symbol_limit"] == runs_routes._POSITIONS_SECTOR_MAX_SYMBOLS
    # Exactly one executor was created across both requests, bounded by
    # _POSITIONS_SECTOR_WORKERS, and never shut down (process-lifetime).
    assert len(created) == 1
    assert created[0]["max_workers"] == runs_routes._POSITIONS_SECTOR_WORKERS
    executor = runs_routes._POSITIONS_SECTOR_EXECUTOR
    assert executor is not None
    assert runs_routes._get_positions_sector_executor() is executor
    assert executor._max_workers == runs_routes._POSITIONS_SECTOR_WORKERS
    assert not executor._shutdown


# ============================================================================
# resolve_industry_board helper
# ============================================================================


class TestResolveIndustryBoard:
    """Direct unit tests for the sector_tool helper."""

    def test_returns_board_row_name_with_spt_1(self) -> None:
        with patch(
            "src.tools.sector_tool.resolve_secid", return_value="1.600519"
        ), patch("src.tools.sector_tool.get_json", return_value=_SLIST_600519) as get:
            assert resolve_industry_board("600519.SH") == "白酒Ⅱ"

        params = get.call_args.kwargs["params"]
        assert params["spt"] == "1"
        assert params["secid"] == "1.600519"
        assert params["fltt"] == "2"

    def test_non_a_share_returns_none_without_any_call(self) -> None:
        with patch("src.tools.sector_tool.resolve_secid") as resolve, patch(
            "src.tools.sector_tool.get_json"
        ) as get:
            assert resolve_industry_board("AAPL.US") is None

        resolve.assert_not_called()
        get.assert_not_called()

    def test_request_failure_returns_none(self) -> None:
        with patch(
            "src.tools.sector_tool.resolve_secid", return_value="1.600519"
        ), patch("src.tools.sector_tool.get_json", side_effect=RuntimeError("HTTP 429")):
            assert resolve_industry_board("600519.SH") is None

    def test_missing_board_row_returns_none(self) -> None:
        with patch(
            "src.tools.sector_tool.resolve_secid", return_value="0.159913"
        ), patch("src.tools.sector_tool.get_json", return_value=_SLIST_159913_NO_BOARD):
            assert resolve_industry_board("159913.SZ") is None
