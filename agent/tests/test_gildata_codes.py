"""Tests for gildata_codes: recall matching, cache behavior, failure paths.

The MCP transport is injected, so no test touches the network.
"""

import json

import pytest

from backtest.loaders import gildata_codes as gc


def _transport(refs):
    """Build a fake transport returning candidates with the given ref codes."""
    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        return {
            "api_name": "ParamCandidateRecall",
            "candidates": [
                {"caption": f"name{i}", "code": str(1000 + i), "ref_code": ref}
                for i, ref in enumerate(refs)
            ],
        }

    return call_tool, calls


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point the disk cache at a temp file and clear the memo per test."""
    monkeypatch.setattr(gc, "_cache_path", lambda: tmp_path / "codes.json")
    gc.reset_code_cache()
    yield
    gc.reset_code_cache()


class TestResolve:
    """Exact ref_code matching against the recall candidates."""

    def test_exact_ref_match(self):
        transport, calls = _transport(["09999.HK", "00700.HK"])
        code = gc.resolve_vendor_code("hk_equity", "00700.HK", transport)
        assert code == "1001"
        name, arguments = calls[0]
        assert name == "ParamCandidateRecall"
        assert arguments["recall_list"][0]["api_name"] == "HKStockDailyQuotes"
        assert arguments["recall_list"][0]["param_name"] == "stockObject"

    def test_ss_normalized_for_index_match(self):
        transport, _ = _transport(["000300.SH"])
        code = gc.resolve_vendor_code("cn_index", "000300.SS", transport)
        assert code == "1000"

    def test_no_match_returns_none(self):
        transport, _ = _transport(["09999.HK"])
        assert gc.resolve_vendor_code("hk_equity", "00700.HK", transport) is None

    def test_transport_error_returns_none(self):
        def boom(name, arguments):
            raise RuntimeError("network down")

        assert gc.resolve_vendor_code("hk_equity", "00700.HK", boom) is None

    def test_unknown_kind_returns_none(self):
        transport, _ = _transport(["00700.HK"])
        assert gc.resolve_vendor_code("us_equity", "AAPL", transport) is None


class TestCache:
    """A resolved code is recalled once, then served from the caches."""

    def test_second_resolve_hits_memo(self):
        transport, calls = _transport(["00700.HK"])
        assert gc.resolve_vendor_code("hk_equity", "00700.HK", transport) == "1000"
        assert gc.resolve_vendor_code("hk_equity", "00700.HK", transport) == "1000"
        assert len(calls) == 1

    def test_disk_cache_survives_memo_clear(self):
        # Fresh resolve: code 1000. The post-clear transport would answer a
        # DIFFERENT code (1001) if it were consulted — proving the disk hit.
        transport, _ = _transport(["00700.HK"])
        assert gc.resolve_vendor_code("hk_equity", "00700.HK", transport) == "1000"
        gc.reset_code_cache()
        fresh_transport, fresh_calls = _transport(["09999.HK", "00700.HK"])
        code = gc.resolve_vendor_code("hk_equity", "00700.HK", fresh_transport)
        assert code == "1000"
        assert fresh_calls == []  # served from disk, no new recall

    def test_disk_entry_with_wrong_kind_is_ignored(self):
        # A code cached for another market must not shadow a live recall.
        import time

        path = gc._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"00700.HK": {"kind": "cn_index", "code": "42", "resolved_at": time.time()}}
            ),
            encoding="utf-8",
        )
        transport, calls = _transport(["09999.HK", "00700.HK"])
        code = gc.resolve_vendor_code("hk_equity", "00700.HK", transport)
        assert code == "1001"
        assert len(calls) == 1

    def test_stale_disk_entry_re_resolves(self):
        import time

        path = gc._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"00700.HK": {
                    "kind": "hk_equity", "code": "42",
                    "resolved_at": time.time() - gc._CACHE_MAX_AGE_S - 1,
                }}
            ),
            encoding="utf-8",
        )
        transport, calls = _transport(["09999.HK", "00700.HK"])
        assert gc.resolve_vendor_code("hk_equity", "00700.HK", transport) == "1001"
        assert len(calls) == 1
        # And the fresh mapping replaced the stale one on disk.
        disk = json.loads(path.read_text(encoding="utf-8"))
        assert disk["00700.HK"]["code"] == "1001"
