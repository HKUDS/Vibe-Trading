from pathlib import Path
from datetime import date, timedelta

from src.chan_training_analysis import calculate_analysis_window, match_trade_structures
from src.chan_training_agent import run_chan_analysis
from src.chan_training_store import ChanTrainingStore


def _bars() -> list[dict[str, object]]:
    start = date(2025, 2, 1)
    return [{"time": (start + timedelta(days=index)).isoformat(), "open": 10, "high": 11 + index % 3, "low": 9 - index % 2, "close": 10, "volume": 100, "amount": 1000} for index in range(45)]


def test_trade_window_uses_natural_30_days_and_actual_snapshot() -> None:
    bars = _bars()
    window = calculate_analysis_window(bars, [{"bar_index": 35}], cursor=10)
    assert window["reason"] == "trade_window"
    assert window["start"] == "2025-02-06"
    assert window["end"] == "2025-03-08"
    assert window["available_start"] == "2025-02-06"
    assert window["missing"] is False


def test_trade_matching_never_uses_future_confirmed_signal() -> None:
    analysis = {"fractals": [], "strokes": [], "segments": [], "centers": [], "signals": [
        {"label": "B3", "side": "buy", "bar_index": 5, "confirmed_index": 5, "price": 10},
        {"label": "S3", "side": "sell", "bar_index": 8, "confirmed_index": 8, "price": 9},
    ]}
    matches = match_trade_structures([{"sequence": 1, "side": "buy", "bar_index": 4}, {"sequence": 2, "side": "sell", "bar_index": 7}], analysis)
    assert matches[0]["matched_signal"] is None
    assert matches[1]["matched_signal"] is None


def test_analysis_run_transitions_and_persists_structured_report(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session("user-1", {"market": "us", "period": "1d", "symbol": "AAPL.US", "name": "Apple", "initial_capital": "100000", "window_size": 2, "commission_rate": "0", "stamp_rate": "0", "transfer_rate": "0", "initial_cursor": 20}, _bars())
    run = store.create_analysis_run("user-1", session["id"], window={"reason": "trade_window"}, snapshot_summary={"source": "training_session_snapshot"}, analysis_version="chan-structure-v3")
    completed = run_chan_analysis(store, "user-1", run["id"], agent_runner=lambda context: "中文 Agent 补充")
    assert completed["status"] == "completed"
    assert completed["report"]["agent_report"] == "中文 Agent 补充"
    assert completed["report"]["data"]["analysis_version"] == "chan-structure-v3"


def test_analysis_run_preserves_failure_for_retry(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session("user-1", {"market": "us", "period": "1d", "symbol": "AAPL.US", "name": "Apple", "initial_capital": "100000", "window_size": 2, "commission_rate": "0", "stamp_rate": "0", "transfer_rate": "0"}, _bars())
    run = store.create_analysis_run("user-1", session["id"], window={}, snapshot_summary={}, analysis_version="chan-structure-v3")
    failed = run_chan_analysis(store, "user-1", run["id"], agent_runner=lambda _: (_ for _ in ()).throw(RuntimeError("provider down")))
    assert failed["status"] == "failed"
    assert "provider down" in failed["error"]


def test_analysis_run_isolated_by_user_scope(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session("alice", {"market": "us", "period": "1d", "symbol": "AAPL.US", "name": "Apple", "initial_capital": "100000", "window_size": 2, "commission_rate": "0", "stamp_rate": "0", "transfer_rate": "0"}, _bars())
    store.create_analysis_run("alice", session["id"], window={}, snapshot_summary={}, analysis_version="chan-structure-v3")
    try:
        store.get_analysis_run("bob", session["id"])
    except KeyError:
        pass
    else:
        raise AssertionError("cross-user analysis access must be rejected")
