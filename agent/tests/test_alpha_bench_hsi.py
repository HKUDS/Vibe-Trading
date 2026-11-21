"""HSI alias identity, public roster metadata and loader-chain integration."""

from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from backtest.loaders._symbol_utils import normalize_hk_symbol
from src.tools import alpha_bench_tool as tool
from src.tools import hsi_universe as hsi


@pytest.mark.parametrize("value", ["700", "0700", "0700.HK", "00700.HK", "HK.00700"])
def test_same_instrument(value):
    assert normalize_hk_symbol(value) == "0700.HK"


@pytest.mark.parametrize("value", ["0", "-700", "700.US", "abc", "100000"])
def test_bad_symbol(value):
    with pytest.raises(ValueError):
        normalize_hk_symbol(value)


def test_parse_table_without_counting_aliases_twice():
    html = "<table><tr><th>Ticker</th><th>Name</th><th>Sub-index</th></tr>"
    for code in ["SEHK: 700", "0700.HK", "SEHK: 5"]:
        html += f"<tr><td>{code}</td><td>Fixture</td><td>Finance</td></tr>"
    codes, sectors = hsi.parse_constituents(html + "</table>")
    assert codes == ["0700.HK", "0005.HK"]
    assert sectors == {code: "Finance" for code in codes}


def test_revision_date_belongs_to_parsed_html(monkeypatch):
    html = '<script>{"dateModified":"2026-10-01T18:43:56Z","wgRevisionId":123}</script>'
    html += pd.DataFrame(
        {
            "Ticker": [f"SEHK: {code}" for code in range(1, 51)],
            "Sector": ["Finance"] * 50,
        }
    ).to_html(index=False)
    monkeypatch.setattr(
        hsi.requests,
        "get",
        lambda *a, **kw: SimpleNamespace(text=html, raise_for_status=lambda: None),
    )
    codes, sectors, meta = hsi.fetch_constituents()
    assert len(codes) == len(sectors) == 50
    assert meta["constituent_source_date"] == "2026-10-01"
    assert meta["constituent_revision_id"] == "123"
    assert meta["degraded"] is True
    assert meta["constituent_reference_matches"] is False


def test_network_failure_has_full_dated_fallback(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(hsi.requests, "get", fail)
    codes, sectors, meta = hsi.fetch_constituents()
    assert len(codes) == len(set(codes)) == 95
    assert "0700.HK" in codes
    assert sectors == {}
    assert meta["degraded"] is True
    assert meta["constituent_source_date"] == hsi.FALLBACK_DATE


def patch_panel(monkeypatch, *, sectors=None):
    codes = ["700", "0700", "0700.HK", "0005.HK", "9988.HK"]
    metadata = {
        "constituent_source": "fixture",
        "constituent_source_date": "2026-10-01",
        "degraded": False,
    }
    monkeypatch.setattr(
        hsi, "fetch_benchmark_constituents", lambda: (codes, sectors or {}, metadata)
    )
    monkeypatch.setattr(
        "backtest.loaders.registry.resolve_loader",
        lambda market: (
            SimpleNamespace(name="tencent") if market == "hk_equity" else None
        ),
    )
    frame = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0],
            "close": [11.0, 12.0, 13.0],
            "volume": [100.0, 200.0, 300.0],
        },
        index=pd.date_range("2024-01-01", periods=3),
    )

    def fetch(**kwargs):
        assert kwargs["codes"] == ["0700.HK", "0005.HK", "9988.HK"]
        assert kwargs["source"] == "tencent"
        assert kwargs["max_fallback_attempts"] == 9
        assert kwargs["include_provenance"] and kwargs["as_frames"]
        return {
            "700.HK": frame,
            "0005.HK": frame,
            "_unresolved": ["9988.HK"],
            "_provenance": {
                "700.HK": {
                    "source": "tencent",
                    "adjustment": "raw",
                    "volume_unit": "shares",
                }
            },
        }

    monkeypatch.setattr("src.market_data.fetch_market_data", fetch)
    return frame


def test_panel_metadata_missing_names_and_currency(monkeypatch):
    patch_panel(monkeypatch)
    panel = tool._load_hsi_panel("2024-01-01", "2024-01-02")
    assert list(panel["close"].columns) == ["0005.HK", "0700.HK"]
    assert len(panel["close"]) == 2
    assert panel["_meta"]["missing_instruments"] == ["9988.HK"]
    assert panel["_meta"]["survivorship_bias"] is True
    assert panel["_meta"]["currency"] == "HKD"
    assert panel["_meta"]["price_sources"] == ["tencent"]
    assert panel["_meta"]["price_provenance"]["0700.HK"]["adjustment"] == "raw"
    assert panel["_meta"]["price_adjustments"]["0700.HK"] == "raw"
    assert panel["_meta"]["volume_units"]["0700.HK"] == "shares"
    assert "700.HK" in panel["_meta"]["raw_price_provenance"]
    assert "sector" not in panel
    pd.testing.assert_frame_equal(
        panel["vwap"], sum(panel[k] for k in ("open", "high", "low", "close")) / 4
    )


@pytest.mark.parametrize(
    "sectors,expected",
    [({"700": "Finance", "5": "Finance"}, True), ({"700": "Finance"}, False)],
)
def test_same_sector_coverage_threshold_as_sp500(monkeypatch, sectors, expected):
    patch_panel(monkeypatch, sectors=sectors)
    panel = tool._load_hsi_panel("2024-01-01", "2024-01-02")
    assert ("sector" in panel) is expected
    if expected:
        assert panel["sector"].index.equals(panel["close"].index)
        assert panel["sector"].columns.equals(panel["close"].columns)


def test_cache_keeps_hsi_metadata_without_refetch(monkeypatch, tmp_path):
    patch_panel(monkeypatch)
    monkeypatch.setattr(tool, "get_runtime_root", lambda: tmp_path)
    first = tool._load_universe_panel("hsi", "2024-01-01/2024-01-02")
    monkeypatch.setattr(
        tool, "_load_hsi_panel", lambda *a: pytest.fail("cache was not used")
    )
    second = tool._load_universe_panel("hsi", "2024-01-01/2024-01-02")
    assert second["_meta"] == first["_meta"]


def test_api_cli_universe_wiring():
    from src.api.alpha_routes import BenchRequest, CompareRequest
    from src.factors.cli_handlers import _LIST_UNIVERSE_ALIASES, _UNIVERSE_CHOICES

    assert (
        BenchRequest(zoo="alpha101", universe="hsi", period="2024-2024").universe
        == "hsi"
    )
    assert (
        CompareRequest(
            alpha_ids=["alpha101_001", "alpha101_002"],
            universe="hsi",
            period="2024-2024",
        ).universe
        == "hsi"
    )
    assert "hsi" in _UNIVERSE_CHOICES
    assert _LIST_UNIVERSE_ALIASES["hsi"] == "equity_hk"


def test_legacy_hsi_cache_cannot_hide_reconciliation_and_provenance_fix(
    monkeypatch, tmp_path
):
    patch_panel(monkeypatch)
    monkeypatch.setattr(tool, "get_runtime_root", lambda: tmp_path)
    cache = tmp_path / "cache"
    legacy = {
        "close": pd.DataFrame({"0700.HK": [1.0]}, index=pd.to_datetime(["2024-01-01"])),
        "_meta": {"legacy": True},
    }
    tool._write_pickle_cache(cache, cache / "hsi_2024-01-01_2024-01-02.pkl", legacy)
    panel = tool._load_universe_panel("hsi", "2024-01-01/2024-01-02")
    assert panel["_meta"]["hsi_metadata_version"] == 3
    assert "legacy" not in panel["_meta"]
    assert (cache / "hsi_v3_2024-01-01_2024-01-02.pkl").is_file()


def test_observed_panel_gaps_are_not_filled_by_hsi_layer(monkeypatch):
    frame = patch_panel(monkeypatch)
    frame.loc[pd.Timestamp("2024-01-02"), "volume"] = float("nan")
    panel = tool._load_hsi_panel("2024-01-01", "2024-01-02")
    assert pd.isna(panel["volume"].loc["2024-01-02", "0700.HK"])
    assert panel["_meta"]["missing_observations"]["volume"] == 2
    assert panel["_meta"]["universe_tag"] == "equity_hk"
    assert panel["_meta"]["point_in_time_membership"] is False
    assert (
        "shared upstream adapters may already" in panel["_meta"]["missing_data_policy"]
    )


def test_equal_alias_frames_deduplicate_but_conflicting_metadata_is_visible(
    monkeypatch,
):
    from src import market_data

    patch_panel(monkeypatch)
    fetch = market_data.fetch_market_data

    def aliases(**kwargs):
        result = fetch(**kwargs)
        result["0700.HK"] = result["700.HK"].copy()
        result["_provenance"]["0700.HK"] = {
            "source": "yahoo",
            "adjustment": "split_dividend",
            "volume_unit": "shares",
        }
        return result

    monkeypatch.setattr(market_data, "fetch_market_data", aliases)
    panel = tool._load_hsi_panel("2024-01-01", "2024-01-02")
    assert list(panel["close"].columns) == ["0005.HK", "0700.HK"]
    meta = panel["_meta"]
    assert meta["price_provenance"]["0700.HK"]["source"] == "tencent"
    assert set(meta["provenance_alias_conflicts"]["0700.HK"]) == {"700.HK", "0700.HK"}
    assert meta["degraded"] is True


def test_conflicting_alias_frames_cannot_silently_select_a_price_history(monkeypatch):
    from src import market_data

    patch_panel(monkeypatch)
    fetch = market_data.fetch_market_data

    def aliases(**kwargs):
        result = fetch(**kwargs)
        other = result["700.HK"].copy()
        other.loc[pd.Timestamp("2024-01-01"), "close"] += 1
        result["0700.HK"] = other
        return result

    monkeypatch.setattr(market_data, "fetch_market_data", aliases)
    with pytest.raises(ValueError, match="Conflicting HSI price frames"):
        tool._load_hsi_panel("2024-01-01", "2024-01-02")


def test_ambiguous_provenance_is_unknown_and_all_alias_diagnostics_survive():
    from src.tools.hsi_metadata import canonical_symbol_metadata, provenance_summary

    raw = {
        "700": {"source": "tencent", "adjustment": "raw", "volume_unit": "shares"},
        "0700.HK": {
            "source": "yahoo",
            "adjustment": "split_dividend",
            "volume_unit": "shares",
        },
    }
    canonical, conflicts = canonical_symbol_metadata(
        raw, ["0700.HK"], {"0700.HK": "00700.HK"}
    )
    assert canonical["0700.HK"].get("source") is None
    assert conflicts["0700.HK"] == raw
    assert provenance_summary(["0700.HK"], canonical)["price_adjustments"] == {
        "0700.HK": "unknown"
    }
    diagnostics, _ = canonical_symbol_metadata(
        {"700": {"attempts": ["first"]}, "0700.HK": {"attempts": ["second"]}},
        ["0700.HK"],
        {},
        diagnostics=True,
    )
    assert set(diagnostics["0700.HK"]["alias_diagnostics"]) == {"700", "0700.HK"}


def test_real_hsi_panel_uses_hk_identity_without_claiming_pit_data(monkeypatch):
    from src.factors.data_availability import build_availability_contract

    patch_panel(monkeypatch)
    contract = build_availability_contract(
        tool._load_hsi_panel("2024-01-01", "2024-01-02"), universe="hsi"
    )
    assert (
        contract["venue"],
        contract["currency"],
        contract["timezone"],
        contract["calendar"],
    ) == ("XHKG", "HKD", "Asia/Hong_Kong", "XHKG")
    membership = next(
        item for item in contract["fields"] if item["field"] == "universe:membership"
    )
    assert membership["status"] == "unknown" and membership["pit_safe"] is False


@pytest.mark.parametrize("available", [0, 1])
def test_fewer_than_two_usable_prices_fail_clearly(monkeypatch, available):
    from src import market_data

    patch_panel(monkeypatch)
    fetch = market_data.fetch_market_data

    def insufficient(**kwargs):
        result = fetch(**kwargs)
        result.pop("0005.HK")
        if available == 0:
            result["700.HK"]["close"] = float("nan")
        return result

    monkeypatch.setattr(market_data, "fetch_market_data", insufficient)
    with pytest.raises(RuntimeError, match="HSI prices unavailable: fewer than two"):
        tool._load_hsi_panel("2024-01-01", "2024-01-02")
