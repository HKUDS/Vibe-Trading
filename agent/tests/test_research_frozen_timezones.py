import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.runner import _AutoLoader
from src.research_lab.execution import freeze_run


@pytest.mark.parametrize("timezone", ["Asia/Hong_Kong", "America/New_York"])
def test_engine_price_snapshot_can_be_frozen_across_dst(tmp_path, timezone):
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    source = "class SignalEngine:\n    def generate(self, data_map):\n        return {code: frame['close'] * 0 for code, frame in data_map.items()}\n"
    (root / "code/signal_engine.py").write_text(source)
    config = {"codes": ["AAPL.US"], "source": "local", "interval": "5m", "start_date": "2026-03-08", "end_date": "2026-03-08", "initial_cash": 10000}
    (root / "config.json").write_text(json.dumps(config))
    dates = pd.date_range("2026-03-08 01:55", periods=3, freq="5min", tz=timezone)
    prices = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 10000.}, index=dates)
    namespace = {}
    exec(source, namespace)
    engine = GlobalEquityEngine(config)
    engine.run_backtest(config, _AutoLoader({"AAPL.US": prices}, name="local"), namespace["SignalEngine"](), root)
    _, manifest, calendar, _ = freeze_run(root, tmp_path / "study")
    assert manifest.is_file()
    assert calendar.tolist() == dates.tolist()

@pytest.mark.parametrize("start", ["2026-03-08 01:55", "2026-11-01 01:55"])
def test_hourly_strategy_replays_across_dst(tmp_path, monkeypatch, start):
    from src.research_lab.execution import trial

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    dates = pd.date_range(start, periods=8, freq="5min", tz="America/New_York", ambiguous=True)
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    source = (
        "import pandas as pd\nclass SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        frame = data_map['AAPL.US']\n"
        "        assert str(frame.index.tz) == 'America/New_York'\n"
        "        return {'AAPL.US': pd.Series((frame.index.hour == 1).astype(float), index=frame.index)}\n"
    )
    (root / "code/signal_engine.py").write_text(source)
    config = {"codes": ["AAPL.US"], "source": "local", "interval": "5m", "start_date": str(dates[0].date()), "end_date": str(dates[-1].date()), "initial_cash": 10000, "slippage": 0, "slippage_us": 0}
    (root / "config.json").write_text(json.dumps(config))
    prices = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 100000.}, index=dates)
    namespace = {}
    exec(source, namespace)
    GlobalEquityEngine(config).run_backtest(config, _AutoLoader({"AAPL.US": prices}, name="local"), namespace["SignalEngine"](), root)
    _, manifest, calendar, _ = freeze_run(root, tmp_path / "study", use_evaluation_calendar=True)
    assert calendar.equals(dates)
    entry = json.loads(manifest.read_text())["frames"]["AAPL.US"]
    assert entry["timezone"] == "America/New_York"
    assert (manifest.parent / entry["path"]).read_bytes() == (root / "artifacts/ohlcv_AAPL.US.csv").read_bytes()
    if "03-08" in start:
        assert list(calendar.hour[:3]) == [1, 3, 3]
    else:
        assert calendar.is_unique and calendar[0].hour == calendar[1].hour == 1
        assert calendar[0].utcoffset() != calendar[1].utcoffset()
    measured = trial(tmp_path / "study", "replay", config, manifest)
    assert measured["equity"].index.equals(dates)
    replay = Path(measured["run_dir"])
    for name in ("target_positions.csv", "positions.csv", "trades.csv"):
        pd.testing.assert_frame_equal(pd.read_csv(root / "artifacts" / name), pd.read_csv(replay / "artifacts" / name))
    assert pd.read_csv(root / "artifacts/target_positions.csv").iloc[:, 1].max() > 0

    shortened = {**config, "end_date": dates[4].isoformat()}
    sliced = trial(tmp_path / "study", "sliced", shortened, manifest)
    assert sliced["equity"].index.equals(dates[:5])
    sliced_root = Path(sliced["run_dir"])
    sliced_entry = json.loads((sliced_root / "snapshot/manifest.json").read_text())["frames"]["AAPL.US"]
    assert sliced_entry["timezone"] == "America/New_York"
    assert sliced_entry["sha256"] != entry["sha256"]
    expected = pd.read_csv(root / "artifacts/target_positions.csv").iloc[:5].reset_index(drop=True)
    actual = pd.read_csv(sliced_root / "artifacts/target_positions.csv")
    pd.testing.assert_frame_equal(expected, actual)


@pytest.mark.parametrize("index", ["0,1", "NaT,1", "2026-01-01,2026-01-01", "2026-03-08 01:55:00-05:00,garbage"])
def test_calendar_reader_rejects_invalid_calendars(index):
    from backtest.frozen import read_calendar_csv

    raw = ("timestamp,value\n" + "\n".join(f"{value},1" for value in index.split(","))).encode()
    with pytest.raises(ValueError):
        read_calendar_csv(raw)


def test_calendar_reader_legacy_and_metadata_validation():
    from backtest.frozen import read_calendar_csv

    raw = b"timestamp,value\n2026-03-08 01:55:00-05:00,0.12345678901234566\n2026-03-08 03:00:00-04:00,0.2\n"
    frame = read_calendar_csv(raw)
    assert str(frame.index.tz) == "UTC"
    assert frame.iloc[0, 0] == 0.12345678901234566
    for zone in ("invalid/zone", "America/New_York"):
        with pytest.raises(ValueError):
            read_calendar_csv(b"timestamp,value\n2026-01-01,1\n", zone)
    with pytest.raises(ValueError):
        read_calendar_csv(raw, "invalid/zone")
    assert read_calendar_csv(b"timestamp,value\n2026-01-01,1\n").index.tz is None
    assert read_calendar_csv(b"timestamp,value\n2026-01-01 00:00:00+08:00,1\n").index[0].hour == 0


@pytest.mark.parametrize("zones", [(None, None), ("America/New_York", "America/New_York"), ("America/New_York", "Asia/Hong_Kong"), (None, "America/New_York")])
def test_freeze_evaluation_calendar_matches_engine_union(tmp_path, zones):
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    source = "class SignalEngine:\n    def generate(self, data_map):\n        return {code: frame['close'] * 0 for code, frame in data_map.items()}\n"
    (root / "code/signal_engine.py").write_text(source)
    config = {"codes": ["AAPL.US", "MSFT.US"], "source": "local", "interval": "1h", "start_date": "2026-03-07", "end_date": "2026-03-10", "initial_cash": 10000}
    (root / "config.json").write_text(json.dumps(config))
    frames = {}
    for code, zone in zip(config["codes"], zones):
        dates = pd.date_range("2026-03-08 01:00", periods=5, freq="h", tz=zone)
        frames[code] = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 10000.}, index=dates)
    namespace = {}
    exec(source, namespace)
    GlobalEquityEngine(config).run_backtest(config, _AutoLoader(frames, name="local"), namespace["SignalEngine"](), root)
    _, _, calendar, _ = freeze_run(root, tmp_path / "study", use_evaluation_calendar=True)
    from backtest.frozen import read_calendar_csv
    card = json.loads((root / "run_card.json").read_text())
    equity = read_calendar_csv((root / "artifacts/equity.csv").read_bytes(), card.get("calendar_timezones", {}).get("artifacts/equity.csv"))
    assert calendar.equals(equity.index)


def test_mixed_offsets_preserve_distinct_nanoseconds():
    from backtest.frozen import read_calendar_csv

    raw = (
        b"timestamp,value\n2026-03-08 01:59:59.123456788-05:00,1\n"
        b"2026-03-08 01:59:59.123456789-05:00,2\n2026-03-08 03:00:00.123456789-04:00,3\n"
    )
    frame = read_calendar_csv(raw, "America/New_York")
    assert frame.index.is_unique
    assert frame.index[1].value - frame.index[0].value == 1
    assert frame.index[2].nanosecond == 789


@pytest.mark.parametrize("kind", ["dateutil", "named_fixed"])
def test_fixed_offset_engine_freeze_replay(tmp_path, monkeypatch, kind):
    from datetime import timedelta, timezone
    from dateutil.tz import tzoffset
    from src.research_lab.execution import trial

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    zone = tzoffset(None, 19800) if kind == "dateutil" else timezone(timedelta(minutes=330), "custom")
    dates = pd.date_range("2026-01-05 09:30", periods=5, freq="5min", tz=zone)
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    source = ("import pandas as pd\nclass SignalEngine:\n    def generate(self, data_map):\n"
              "        frame = data_map['AAPL.US']\n"
              "        assert list(frame.index.hour) == [9, 9, 9, 9, 9]\n"
              "        return {'AAPL.US': pd.Series(1.0, index=frame.index)}\n")
    (root / "code/signal_engine.py").write_text(source)
    config = {"codes": ["AAPL.US"], "source": "local", "interval": "5m", "start_date": "2026-01-05", "end_date": "2026-01-05", "initial_cash": 10000}
    (root / "config.json").write_text(json.dumps(config))
    frame = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 100000.}, index=dates)
    namespace = {}
    exec(source, namespace)
    GlobalEquityEngine(config).run_backtest(config, _AutoLoader({"AAPL.US": frame}, name="local"), namespace["SignalEngine"](), root)
    _, manifest, calendar, _ = freeze_run(root, tmp_path / "study", use_evaluation_calendar=True)
    assert list(calendar.asi8) == list(dates.asi8)
    assert json.loads(manifest.read_text())["frames"]["AAPL.US"]["timezone"] == "+05:30"
    measured = trial(tmp_path / "study", "replay", config, manifest)
    assert list(measured["equity"].index.asi8) == list(dates.asi8)
    pd.testing.assert_frame_equal(pd.read_csv(root / "artifacts/target_positions.csv"), pd.read_csv(Path(measured["run_dir"]) / "artifacts/target_positions.csv"))


@pytest.mark.parametrize("start,end,valid", [
    ("2026-03-08", "2026-03-08T03:00:00-04:00", True),
    ("2026-03-09", "2026-03-08T23:59:59-04:00", False),
    ("2026-03-08T23:59:59-04:00", "2026-03-08", True),
    ("2026-03-09T00:00:00-04:00", "2026-03-08", False),
    ("2026-11-01T01:55:00-04:00", "2026-11-01T01:00:00-05:00", True),
    ("2026-11-01T01:00:00-05:00", "2026-11-01T01:55:00-04:00", False),
])
def test_frozen_config_date_boundaries(start, end, valid):
    from backtest.runner import BacktestConfigSchema

    config = {"codes": ["AAPL.US"], "start_date": start, "end_date": end, "frozen_data_manifest": "manifest.json"}
    if valid:
        BacktestConfigSchema(**config)
    else:
        with pytest.raises(ValueError):
            BacktestConfigSchema(**config)


def test_equal_offsets_with_distinct_zone_objects_replay_engine_calendar(tmp_path, monkeypatch):
    from datetime import timedelta, timezone
    from dateutil.tz import tzoffset
    from backtest.frozen import read_calendar_csv
    from src.research_lab.execution import trial

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    zones = [tzoffset(None, 19800), timezone(timedelta(minutes=330), "custom")]
    assert zones[0] != zones[1]
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    source = ("import pandas as pd\nclass SignalEngine:\n    def generate(self, data_map):\n"
              "        return {code: pd.Series(1.0, index=frame.index) for code, frame in data_map.items()}\n")
    (root / "code/signal_engine.py").write_text(source)
    config = {"codes": ["AAPL.US", "MSFT.US"], "source": "local", "interval": "5m", "start_date": "2026-01-05", "end_date": "2026-01-05", "initial_cash": 10000}
    (root / "config.json").write_text(json.dumps(config))
    frames = {}
    for code, zone in zip(config["codes"], zones):
        dates = pd.date_range("2026-01-05 09:30", periods=5, freq="5min", tz=zone)
        frames[code] = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 100000.}, index=dates)
    namespace = {}
    exec(source, namespace)
    GlobalEquityEngine(config).run_backtest(config, _AutoLoader(frames, name="local"), namespace["SignalEngine"](), root)
    original = read_calendar_csv((root / "artifacts/equity.csv").read_bytes())
    assert original.index.tz is None
    _, manifest, calendar, _ = freeze_run(root, tmp_path / "study", use_evaluation_calendar=True)
    assert calendar.equals(original.index)
    replay = trial(tmp_path / "study", "replay", config, manifest)
    assert replay["equity"].index.equals(original.index)
    for name in ("target_positions.csv", "positions.csv", "trades.csv"):
        pd.testing.assert_frame_equal(pd.read_csv(root / "artifacts" / name), pd.read_csv(Path(replay["run_dir"]) / "artifacts" / name))


@pytest.mark.parametrize("offset", [30, 0.5])
def test_second_offset_does_not_break_ordinary_engine(tmp_path, offset):
    from datetime import timedelta, timezone

    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    source = "class SignalEngine:\n    def generate(self, data_map):\n        return {code: frame['close'] * 0 for code, frame in data_map.items()}\n"
    (root / "code/signal_engine.py").write_text(source)
    config = {"codes": ["AAPL.US"], "source": "local", "interval": "5m", "start_date": "2026-01-05", "end_date": "2026-01-05", "initial_cash": 10000}
    (root / "config.json").write_text(json.dumps(config))
    dates = pd.date_range("2026-01-05 09:30", periods=4, freq="5min", tz=timezone(timedelta(hours=5, seconds=offset)))
    frame = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 10000.}, index=dates)
    namespace = {}
    exec(source, namespace)
    GlobalEquityEngine(config).run_backtest(config, _AutoLoader({"AAPL.US": frame}, name="local"), namespace["SignalEngine"](), root)
    assert (root / "run_card.json").exists()
    with pytest.raises(ValueError, match="unsupported.*timezone|timezone.*unsupported"):
        freeze_run(root, tmp_path / "study")


@pytest.mark.parametrize("start", ["2026-03-06", "2026-10-30"])
def test_options_replay_preserves_local_calendar_and_trades(tmp_path, monkeypatch, start):
    from backtest.engines.options_portfolio import run_options_backtest
    from src.research_lab.execution import trial

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    dates = pd.date_range(start, periods=6, freq="D", tz="America/New_York")
    root = tmp_path / "baseline"
    (root / "code").mkdir(parents=True)
    expiry = (dates[-1] + pd.Timedelta(days=30)).isoformat()
    source = f'''class SignalEngine:
    def generate(self, data_map):
        frame = data_map["AAPL.US"]
        if frame.index[0].hour != 0:
            return []
        leg = {{"type": "call", "strike": 100, "expiry": {expiry!r}, "qty": 1}}
        return [
            {{"date": str(frame.index[0].date()), "action": "open", "legs": [leg]}},
            {{"date": str(frame.index[-2].date()), "action": "close", "legs": [leg]}},
        ]
'''
    (root / "code/signal_engine.py").write_text(source)
    config = {
        "codes": ["AAPL.US"], "source": "local", "engine": "options", "interval": "1D",
        "start_date": str(dates[0].date()), "end_date": str(dates[-1].date()),
        "initial_cash": 10000,
    }
    (root / "config.json").write_text(json.dumps(config))
    prices = pd.DataFrame(
        {"open": 100., "high": 102., "low": 99., "close": 101., "volume": 10000.},
        index=dates,
    )
    namespace = {}
    exec(source, namespace)
    run_options_backtest(
        config, _AutoLoader({"AAPL.US": prices}, name="local"),
        namespace["SignalEngine"](), root,
    )
    _, manifest, _, _ = freeze_run(root, tmp_path / "study")
    measured = trial(tmp_path / "study", "replay", config, manifest)
    replay = Path(measured["run_dir"])
    original_trades = pd.read_csv(root / "artifacts/trades.csv")
    assert len(original_trades) == 2
    for name in ("trades.csv", "equity.csv", "greeks.csv"):
        pd.testing.assert_frame_equal(
            pd.read_csv(root / "artifacts" / name), pd.read_csv(replay / "artifacts" / name),
        )
