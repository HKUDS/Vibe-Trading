"""Offline API/CLI integration; all constituent rows and market prices are synthetic."""

from __future__ import annotations

import argparse
from threading import Event
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api import alpha_routes as api
from src.tools import build_registry
from src.factors import bench_runner, cli_handlers as cli, registry
from src.tools import alpha_bench_tool as tool
from tests.test_alpha_bench_nifty100 import (
    PRIVATE_ERROR,
    PRIVATE_MARKERS,
    response,
    roster,
)

IDS = ["alpha101_033", "alpha101_101"]
PERIOD = "2024-01-01/2024-03-01"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    cli.add_subparser(result.add_subparsers(dest="command"))
    return result


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Offline tests must not access the network")

    monkeypatch.setattr(requests, "get", reject)
    monkeypatch.setattr("src.market_data.fetch_market_data", reject)
    monkeypatch.setattr(cli, "_load_cli_env", lambda: None)
    monkeypatch.setattr(cli, "_console", None)
    monkeypatch.setattr(cli, "_stderr_console", None)
    api.ALPHA_BENCH_JOBS.clear()
    api.ALPHA_COMPARE_JOBS.clear()
    yield
    api.ALPHA_BENCH_JOBS.clear()
    api.ALPHA_COMPARE_JOBS.clear()


@pytest.fixture
def client():
    app = FastAPI()
    api.register_alpha_routes(
        app, require_auth=lambda: None, require_event_stream_auth=lambda: None
    )
    with TestClient(app) as value:
        yield value


def test_core_api_and_cli_universe_contracts_stay_in_sync():
    # API accepts BTC only to return its existing explicit single-asset error.
    assert set(cli._UNIVERSE_CHOICES) == api._BENCH_UNIVERSES - {"btc-usdt"}
    assert set(cli._UNIVERSE_CHOICES) == set(tool._UNIVERSE_TAG)
    assert (
        cli._LIST_UNIVERSE_ALIASES["nifty100"]
        == tool._UNIVERSE_TAG["nifty100"]
        == "equity_in"
    )
    assert "nifty100" not in api._VALID_UNIVERSES  # benchmark alias, not metadata


@pytest.mark.parametrize("universe", ["csi300", "sp500", "nifty100", "btc-usdt"])
@pytest.mark.parametrize("model", [api.BenchRequest, api.CompareRequest])
def test_request_models_accept_all_registered_benchmarks(model, universe):
    kwargs = {"zoo": "alpha101"} if model is api.BenchRequest else {"alpha_ids": IDS}
    assert model(universe=universe, period=PERIOD, **kwargs).universe == universe


@pytest.mark.parametrize(
    "universe", ["nifty50", "krx", "equity_in", "NIFTY100", "unknown"]
)
@pytest.mark.parametrize("model", [api.BenchRequest, api.CompareRequest])
def test_request_models_reject_unsupported_benchmarks(model, universe):
    kwargs = {"zoo": "alpha101"} if model is api.BenchRequest else {"alpha_ids": IDS}
    with pytest.raises(ValidationError, match="unknown universe"):
        model(universe=universe, period=PERIOD, **kwargs)


@pytest.mark.parametrize(
    "alias,metadata",
    [
        ("nifty100", "equity_in"),
        ("sp500", "equity_us"),
        ("csi300", "equity_cn"),
        ("btc-usdt", "crypto"),
    ],
)
def test_api_list_alias_matches_factor_metadata_filter(client, alias, metadata):
    first = client.get("/alpha/list", params={"universe": alias})
    second = client.get("/alpha/list", params={"universe": metadata})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["total"] > 0


def test_readiness_is_configuration_only_not_a_live_data_success(client, monkeypatch):
    load = Mock(side_effect=AssertionError("Readiness must not load data"))
    monkeypatch.setattr(tool, "_load_universe_panel", load)
    data = client.get("/alpha/readiness")
    assert data.status_code == 200
    row = data.json()["universes"]["nifty100"]
    assert row["ready"] and row["reason"] == "public_data"
    assert "Source availability is checked at run time" in row["description"]
    assert data.json()["universes"]["btc-usdt"]["ready"] is False
    load.assert_not_called()


@pytest.mark.parametrize("endpoint", ["bench", "compare"])
def test_api_registers_and_forwards_nifty100_jobs(client, monkeypatch, endpoint):
    called = Event()
    seen = []

    def worker(*args):
        seen.append(args)
        called.set()

    monkeypatch.setattr(api, f"_run_{endpoint}_blocking", worker)
    body = {"universe": "nifty100", "period": PERIOD}
    body.update({"zoo": "alpha101"} if endpoint == "bench" else {"alpha_ids": IDS})
    result = client.post(f"/alpha/{endpoint}", json=body)
    assert result.status_code == 202
    assert called.wait(3), "Synthetic worker should receive the accepted job"
    assert seen[0][2] == "nifty100"
    store = api.ALPHA_BENCH_JOBS if endpoint == "bench" else api.ALPHA_COMPARE_JOBS
    assert store[result.json()["job_id"]]["universe"] == "nifty100"


@pytest.mark.parametrize("endpoint", ["bench", "compare"])
@pytest.mark.parametrize(
    "universe,status", [("equity_in", 422), ("krx", 422), ("btc-usdt", 400)]
)
def test_api_rejects_invalid_or_single_asset_jobs_before_worker(
    client, monkeypatch, endpoint, universe, status
):
    worker = Mock()
    monkeypatch.setattr(api, f"_run_{endpoint}_blocking", worker)
    body = {"universe": universe, "period": PERIOD}
    body.update({"zoo": "alpha101"} if endpoint == "bench" else {"alpha_ids": IDS})
    assert client.post(f"/alpha/{endpoint}", json=body).status_code == status
    worker.assert_not_called()


@pytest.mark.parametrize("command", ["bench", "compare"])
@pytest.mark.parametrize("universe", ["csi300", "sp500", "nifty100"])
def test_cli_parser_accepts_benchmark_choices(command, universe):
    args = parser().parse_args(["alpha", command, "--universe", universe])
    assert args.universe == universe


@pytest.mark.parametrize("command", ["bench", "compare"])
@pytest.mark.parametrize(
    "universe", ["equity_in", "krx", "nifty50", "unknown", "btc-usdt"]
)
def test_cli_parser_rejects_unknown_or_metadata_benchmarks(command, universe):
    with pytest.raises(SystemExit) as caught:
        parser().parse_args(["alpha", command, "--universe", universe])
    assert caught.value.code == 2


def test_cli_list_alias_maps_to_india_without_computing_factors(capsys):
    p = parser()
    assert (
        cli.dispatch(
            p.parse_args(["alpha", "list", "--universe", "nifty100", "--json"])
        )
        == 0
    )
    alias = capsys.readouterr().out
    assert (
        cli.dispatch(
            p.parse_args(["alpha", "list", "--universe", "equity_in", "--json"])
        )
        == 0
    )
    assert alias == capsys.readouterr().out
    assert '"equity_in"' in alias


@pytest.mark.parametrize("command", ["bench", "compare"])
def test_cli_help_names_nifty100(command, capsys):
    with pytest.raises(SystemExit) as caught:
        parser().parse_args(["alpha", command, "--help"])
    assert caught.value.code == 0
    assert "NIFTY 100: nifty100" in capsys.readouterr().out


@pytest.fixture
def synthetic_market(monkeypatch, tmp_path):
    """Use the real loader and original factors on invented prices, never market data."""
    monkeypatch.setattr(requests, "get", Mock(return_value=response(roster())))
    codes = [f"TEST{i}.NS" for i in range(100)]
    rng = np.random.default_rng(100)
    dates = pd.bdate_range("2024-01-01", periods=40)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (40, 100)), axis=0))
    open_ = close * np.exp(rng.normal(0, 0.008, close.shape))
    data = {
        s: pd.DataFrame(
            {
                "open": open_[:, i],
                "close": close[:, i],
                "high": np.maximum(open_[:, i], close[:, i]) * 1.01,
                "low": np.minimum(open_[:, i], close[:, i]) * 0.99,
                "volume": rng.integers(1000, 10000, 40).astype(float),
            },
            index=dates,
        )
        for i, s in enumerate(codes)
    }
    data["_provenance"] = {
        s: {"source": "offline_synthetic", "volume_unit": "shares"} for s in codes
    }
    fetch = Mock(return_value=data)
    monkeypatch.setattr("src.market_data.fetch_market_data", fetch)
    monkeypatch.setattr(tool, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(tool, "_default_output_dir", lambda: tmp_path / "reports")
    original_registry = registry.Registry()
    # Restrict work to two unchanged original factors; preserve real calculations.
    selected = Mock(wraps=original_registry)
    selected.list.side_effect = lambda **kw: [
        aid for aid in original_registry.list(**kw) if aid in IDS
    ]
    monkeypatch.setattr(registry, "get_default_registry", lambda: selected)
    monkeypatch.setattr(bench_runner, "get_default_registry", lambda: selected)
    monkeypatch.setattr(cli, "Registry", lambda: selected)
    monkeypatch.setenv("VIBE_TRADING_BENCH_WORKERS", "1")
    loader = Mock(wraps=tool._load_nifty100_panel)
    monkeypatch.setattr(tool, "_load_nifty100_panel", loader)
    return fetch, loader


@pytest.mark.parametrize("endpoint", ["bench", "compare"])
def test_api_worker_reaches_actual_nifty_loader_offline(synthetic_market, endpoint):
    fetch, loader = synthetic_market
    job_id = "abcdef12"
    store = api.ALPHA_BENCH_JOBS if endpoint == "bench" else api.ALPHA_COMPARE_JOBS
    store[job_id] = {
        "status": "queued",
        "result": None,
        "error": None,
        "progress": {"n_done": 0, "n_total": 2, "current_alpha_id": None},
    }
    if endpoint == "bench":
        api._run_bench_blocking(job_id, "alpha101", "nifty100", PERIOD, 2, IDS[0])
    else:
        api._run_compare_blocking(job_id, IDS, "nifty100", PERIOD, "ir")
    assert store[job_id]["status"] == "done", store[job_id]
    assert store[job_id]["result"]["meta"]["universe"] == "nifty100"
    loader.assert_called_once_with("2024-01-01", "2024-03-01")
    assert len(fetch.call_args.kwargs["codes"]) == 100


@pytest.mark.parametrize("command", ["bench", "compare"])
def test_cli_execution_reaches_actual_nifty_loader_offline(
    synthetic_market, command, capsys
):
    fetch, loader = synthetic_market
    argv = ["alpha", command, "--universe", "nifty100", "--period", PERIOD]
    argv += ["--zoo", "alpha101"] if command == "bench" else IDS
    assert cli.dispatch(parser().parse_args(argv)) == 0
    out = capsys.readouterr().out
    assert '"universe": "nifty100"' in out
    loader.assert_called_once_with("2024-01-01", "2024-03-01")
    fetch.assert_called_once()


@pytest.mark.parametrize("endpoint", ["bench", "compare"])
@pytest.mark.parametrize("fallback_succeeds", [True, False])
def test_api_responses_do_not_expose_constituent_exception_details(
    client, synthetic_market, monkeypatch, caplog, endpoint, fallback_succeeds
):
    failure = requests.ConnectionError(PRIVATE_ERROR)
    monkeypatch.setattr(
        requests,
        "get",
        Mock(
            side_effect=[failure, response(roster()) if fallback_succeeds else failure]
        ),
    )
    job_id = "security-check"
    store = api.ALPHA_BENCH_JOBS if endpoint == "bench" else api.ALPHA_COMPARE_JOBS
    store[job_id] = {
        "status": "queued",
        "result": None,
        "error": None,
        "progress": {"n_done": 0, "n_total": 2, "current_alpha_id": None},
    }
    if endpoint == "bench":
        api._run_bench_blocking(job_id, "alpha101", "nifty100", PERIOD, 2, IDS[0])
    else:
        api._run_compare_blocking(job_id, IDS, "nifty100", PERIOD, "ir")
    result = client.get(f"/alpha/{endpoint}/{job_id}")
    assert result.status_code == 200
    assert store[job_id]["status"] == ("done" if fallback_succeeds else "error")
    if fallback_succeeds:
        assert store[job_id]["result"]["meta"]["constituent_fallback_used"]
    else:
        expected = (
            "no substitute universe"
            if endpoint == "bench"
            else "no requested alphas could be evaluated"
        )
        assert expected in str(store[job_id])
    for marker in PRIVATE_MARKERS:
        assert marker not in result.text + str(store[job_id]) + caplog.text


@pytest.mark.parametrize("command", ["bench", "compare"])
@pytest.mark.parametrize("fallback_succeeds", [True, False])
def test_cli_outputs_do_not_expose_constituent_exception_details(
    synthetic_market, monkeypatch, capsys, caplog, command, fallback_succeeds
):
    failure = requests.ConnectionError(PRIVATE_ERROR)
    monkeypatch.setattr(
        requests,
        "get",
        Mock(
            side_effect=[failure, response(roster()) if fallback_succeeds else failure]
        ),
    )
    argv = ["alpha", command, "--universe", "nifty100", "--period", PERIOD]
    argv += ["--zoo", "alpha101"] if command == "bench" else IDS
    status = cli.dispatch(parser().parse_args(argv))
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert status == (0 if fallback_succeeds else 1)
    assert (
        "constituent_fallback_used" in output
        if fallback_succeeds
        else "no substitute universe" in output
    )
    for marker in PRIVATE_MARKERS:
        assert marker not in output


@pytest.mark.parametrize(
    "tool_name,previous_description",
    [
        (
            "alpha_bench",
            "csi300 | sp500. btc-usdt is single-asset and is rejected before "
            "data loading. Alphas requiring fund:* SEC filings need sp500; "
            "elsewhere they are excluded.",
        ),
        (
            "alpha_compare",
            "csi300 | sp500. btc-usdt is single-asset and is rejected before "
            "data loading. csi300 needs TUSHARE_TOKEN; fund:* alphas require sp500.",
        ),
    ],
)
def test_discovered_tool_schemas_advertise_nifty100_without_changing_old_descriptions(
    tool_name, previous_description
):
    discovered = build_registry()
    definitions = {
        entry["function"]["name"]: entry["function"]
        for entry in discovered.get_definitions()
    }
    assert tool_name in discovered.tool_names
    field = definitions[tool_name]["parameters"]["properties"]["universe"]
    description = field["description"]
    assert description.replace(" | nifty100", "") == previous_description
    advertised = description.split(".", 1)[0].split(" | ")
    assert advertised == cli._UNIVERSE_CHOICES
    assert set(advertised) == api._BENCH_UNIVERSES - {"btc-usdt"}
    assert set(advertised) == set(tool._UNIVERSE_TAG)
    assert field["type"] == "string"
