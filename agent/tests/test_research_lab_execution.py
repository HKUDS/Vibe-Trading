"""Exercise saved inputs -> sandboxed engine -> cost and frozen OOS reports."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research_lab.models import CostRequest, WalkForwardRequest
from src.research_lab.studies import cost_sensitivity, walk_forward


@pytest.fixture
def saved_run(tmp_path, monkeypatch, request):
    import dotenv
    from backtest import runner
    import backtest.loaders.local_loader as local

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    dates = pd.bdate_range("2026-01-01", periods=35)
    overrides = getattr(request, "param", {})
    codes = overrides.get("codes", ["local:AAPL.US"])
    symbol = codes[0].removeprefix("local:")
    if symbol == "000001.SZ":
        prices = np.linspace(10, 10.02, 35)
    else:
        prices = np.r_[np.linspace(10, 12, 15), np.linspace(11.8, 9, 20)]
    frame = pd.DataFrame(
        {"date": dates, "open": prices, "high": prices * 1.01, "low": prices * 0.99, "close": prices, "volume": 1e8}
    )
    sources = []
    for i, code in enumerate(codes):
        source = tmp_path / f"prices-{i}.csv"
        bars = frame if i == 0 else frame.assign(date=dates - pd.offsets.BDay(3))
        bars.to_csv(source, index=False)
        sources.append(
            {"symbol": code.removeprefix("local:"), "type": "csv", "path": str(source)}
        )
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps({"sources": sources}))
    monkeypatch.setattr(local, "_CONFIG_PATH", bridge)
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    (root / "code/signal_engine.py").write_text(
        "import pandas as pd\nfrom pathlib import Path\nclass SignalEngine:\n"
        "    def __init__(self, direction=1):\n        self.direction=direction\n"
        "    def generate(self, data_map):\n"
        "        snapshot = Path(__file__).resolve().parent.parent / 'snapshot/frame-0.csv'\n"
        "        if snapshot.is_file():\n"
        "            stored = pd.read_csv(snapshot, index_col=0, parse_dates=True)\n"
        "            if stored.index.max() > max(df.index.max() for df in data_map.values()):\n"
        "                raise ValueError('trial snapshot leaked future prices')\n"
        f"        frame = data_map[{symbol!r}]\n"
        f"        return {{{symbol!r}: pd.Series(self.direction, index=frame.index)}}\n"
    )
    (root / "config.json").write_text(
        json.dumps(
            {
                "codes": codes,
                "source": "local",
                "start_date": str(dates[0].date()),
                "end_date": str(dates[-1].date()),
                "initial_cash": 10000,
                "slippage": 0,
                "slippage_us": 0,
                **overrides,
            }
        )
    )
    runner.main(root)
    return root


def test_cost_study_reexecutes_same_frozen_data(saved_run, tmp_path):
    result = cost_sensitivity(
        CostRequest(
            run_dir=str(saved_run),
            scenarios=[
                {"name": "base"},
                {"name": "adverse", "extra_slippage_bps": 100},
            ],
        ),
        tmp_path / "cost-study",
        lambda value: None,
    )
    assert len(result["rows"]) == 2
    assert result["rows"][1]["total_return"] < result["rows"][0]["total_return"]
    assert result["rows"][1]["final_value"] < result["rows"][0]["final_value"]
    assert result["input_manifest_sha256"]


@pytest.fixture
def saved_benchmark_run(tmp_path, tmp_path_factory, monkeypatch, request):
    import dotenv
    from backtest import runner
    from backtest.loaders import local_loader

    interval, include_benchmark = getattr(request, "param", ("1D", False))
    portfolio = ["AAPL.US", "SPY.US"] if include_benchmark else ["AAPL.US"]
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path_factory.getbasetemp()))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    dates = pd.bdate_range("2026-01-05", "2026-05-29")
    prices = tmp_path / "prices"
    prices.mkdir()
    sources = []
    for code, opens, closes in (
        ("AAPL.US", np.linspace(20, 18, len(dates)), np.linspace(20, 18, len(dates))),
        ("SPY.US", np.linspace(10, 14, len(dates)), np.linspace(12, 15, len(dates))),
    ):
        path = prices / f"{code}.csv"
        pd.DataFrame(
            {
                "date": dates,
                "open": opens,
                "high": np.maximum(opens, closes),
                "low": np.minimum(opens, closes),
                "close": closes,
                "volume": 10_000,
            }
        ).to_csv(path, index=False)
        sources.append({"symbol": code, "type": "csv", "path": str(path)})
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps({"sources": sources}))
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", bridge)

    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    (root / "code/signal_engine.py").write_text(
        "import pandas as pd\nclass SignalEngine:\n"
        "    def generate(self, data_map):\n"
        f"        assert set(data_map) == set({portfolio!r})\n"
        "        return {code: pd.Series(0.0, index=frame.index) for code, frame in data_map.items()}\n"
    )
    (root / "config.json").write_text(
        json.dumps(
            {
                "codes": ["local:" + code for code in portfolio],
                "source": "local",
                "benchmark": "SPY.US",
                "start_date": str(dates[0].date()),
                "end_date": str(dates[-1].date()),
                "interval": interval,
                "initial_cash": 10_000,
                "slippage": 0,
                "slippage_us": 0,
            }
        )
    )
    runner.main(root)
    prices.rename(tmp_path / "archived-prices")
    return root


@pytest.mark.parametrize(
    "saved_benchmark_run", [("1D", False), ("1D", True)], indirect=True, ids=["external-only", "also-in-portfolio"]
)
def test_cost_study_preserves_benchmark_prices(saved_benchmark_run, tmp_path):
    original = json.loads((saved_benchmark_run / "run_card.json").read_text())["metrics"]
    assert original["benchmark_ticker"] == "SPY.US"
    assert original["benchmark_return"] == pytest.approx(0.5)

    study = cost_sensitivity(
        CostRequest(run_dir=str(saved_benchmark_run), scenarios=[{"name": "same costs"}]),
        tmp_path / "study",
        lambda event: None,
    )
    replay_root = Path(study["rows"][0]["run_dir"])
    replay = json.loads((replay_root / "run_card.json").read_text())["metrics"]
    baseline = pd.read_csv(saved_benchmark_run / "artifacts/equity.csv", index_col=0)
    repeated = pd.read_csv(replay_root / "artifacts/equity.csv", index_col=0)
    pd.testing.assert_series_equal(baseline["equity"], repeated["equity"], check_exact=True)
    assert replay["trade_count"] == original["trade_count"] == 0
    assert replay["benchmark_kind"] == original["benchmark_kind"] == "external"
    assert replay["benchmark_ticker"] == original["benchmark_ticker"]
    assert replay["benchmark_return"] == original["benchmark_return"]
    assert replay["excess_return"] == original["excess_return"]
    assert baseline["benchmark_equity"].iloc[0] == pytest.approx(12_000)
    pd.testing.assert_series_equal(baseline["benchmark_equity"], repeated["benchmark_equity"], check_exact=True)


@pytest.mark.parametrize("saved_benchmark_run", [("1W", False), ("1M", False)], indirect=True, ids=["weekly", "monthly"])
def test_trial_uses_already_aggregated_benchmark_inside_its_window(saved_benchmark_run, tmp_path):
    from backtest.frozen import read_benchmark_prices
    from src.research_lab.execution import digest, freeze_run, trial

    study = tmp_path / "study"
    config, manifest, calendar, _ = freeze_run(saved_benchmark_run, study)
    parent = json.loads(manifest.read_text())
    reference = parent["benchmark_input"]
    assert set(parent["frames"]) == {"AAPL.US"}
    assert parent["interval"] == config["interval"]
    assert reference["ticker"] == "SPY.US"
    prices = read_benchmark_prices((manifest.parent / reference["path"]).read_bytes(), None)
    assert prices.index.equals(calendar)

    start = (calendar[0] + pd.Timedelta(days=1)).date().isoformat()
    end = (calendar[-1] - pd.Timedelta(days=1)).date().isoformat()
    measured = trial(study, "shorter", {**config, "start_date": start, "end_date": end}, manifest)
    child = Path(measured["run_dir"]) / "snapshot"
    entry = json.loads((child / "manifest.json").read_text())["benchmark_input"]
    assert digest(child / entry["path"]) == entry["sha256"]
    visible = prices.loc[start:end]
    assert 2 <= len(visible) < len(prices)
    assert entry["rows"] == len(visible)
    pd.testing.assert_frame_equal(read_benchmark_prices((child / entry["path"]).read_bytes(), None), visible)
    assert measured["equity"].index.equals(visible.index)
    assert measured["equity"]["equity"].tolist() == [10_000] * len(visible)
    expected = visible["close"] / visible["open"].iloc[0]
    np.testing.assert_allclose(measured["equity"]["benchmark_equity"], 10_000 * expected, rtol=1e-12)
    assert measured["benchmark"]["ticker"] == "SPY.US"
    assert measured["benchmark"]["frozen_input_used"] is True
    assert measured["benchmark"]["return"] == pytest.approx(expected.iloc[-1] - 1, abs=1e-6)


@pytest.mark.parametrize("stage", ["source", "sealed"])
@pytest.mark.parametrize("problem", ["missing", "changed"])
def test_declared_frozen_benchmark_cannot_be_lost_or_changed(saved_benchmark_run, tmp_path, stage, problem):
    from src.research_lab.execution import freeze_run, trial

    study = tmp_path / "study"
    if stage == "source":
        card = json.loads((saved_benchmark_run / "run_card.json").read_text())
        prices = saved_benchmark_run / card["benchmark_input"]["path"]
    else:
        config, manifest, _, _ = freeze_run(saved_benchmark_run, study)
        entry = json.loads(manifest.read_text())["benchmark_input"]
        prices = manifest.parent / entry["path"]
    if problem == "missing":
        prices.rename(tmp_path / "detached-reference.csv")
    else:
        with prices.open("ab") as reference:
            reference.write(b"\n")
    with pytest.raises(ValueError, match=rf"frozen input (is )?{problem}: benchmark"):
        if stage == "source":
            freeze_run(saved_benchmark_run, study)
        else:
            trial(study, "bad-reference", config, manifest)


def test_older_cost_study_labels_reference_fallback(saved_benchmark_run, tmp_path):
    card_path = saved_benchmark_run / "run_card.json"
    card = json.loads(card_path.read_text())
    card.pop("benchmark_input")  # An unclaimed artifact is not a frozen reference.
    card_path.write_text(json.dumps(card))
    report = cost_sensitivity(
        CostRequest(run_dir=str(saved_benchmark_run), scenarios=[{"name": "old baseline"}]),
        tmp_path / "legacy-study",
        lambda event: None,
    )
    row = report["rows"][0]
    assert row["benchmark"]["kind"] == "equal_weight"
    assert row["benchmark"]["return"] == pytest.approx(-0.1)
    assert row["benchmark"]["frozen_input_used"] is False
    replay = json.loads((Path(row["run_dir"]) / "run_card.json").read_text())
    assert any("No frozen benchmark prices were saved" in warning for warning in replay["warnings"])


def test_benchmark_price_round_trip_preserves_zone_and_signed_closes(tmp_path):
    from backtest.benchmark import benchmark_from_prices
    from backtest.frozen import read_benchmark_prices, write_benchmark_prices

    dates = pd.DatetimeIndex(
        ["2026-10-30 16:00", "2026-11-02 16:00", "2026-11-03 16:00"],
        tz="America/New_York",
        name="timestamp",
    )
    prices = pd.DataFrame({"open": [10.0, np.nan, 18.25], "close": [-5.0, 12.125, 20.000000000000004]}, index=dates)
    path = tmp_path / "benchmark_prices.csv"
    write_benchmark_prices(path, prices)
    restored = read_benchmark_prices(path.read_bytes(), "America/New_York")
    pd.testing.assert_frame_equal(restored, prices, check_exact=True)
    result = benchmark_from_prices("SPY.US", restored)
    assert result is not None and result.total_ret is None
    assert result.total_return_over(dates) == restored["close"].iloc[-1] / restored["open"].iloc[0] - 1


def test_training_selection_precedes_frozen_oos_and_holdout(saved_run, tmp_path):
    request = WalkForwardRequest(
        run_dir=str(saved_run),
        train_bars=15,
        test_bars=5,
        holdout_bars=5,
        max_folds=1,
        objective="total_return",
        candidates=[
            {"name": "long", "parameters": {"direction": 1}},
            {"name": "short", "parameters": {"direction": -1}},
        ],
    )
    result = walk_forward(request, tmp_path / "wf-study", lambda value: None)
    assert result["folds"][0]["name"] == "long"
    assert result["folds"][0]["test"]["metrics"]["total_return"] < 0
    assert result["oos_bars"] == 5
    assert result["holdout"]["test_start"] > result["folds"][0]["test_end"]
    assert result["mode"] == "locked"
    assert (tmp_path / "wf-study/sealed_plan.json").is_file()
    assert (tmp_path / "wf-study/selection-1.json").is_file()


def test_walk_forward_api_exports_the_actual_oos_equity_csv(saved_run, tmp_path, monkeypatch):
    import csv
    import io

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.research_lab_routes import register_research_lab_routes
    from src.research_lab import service

    monkeypatch.setattr(service, "get_runs_dir", lambda: tmp_path)
    state = service.run(
        "walk_forward",
        {
            "run_dir": str(saved_run),
            "train_bars": 15,
            "test_bars": 5,
            "holdout_bars": 5,
            "max_folds": 1,
            "objective": "total_return",
            "candidates": [
                {"name": "long", "parameters": {"direction": 1}},
                {"name": "short", "parameters": {"direction": -1}},
            ],
        },
    )
    assert state["status"] == "completed"
    result = state["result"]
    artifact = service.job_root(state["id"]) / "oos_equity.csv"
    expected = artifact.read_bytes()
    app = FastAPI()
    register_research_lab_routes(app, lambda: None, lambda: None)

    with TestClient(app) as client:
        path = f"/api/research-lab/jobs/{state['id']}/report"
        assert client.get(path).json()["kind"] == "walk_forward"
        response = client.get(path, params={"format": "oos_equity_csv"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        assert response.content == expected
        assert client.get(path, params={"format": "unknown"}).status_code == 422

    rows = list(csv.DictReader(io.StringIO(expected.decode())))
    assert len(rows) == result["oos_bars"]
    assert float(rows[-1]["equity"]) == pytest.approx(
        10000 * (1 + result["oos_total_return"])
    )


def test_csv_export_rejects_a_completed_non_walk_forward_job(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.research_lab_routes import register_research_lab_routes
    from src.research_lab import service

    monkeypatch.setattr(service, "get_runs_dir", lambda: tmp_path)
    state = service.create_job("factor_audit", {})
    service._write(
        service.job_root(state["id"]) / "study.json",
        {**state, "status": "completed", "result": {"kind": "factor_audit"}},
    )
    app = FastAPI()
    register_research_lab_routes(app, lambda: None, lambda: None)
    with TestClient(app) as client:
        response = client.get(
            f"/api/research-lab/jobs/{state['id']}/report",
            params={"format": "oos_equity_csv"},
        )
    assert response.status_code == 422


def test_walk_forward_rejects_a_candidate_scored_on_a_different_calendar(
    saved_run, tmp_path, monkeypatch,
):
    from src.research_lab import studies

    evaluated = pd.read_csv(
        saved_run / "artifacts/equity.csv", index_col=0, parse_dates=True,
    )

    def trial(root, name, config, manifest, *, parameters):
        assert "train" in name
        return {
            "equity": evaluated.iloc[1:5],
            "metrics": {"total_return": 0.15},
            "run_dir": str(root),
        }

    monkeypatch.setattr(studies, "trial", trial)
    root = tmp_path / "wf-study"
    with pytest.raises(ValueError, match="training trial did not evaluate exactly"):
        walk_forward(
            WalkForwardRequest(
                run_dir=str(saved_run), train_bars=5, test_bars=3,
                objective="total_return", candidates=[{"name": "baseline"}],
            ),
            root,
            lambda value: None,
        )
    assert not (root / "selection-1.json").exists()


@pytest.mark.parametrize(
    "saved_run",
    [{"codes": ["local:AAPL.US", "local:MSFT.US"], "start_date": "2025-12-29"}],
    indirect=True,
)
def test_frozen_study_uses_manifested_scored_dates_without_an_explicit_boundary(
    saved_run, tmp_path,
):
    from src.research_lab.execution import freeze_run

    equity = saved_run / "artifacts/equity.csv"
    observed = pd.read_csv(equity, index_col=0, parse_dates=True).index
    unused_prices = pd.read_csv(
        saved_run / "artifacts/ohlcv_MSFT.US.csv", index_col=0, parse_dates=True,
    )
    assert unused_prices.index[0] < observed[0]
    _, manifest, calendar, _ = freeze_run(
        saved_run, tmp_path / "study", use_evaluation_calendar=True,
    )
    assert calendar.equals(observed)
    assert json.loads(manifest.read_text())["source_equity_sha256"] == (
        hashlib.sha256(equity.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("saved_run", [{"codes": ["local:000001.SZ"]}], indirect=True)
@pytest.mark.parametrize("enrichment", ["fundamentals", "events"])
def test_frozen_backtest_keeps_saved_enrichment(saved_run, tmp_path, monkeypatch, enrichment):
    from types import SimpleNamespace

    from backtest import runner
    from backtest.engines import base
    from src.research_lab.execution import freeze_run

    symbol = "000001.SZ"
    config_path = saved_run / "config.json"
    config = json.loads(config_path.read_text())
    with monkeypatch.context() as source_fixture:
        if enrichment == "fundamentals":
            config["fundamental_fields"] = {"income": ["revenue"]}
            column = "income_revenue"
            filings = pd.DataFrame(
                {"ts_code": [symbol], "ann_date": ["20260105"], "end_date": ["20251231"], "revenue": [125.0]}
            )
            provider = base.TushareFundamentalProvider(api=SimpleNamespace(income=lambda **_: filings))
            source_fixture.setattr(base, "TushareFundamentalProvider", lambda: provider)
        else:
            config["event_feeds"] = [{"name": "fixture", "route_template": "/news/{code}", "event_type": "sentiment"}]
            column = "event_score"
            events = pd.DataFrame({"ts_code": [symbol], "knowable_date": [pd.Timestamp("2026-01-05")], "score": [0.8]})
            provider = SimpleNamespace(is_available=lambda: True, query_events=lambda *_, **__: events)
            source_fixture.setattr(base, "RSSHubEventProvider", lambda **_: provider)
        config_path.write_text(json.dumps(config))
        (saved_run / "code/signal_engine.py").write_text(
            "class SignalEngine:\n"
            "    def generate(self, data_map):\n"
            f"        return {{code: frame[{column!r}].gt(0).astype(float) for code, frame in data_map.items()}}\n"
        )
        runner.main(saved_run)

    prices_path = Path(f"artifacts/ohlcv_{symbol}.csv")
    saved_prices = pd.read_csv(saved_run / prices_path, index_col=0, parse_dates=True)
    assert saved_prices.loc["2026-01-05", column] == pytest.approx(125.0 if enrichment == "fundamentals" else 0.8)
    config, manifest, _, _ = freeze_run(saved_run, tmp_path / "study")
    replay = tmp_path / "replay"
    (replay / "code").mkdir(parents=True)
    (replay / "code/signal_engine.py").write_bytes((manifest.parent / "signal_engine.py").read_bytes())
    (replay / "config.json").write_text(
        json.dumps({**config, "codes": [symbol], "frozen_data_manifest": str(manifest)})
    )

    def unexpected_provider(*args, **kwargs):
        pytest.fail("frozen backtest tried to enrich inputs again")

    monkeypatch.setattr(base, "TushareFundamentalProvider", unexpected_provider)
    monkeypatch.setattr(base, "RSSHubEventProvider", unexpected_provider)
    runner.main(replay)

    replayed_prices = pd.read_csv(replay / prices_path, index_col=0, parse_dates=True)
    pd.testing.assert_series_equal(replayed_prices[column], saved_prices[column])
    expected_equity = pd.read_csv(saved_run / "artifacts/equity.csv")
    assert expected_equity["equity"].nunique() > 1
    pd.testing.assert_frame_equal(pd.read_csv(replay / "artifacts/equity.csv"), expected_equity)


@pytest.mark.parametrize(
    "saved_run",
    [
        pytest.param({"warmup_bars": 10}, id="bar-count"),
        pytest.param({"evaluation_start_date": "2026-01-15"}, id="start-date"),
        pytest.param(
            {
                "warmup_bars": 10,
                "codes": ["local:AAPL.US", "local:MSFT.US"],
                "start_date": "2025-12-29",
            },
            id="extra-history-for-unused-symbol",
        ),
    ],
    indirect=True,
)
def test_walk_forward_keeps_source_warmup_out_of_training_and_test(saved_run, tmp_path):
    def calendar(path):
        return pd.read_csv(path, index_col=0, parse_dates=True).index

    prices = calendar(saved_run / "artifacts/ohlcv_AAPL.US.csv")
    evaluated = calendar(saved_run / "artifacts/equity.csv")
    assert evaluated.equals(prices[10:])
    result = walk_forward(
        WalkForwardRequest(
            run_dir=str(saved_run),
            train_bars=5,
            test_bars=3,
            holdout_bars=3,
            max_folds=1,
            objective="total_return",
            candidates=[{"name": "baseline"}],
        ),
        tmp_path / "wf-study",
        lambda value: None,
    )
    fold = result["folds"][0]
    train = Path(fold["training"][0]["run_dir"])
    test = Path(fold["test"]["run_dir"])
    assert calendar(train / "artifacts/equity.csv").equals(evaluated[:5])
    assert calendar(test / "artifacts/equity.csv").equals(evaluated[5:8])
    assert calendar(
        Path(result["holdout"]["test"]["run_dir"]) / "artifacts/equity.csv"
    ).equals(evaluated[-3:])
    train_prices = prices[prices <= evaluated[4]]
    test_prices = prices[prices <= evaluated[7]]
    assert calendar(train / "snapshot/frame-0.csv").equals(train_prices)
    assert calendar(train / "artifacts/ohlcv_AAPL.US.csv").equals(train_prices)
    assert calendar(test / "snapshot/frame-0.csv").equals(test_prices)


@pytest.mark.parametrize("saved_run", [{"warmup_bars": 30}], indirect=True)
def test_walk_forward_does_not_count_warmup_toward_minimum_bars(saved_run, tmp_path):
    with pytest.raises(ValueError, match="too few bars"):
        walk_forward(
            WalkForwardRequest(
                run_dir=str(saved_run),
                train_bars=5,
                test_bars=3,
                objective="total_return",
                candidates=[{"name": "baseline"}],
            ),
            tmp_path / "wf-study",
            lambda value: None,
        )


@pytest.mark.parametrize("saved_run", [{"warmup_bars": 10}], indirect=True)
def test_walk_forward_rejects_a_changed_source_evaluation_artifact(saved_run, tmp_path):
    equity = saved_run / "artifacts/equity.csv"
    equity.write_bytes(equity.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="source equity changed"):
        walk_forward(
            WalkForwardRequest(
                run_dir=str(saved_run),
                train_bars=5,
                test_bars=3,
                objective="total_return",
                candidates=[{"name": "baseline"}],
            ),
            tmp_path / "wf-study",
            lambda value: None,
        )
    assert not (tmp_path / "wf-study/trials").exists()


@pytest.mark.parametrize("saved_run", [{}, {"warmup_bars": 10}], indirect=True)
def test_rolling_fit_uses_only_its_own_evaluation_window(saved_run, tmp_path):
    evaluated = pd.read_csv(saved_run / "artifacts/equity.csv", index_col=0, parse_dates=True).index
    result = walk_forward(
        WalkForwardRequest(
            run_dir=str(saved_run),
            training="rolling",
            train_bars=5,
            test_bars=3,
            holdout_bars=3,
            max_folds=2,
            objective="total_return",
            candidates=[{"name": "baseline"}],
        ),
        tmp_path / "rolling-study",
        lambda value: None,
    )
    expected = (evaluated[:5], evaluated[3:8], evaluated[-8:-3])
    for fold, window in zip([*result["folds"], result["holdout"]], expected, strict=True):
        train = Path(fold["training"][0]["run_dir"])
        actual = pd.read_csv(train / "artifacts/equity.csv", index_col=0, parse_dates=True).index
        assert actual.equals(window)


@pytest.mark.parametrize("saved_run", [{"warmup_bars": 0}], indirect=True)
def test_cost_replay_does_not_require_a_saved_equity_calendar(saved_run, tmp_path):
    card_path = saved_run / "run_card.json"
    card = json.loads(card_path.read_text())
    card["artifacts"] = [entry for entry in card["artifacts"] if entry["path"] != "artifacts/equity.csv"]
    card_path.write_text(json.dumps(card))

    result = cost_sensitivity(
        CostRequest(run_dir=str(saved_run), scenarios=[{"name": "base"}]),
        tmp_path / "cost-study",
        lambda value: None,
    )
    row, = result["rows"]
    replay = pd.read_csv(Path(row["run_dir"]) / "artifacts/equity.csv", index_col=0)
    source = pd.read_csv(saved_run / "artifacts/equity.csv", index_col=0)
    assert replay.index.equals(source.index)


def test_modified_source_prices_are_not_relabelled_as_frozen(saved_run, tmp_path):
    prices = saved_run / "artifacts/ohlcv_AAPL.US.csv"
    prices.write_text(prices.read_text().replace("10.0", "10.1"))
    with pytest.raises(ValueError, match="snapshot changed"):
        cost_sensitivity(
            CostRequest(run_dir=str(saved_run), scenarios=[{"name": "base"}]),
            tmp_path / "changed-study",
            lambda value: None,
        )


@pytest.mark.parametrize("saved_run", [{"codes": ["local:000001.SZ"]}], indirect=True)
def test_fee_multiplier_reexecutes_minimum_fees_tax_and_measured_break_even(saved_run, tmp_path):
    result = cost_sensitivity(
        CostRequest(
            run_dir=str(saved_run),
            scenarios=[
                {"name": "zero", "fee_multiplier": 0},
                {"name": "high", "fee_multiplier": 10},
            ],
        ),
        tmp_path / "fees-study",
        lambda value: None,
    )
    assert result["rows"][0]["total_return"] > 0
    assert result["rows"][1]["total_return"] < 0
    assert result["break_even_brackets"] == [{"extra_slippage_bps": 0.0, "fee_multiplier_interval": [0.0, 10.0]}]
    import json

    commissions = []
    for row in result["rows"]:
        fills = [json.loads(line) for line in (Path(row["run_dir"]) / "artifacts/fills.jsonl").read_text().splitlines()]
        commissions.append(sum(float(fill["fee"]) for fill in fills))
    assert commissions[0] == 0
    assert commissions[1] > 100


def test_modified_source_configuration_is_refused(saved_run, tmp_path):
    path = saved_run / "config.json"
    config = json.loads(path.read_text())
    config["initial_cash"] = 5000
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="configuration changed"):
        cost_sensitivity(
            CostRequest(run_dir=str(saved_run), scenarios=[{"name": "base"}]),
            tmp_path / "changed-config",
            lambda value: None,
        )


def test_source_strategy_symlink_cannot_escape_run(saved_run, tmp_path):
    strategy = saved_run / "code/signal_engine.py"
    outside = tmp_path / "outside.py"
    outside.write_bytes(strategy.read_bytes())
    strategy.unlink()
    strategy.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes its run"):
        cost_sensitivity(
            CostRequest(run_dir=str(saved_run), scenarios=[{"name": "base"}]),
            tmp_path / "escaped-code",
            lambda value: None,
        )


def test_frozen_auto_source_uses_only_snapshot_benchmark(tmp_path, monkeypatch):
    from backtest.engines.global_equity import GlobalEquityEngine
    from backtest.runner import _AutoLoader

    dates = pd.bdate_range("2026-01-01", periods=10)
    prices = np.linspace(10, 11, len(dates))
    frame = pd.DataFrame(
        {"open": prices, "high": prices * 1.01, "low": prices * 0.99, "close": prices, "volume": 1e8}, index=dates
    )

    class FlatSignal:
        def generate(self, data_map):
            return {code: pd.Series(0.0, index=value.index) for code, value in data_map.items()}

    def no_network(*args, **kwargs):
        pytest.fail("frozen benchmark tried a network provider")

    monkeypatch.setattr("backtest.benchmark.YfinanceLoader", no_network)
    config = {
        "codes": ["AAPL.US"],
        "source": "auto",
        "benchmark": "AAPL.US",
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "initial_cash": 10000,
        "frozen_data_manifest": "sealed-manifest",
    }
    result = GlobalEquityEngine(config).run_backtest(
        config, _AutoLoader({"AAPL.US": frame}, name="local"), FlatSignal(), tmp_path
    )
    assert result["benchmark_kind"] == "external"
    assert result["benchmark_return"] == pytest.approx(0.1)


def test_declared_frozen_benchmark_rejects_unusable_evaluation_window(tmp_path):
    from backtest.engines.global_equity import GlobalEquityEngine
    from backtest.frozen import FrozenBenchmarkInput
    from backtest.runner import _AutoLoader

    dates = pd.date_range("2026-01-05", "2026-01-09", freq="D")
    strategy_prices = np.linspace(20, 24, len(dates))
    strategy = pd.DataFrame(
        {
            "open": strategy_prices,
            "high": strategy_prices,
            "low": strategy_prices,
            "close": strategy_prices,
            "volume": 10_000,
        },
        index=dates,
    )
    benchmark_prices = np.linspace(10, 13, len(dates) - 1)
    benchmark = pd.DataFrame({"open": benchmark_prices, "close": benchmark_prices}, index=dates[:-1])

    class FlatSignal:
        def generate(self, data_map):
            return {code: pd.Series(0.0, index=value.index) for code, value in data_map.items()}

    config = {
        "codes": ["AAPL.US"],
        "source": "local",
        "benchmark": "SPY.US",
        "start_date": "2026-01-05",
        "end_date": "2026-01-09",
        "evaluation_start_date": "2026-01-08",
        "initial_cash": 10_000,
        "frozen_data_manifest": "sealed-manifest",
    }
    loader = _AutoLoader(
        {"AAPL.US": strategy},
        name="local",
        benchmark_input=FrozenBenchmarkInput("SPY.US", benchmark),
    )

    with pytest.raises(ValueError, match="frozen benchmark.*lacks usable prices in the evaluation window"):
        GlobalEquityEngine(config).run_backtest(config, loader, FlatSignal(), tmp_path)
