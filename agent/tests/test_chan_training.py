from __future__ import annotations

from pathlib import Path

import pytest

from src.api.chan_training_routes import _choose_session_data
from src.api import chan_training_routes
from src.chan_training_analysis import _centers, _segments, _signals, build_chan_analysis
from src.chan_training_store import ChanTrainingStore


def _bars(count: int = 60) -> list[dict[str, object]]:
    return [
        {"time": f"2025-01-{index + 1:02d}", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000}
        for index in range(count)
    ]


def test_instruments_are_persisted_and_randomly_available(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    assert store.upsert_instruments([
        {"market": "a_share", "symbol": "600000.SH", "name": "浦发银行", "exchange": "SH", "source": "test"},
        {"market": "us", "symbol": "AAPL.US", "name": "Apple Inc.", "exchange": "US", "source": "test"},
    ]) == 2
    assert store.count_instruments("a_share") == 1
    assert store.random_instrument("us")["symbol"] == "AAPL.US"


def test_empty_pool_requires_synchronization(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    with pytest.raises(LookupError, match="synchronize instruments"):
        _choose_session_data(store, "a_share", "1d", 60)


def test_a_share_sync_falls_back_when_eastmoney_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = [{"market": "a_share", "symbol": "600000.SH", "name": "测试", "exchange": "SH", "source": "akshare-exchange"}]
    monkeypatch.setattr(chan_training_routes, "_fetch_a_share_instruments_eastmoney", lambda: (_ for _ in ()).throw(ConnectionError("proxy reset")))
    monkeypatch.setattr(chan_training_routes, "_fetch_a_share_instruments_akshare", lambda: fallback)
    assert chan_training_routes._fetch_a_share_instruments() == fallback


def test_active_session_masks_identity_and_dates(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session(
        "user-1",
        {"market": "a_share", "period": "1d", "symbol": "600000.SH", "name": "浦发银行", "initial_capital": "100000", "window_size": 60, "commission_rate": "0.0003", "stamp_rate": "0.0005", "transfer_rate": "0.00001"},
        _bars(),
    )
    assert session["symbol"] == "600000.SH"
    masked = store.get_session("user-1", session["id"])
    assert masked["symbol"] is None
    assert masked["name"] is None
    assert masked["bars"][0]["time"] == "K1"


def test_delete_session_cascades_review_data(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session(
        "user-1",
        {"market": "us", "period": "1d", "symbol": "AAPL.US", "name": "Apple", "initial_capital": "100000", "window_size": 60, "commission_rate": "0", "stamp_rate": "0", "transfer_rate": "0"},
        _bars(),
    )
    store.execute_trade("user-1", session["id"], "buy", "1/2")
    store.delete_session("user-1", session["id"])
    with pytest.raises(KeyError):
        store.get_session("user-1", session["id"])


def test_full_buy_uses_all_affordable_cash(tmp_path: Path) -> None:
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session(
        "user-1",
        {
            "market": "a_share",
            "period": "1d",
            "symbol": "600000.SH",
            "name": "娴嬭瘯",
            "initial_capital": "100000",
            "window_size": 2,
            "commission_enabled": False,
            "commission_rate": "0",
            "stamp_enabled": False,
            "stamp_rate": "0",
            "transfer_enabled": False,
            "transfer_rate": "0",
        },
        [
            {"time": "2025-01-01", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
            {"time": "2025-01-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100},
        ],
    )

    updated = store.execute_trade("user-1", session["id"], "buy", "1")

    assert updated["position"] == "10000"
    assert updated["cash"] == "0"


def test_chan_analysis_is_persisted_and_live_payload_is_cursor_bounded(tmp_path: Path) -> None:
    bars = []
    highs_lows = [(10, 8), (12, 9), (11, 9), (10, 8), (9, 7), (11, 8), (13, 10), (12, 10), (11, 9), (10, 8), (9, 7), (12, 9), (14, 11), (13, 11), (12, 10), (11, 9), (10, 8), (13, 10), (15, 12), (14, 12)]
    for index, (high, low) in enumerate(highs_lows):
        bars.append({"time": f"2025-01-{index + 1:02d}", "open": low, "high": high, "low": low, "close": (high + low) / 2, "volume": 100, "amount": 1000})
    analysis = build_chan_analysis(bars)
    assert analysis["version"] == "chan-structure-v2"
    assert analysis["fractals"]
    store = ChanTrainingStore(tmp_path / "training.db")
    session = store.create_session(
        "user-1",
        {"market": "us", "period": "1d", "symbol": "AAPL.US", "name": "Apple", "initial_capital": "100000", "window_size": 2, "commission_rate": "0", "stamp_rate": "0", "transfer_rate": "0", "initial_cursor": 4},
        bars,
        analysis,
    )
    live = store.get_session("user-1", session["id"])
    assert live["chan_analysis"] is not None
    assert all(item["confirmed_index"] <= live["current_cursor"] for item in live["chan_analysis"]["fractals"])
    review = store.get_session("user-1", session["id"], include_hidden=True)
    assert len(review["chan_analysis"]["fractals"]) >= len(live["chan_analysis"]["fractals"])


def _stroke(index: int, direction: str, start: float, end: float, low: float, high: float) -> dict[str, object]:
    return {
        "stroke_index": index,
        "direction": direction,
        "start_index": index * 2,
        "end_index": index * 2 + 1,
        "start_price": start,
        "end_price": end,
        "low": low,
        "high": high,
        "confirmed_index": index * 2 + 1,
    }


def test_segments_extend_until_the_first_failed_same_direction_swing() -> None:
    strokes = [
        _stroke(0, "up", 1, 5, 1, 5),
        _stroke(1, "down", 5, 3, 3, 5),
        _stroke(2, "up", 3, 7, 3, 7),
        _stroke(3, "down", 7, 4, 4, 7),
        _stroke(4, "up", 4, 9, 4, 9),
    ]

    segments = _segments(strokes)

    assert len(segments) == 1
    assert segments[0]["stroke_end_index"] == 4
    assert segments[0]["end_price"] == 9


def test_centers_merge_overlapping_sliding_windows_and_extend() -> None:
    strokes = [
        _stroke(0, "up", 1, 5, 1, 5),
        _stroke(1, "down", 5, 3, 3, 5),
        _stroke(2, "up", 3, 7, 3, 7),
        _stroke(3, "down", 7, 4, 4, 7),
    ]

    centers = _centers(strokes)

    assert len(centers) == 1
    assert centers[0]["stroke_end_index"] == 3
    assert centers[0]["high"] == 5
    assert centers[0]["low"] == 4


def test_signals_use_a_confirmed_center_exit_and_retracement() -> None:
    strokes = [
        _stroke(0, "down", 5, 3, 3, 5),
        _stroke(1, "up", 3, 6, 3, 6),
        _stroke(2, "down", 6, 4, 4, 6),
        _stroke(3, "up", 4, 7, 4, 7),
        _stroke(4, "down", 7, 5.5, 5.5, 7),
    ]
    centers = [{
        "stroke_start_index": 0,
        "stroke_end_index": 2,
        "start_index": 0,
        "end_index": 5,
        "high": 5,
        "low": 4,
        "confirmed_index": 5,
    }]

    signals = _signals(strokes, centers)

    assert signals == [{
        "label": "B3",
        "side": "buy",
        "bar_index": 9,
        "price": 5.5,
        "confirmed_index": 9,
        "center_start_index": 0,
        "center_end_index": 5,
    }]
