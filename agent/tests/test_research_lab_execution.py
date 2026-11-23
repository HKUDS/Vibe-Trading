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
