"""Offline NSE Industry / OHLC4 tests; all quotes and rosters are synthetic."""

from __future__ import annotations

import csv
import io
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import requests

import src.market_data as market_data
import src.tools.alpha_bench_tool as tool
from src.factors.registry import Registry, SkipAlpha
from tests.test_alpha_bench_nifty100 import prices, response


def industry_roster(labels=None, *, include_industry=True):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Symbol", "Series"] + (["Industry"] if include_industry else []))
    labels = labels or {}
    for i in range(100):
        writer.writerow(
            [f"TEST{i}", "EQ"] + ([labels.get(i, "")] if include_industry else [])
        )
    return stream.getvalue().encode()


@pytest.fixture
def setup(monkeypatch):
    get = Mock(
        return_value=response(
            industry_roster(
                {i: "Industry A" if i % 2 else "Industry B" for i in range(100)}
            )
        )
    )
    monkeypatch.setattr(requests, "get", get)
    fetch = Mock(side_effect=lambda **kw: prices(kw["codes"]))
    monkeypatch.setattr(market_data, "fetch_market_data", fetch)
    return get, fetch


def test_official_industry_keys_are_normalized_and_blank_labels_not_invented(setup):
    get, _ = setup
    raw = industry_roster(
        {
            0: " Financial Services ",
            1: "Industrials, Other",
            2: "nan",
            3: "N/A",
            4: "UNKNOWN",
            5: "None",
            6: "null",
        }
    )
    get.return_value = response(raw.replace(b"TEST0,", b"m&m,"))
    _, meta = tool._fetch_nifty100_constituents()
    assert meta["constituent_industries"] == {
        "M&M.NS": "Financial Services",
        "TEST1.NS": "Industrials, Other",
    }
    assert meta["constituent_industry_column_present"]


@pytest.mark.parametrize("covered,attached", [(8, False), (9, True), (10, True)])
def test_existing_ninety_percent_gate_counts_loaded_symbols(setup, covered, attached):
    get, fetch = setup
    get.return_value = response(
        industry_roster({i: "Industry A" for i in range(covered)})
    )
    fetch.side_effect = lambda **kw: prices(kw["codes"][:10])
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    meta = panel["_meta"]
    assert meta["sector_coverage"] == covered / 10
    assert (
        meta["sector_coverage_threshold"] == tool._NIFTY100_MIN_SECTOR_COVERAGE == 0.9
    )
    assert ("sector" in panel) is attached
    assert meta["fetched_instruments"] == 10 and meta["requested_instruments"] == 100
    if attached:
        assert meta["sector_source"] == meta["constituent_source"]
        assert meta["sector_source_sha256"] == meta["constituent_sha256"]
        assert meta["sector_source_date"] == meta["constituent_source_date"]
        assert meta["sector_classification"] == "NSE Industry"
        assert meta["sector_source_column"] == "Industry"
        assert not meta["sector_point_in_time"]
        assert panel["sector"].axes[0].equals(panel["close"].axes[0])
        assert panel["sector"].axes[1].equals(panel["close"].axes[1])
        if covered == 9:
            assert panel["sector"]["TEST9.NS"].eq("UNKNOWN").all()
    else:
        assert meta["sector_source"] is None
        with pytest.raises(SkipAlpha, match="sector tag"):
            Registry().compute("alpha101_080", panel)


def test_threshold_is_reused_not_a_separate_nifty_magic_number(setup, monkeypatch):
    get, _ = setup
    get.return_value = response(industry_roster({i: "Industry A" for i in range(90)}))
    monkeypatch.setattr(tool, "_NIFTY100_MIN_SECTOR_COVERAGE", 0.95)
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert "sector" not in panel
    assert panel["_meta"]["sector_coverage_threshold"] == 0.95


@pytest.mark.parametrize("include_column", [False, True])
def test_missing_or_empty_industry_still_loads_prices_without_fake_sector(
    setup, include_column
):
    get, _ = setup
    get.return_value = response(industry_roster(include_industry=include_column))
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert "sector" not in panel
    assert panel["_meta"]["sector_coverage"] == 0
    assert panel["_meta"]["sector_source"] is None
    assert len(panel["close"].columns) == 100


def test_mirror_industry_provenance_and_sector_alignment(setup):
    get, _ = setup
    get.side_effect = [
        requests.Timeout("primary unavailable"),
        response(
            industry_roster(
                {i: "Industry A" if i % 2 else "Industry B" for i in range(100)}
            )
        ),
    ]
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    meta = panel["_meta"]
    assert meta["sector_source"] == tool._NIFTY100_CONSTITUENT_URLS[1]
    assert meta["sector_coverage"] == 1
    assert meta["sector_group_count"] == 2
    assert meta["constituent_fallback_used"]
    assert panel["sector"]["TEST0.NS"].eq("Industry B").all()
    assert panel["sector"]["TEST1.NS"].eq("Industry A").all()


def test_ohlc4_is_explicitly_approximate_and_not_volume_weighted(setup):
    _, fetch = setup
    data = prices([f"TEST{i}.NS" for i in range(100)])
    data["TEST0.NS"].iloc[1, 4] = 0
    original = data["TEST0.NS"].copy(deep=True)
    fetch.side_effect = None
    fetch.return_value = data
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    expected = sum(panel[field] for field in ("open", "high", "low", "close")) / 4
    pd.testing.assert_frame_equal(panel["vwap"], expected)
    pd.testing.assert_frame_equal(data["TEST0.NS"], original)
    assert panel["volume"].loc[original.index[1], "TEST0.NS"] == 0
    meta = panel["_meta"]
    assert meta["vwap_source"] == "ohlc4_approximation"
    assert meta["vwap_approximation"]
    assert not meta["vwap_approximation_is_exchange_observation"]
    assert meta["vwap_formula"] == "(open + high + low + close) / 4"
    assert meta["vwap_approximate_cells"] == 300
    assert meta["vwap_provided_cells"] == meta["vwap_missing_cells"] == 0


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_any_missing_ohlc_cell_keeps_approximate_vwap_missing(setup, field):
    _, fetch = setup
    data = prices([f"TEST{i}.NS" for i in range(100)])
    date = data["TEST0.NS"].index[1]
    data["TEST0.NS"].loc[date, field] = np.nan
    original = data["TEST0.NS"].copy(deep=True)
    fetch.side_effect = None
    fetch.return_value = data
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert pd.isna(panel[field].loc[date, "TEST0.NS"])
    assert pd.isna(panel["vwap"].loc[date, "TEST0.NS"])
    assert panel["_meta"]["vwap_missing_cells"] == 1
    pd.testing.assert_frame_equal(data["TEST0.NS"], original)


@pytest.mark.parametrize("field", ["open", "high", "low"])
def test_missing_whole_ohlc_field_does_not_manufacture_vwap(setup, field):
    _, fetch = setup
    data = prices([f"TEST{i}.NS" for i in range(100)])
    for key, frame in list(data.items()):
        if not key.startswith("_"):
            data[key] = frame.drop(columns=field)
    fetch.side_effect = None
    fetch.return_value = data
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert "vwap" not in panel and field not in panel
    assert panel["_meta"]["vwap_source"] is None
    assert panel["_meta"]["vwap_missing_cells"] == 300


@pytest.mark.parametrize("partial", [False, True])
def test_provider_vwap_takes_precedence_and_only_missing_cells_use_fallback(
    setup, partial
):
    _, fetch = setup
    data = prices([f"TEST{i}.NS" for i in range(100)])
    data["TEST0.NS"]["vwap"] = [200.0, np.nan if partial else 201.0, 202.0]
    original = data["TEST0.NS"].copy(deep=True)
    fetch.side_effect = None
    fetch.return_value = data
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert panel["vwap"]["TEST0.NS"].iloc[0] == 200
    assert panel["vwap"]["TEST0.NS"].iloc[2] == 202
    expected_mid = (
        sum(original[k].iloc[1] for k in ("open", "high", "low", "close")) / 4
    )
    assert panel["vwap"]["TEST0.NS"].iloc[1] == (expected_mid if partial else 201.0)
    meta = panel["_meta"]
    assert meta["vwap_source"] == "provider_with_ohlc4_fallback"
    assert meta["vwap_provided_cells"] == (2 if partial else 3)
    assert meta["vwap_approximate_cells"] == (298 if partial else 297)
    pd.testing.assert_frame_equal(data["TEST0.NS"], original)


def test_provided_vwap_survives_missing_ohlc_without_repairing_prices(setup):
    _, fetch = setup
    data = prices([f"TEST{i}.NS" for i in range(100)])
    data["TEST0.NS"]["vwap"] = [200.0, 201.0, 202.0]
    data["TEST0.NS"].iloc[1, 0] = np.nan
    fetch.side_effect = None
    fetch.return_value = data
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert pd.isna(panel["open"]["TEST0.NS"].iloc[1])
    assert panel["vwap"]["TEST0.NS"].iloc[1] == 201.0


def test_all_provider_vwap_remains_supplied_without_claiming_ohlc4(setup):
    _, fetch = setup
    data = prices([f"TEST{i}.NS" for i in range(100)])
    for key, frame in data.items():
        if not key.startswith("_"):
            frame["vwap"] = [200.0, 201.0, 202.0]
    fetch.side_effect = None
    fetch.return_value = data
    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    assert panel["vwap"].iloc[1].eq(201.0).all()
    assert panel["_meta"]["vwap_provided_cells"] == 300
    assert panel["_meta"]["vwap_approximate_cells"] == 0
    assert panel["_meta"]["vwap_source"] == "shared_loader_provided"
    assert panel["_meta"]["vwap_formula"] is None
    assert not panel["_meta"]["vwap_approximation"]


def test_availability_contract_does_not_mislabel_derived_vwap_as_yahoo_data(setup):
    from src.factors.data_availability import build_availability_contract

    panel = tool._load_nifty100_panel("2024-01-01", "2024-01-05")
    contract = build_availability_contract(panel, universe="nifty100")
    row = next(x for x in contract["fields"] if x["field"] == "vwap")
    assert row["source"] == "ohlc4_approximation"
    assert not row["pit_safe"]
    sector = next(x for x in contract["fields"] if x["field"] == "sector")
    assert sector["source"] == panel["_meta"]["constituent_source"]
