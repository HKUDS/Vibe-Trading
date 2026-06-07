"""Local paper-trading adapter for ztrade V47 strategies.

This module promotes a validated autoresearch parameter file into a normal
Vibe-Trading run directory and replays it through the China A-share execution
rules without connecting to a broker.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.engines.china_a import ChinaAEngine
from backtest.models import EquitySnapshot
from src.tools.path_utils import safe_run_dir
from src.ztrade_autoresearch.candidate_strategy import ZTradeV47SignalEngine
from src.ztrade_autoresearch.protocol import FROZEN_CSV_END, FROZEN_CSV_START, STRATEGY_FAMILY
from src.ztrade_autoresearch.research_loop import validate_v47_params
from src.ztrade_autoresearch.runner import (
    ZtradeCsvLoader,
    _synthetic_data_map,
    _warmup_start,
    discover_ztrade_csv_universe,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyPayload:
    """Validated ztrade strategy params plus promotion metadata."""

    candidate_id: str
    strategy_family: str
    score: float | None
    params: dict[str, Any]


class StaticDataLoader:
    """Loader wrapper for a pre-fetched data map."""

    name = "static"

    def __init__(self, data_map: dict[str, pd.DataFrame], *, name: str) -> None:
        self._data_map = data_map
        self.name = name

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        fields: list[str] | None = None,
        interval: str = "1D",
    ) -> dict[str, pd.DataFrame]:
        del start_date, end_date, fields, interval
        return {code: self._data_map[code].copy() for code in codes if code in self._data_map}


class PaperChinaAEngine(ChinaAEngine):
    """ChinaAEngine variant that keeps open positions at the replay endpoint."""

    def _execute_bars(
        self,
        dates: pd.DatetimeIndex,
        data_map: dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        target_pos: pd.DataFrame,
        codes: list[str],
    ) -> None:
        for i, ts in enumerate(dates):
            self._bar_idx = i

            for code in codes:
                if ts in data_map[code].index:
                    self.on_bar(code, data_map[code].loc[ts], ts)

            equity = self._calc_equity(close_df, ts)
            for code in codes:
                try:
                    target_w = float(target_pos.at[ts, code]) if ts in target_pos.index else 0.0
                    self._rebalance(code, target_w, data_map.get(code), ts, equity)
                except Exception as exc:  # noqa: BLE001 - match BaseEngine's resilient loop
                    logger.warning("Paper rebalance failed for %s at %s: %s", code, ts, exc)

            snap_equity = self._calc_equity(close_df, ts)
            total_unrealized = 0.0
            for position in self.positions.values():
                close_price = self._safe_price(close_df, ts, position.symbol, position.entry_price)
                total_unrealized += self._calc_pnl(
                    position.symbol,
                    position.direction,
                    position.size,
                    position.entry_price,
                    close_price,
                )
            self.equity_snapshots.append(
                EquitySnapshot(
                    timestamp=ts,
                    capital=self.capital,
                    unrealized=total_unrealized,
                    equity=snap_equity,
                    positions=len(self.positions),
                )
            )


def default_params_path() -> Path:
    """Return the repo-level ztrade best params file."""

    return Path(__file__).resolve().parents[3] / "autoresearch" / "best" / "v47_params.json"


def load_strategy_payload(params_path: str | Path | None = None) -> StrategyPayload:
    """Load and validate a ztrade V47 params payload."""

    path = Path(params_path) if params_path is not None else default_params_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_params = payload.get("params", payload)
    if not isinstance(raw_params, dict):
        raise ValueError("ztrade params file must contain a JSON object or a params object")
    params = validate_v47_params(raw_params)
    return StrategyPayload(
        candidate_id=str(payload.get("candidate_id") or "candidate_mutable_v47"),
        strategy_family=str(payload.get("strategy_family") or STRATEGY_FAMILY),
        score=float(payload["score"]) if payload.get("score") is not None else None,
        params=params,
    )


def write_signal_engine(path: Path, payload: StrategyPayload) -> None:
    """Write a Vibe-Trading SignalEngine for the validated params."""

    params_literal = json.dumps(payload.params, ensure_ascii=False, sort_keys=True, indent=4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                '"""Promoted ztrade V47 paper-trading SignalEngine."""',
                "",
                "from src.ztrade_autoresearch.candidate_strategy import ZTradeV47SignalEngine",
                "",
                f"CANDIDATE_ID = {payload.candidate_id!r}",
                f"STRATEGY_FAMILY = {payload.strategy_family!r}",
                f"EVALUATOR_SCORE = {payload.score!r}",
                f"PARAMS = {params_literal}",
                "",
                "class SignalEngine(ZTradeV47SignalEngine):",
                "    def __init__(self):",
                "        super().__init__(**PARAMS)",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_ztrade_paper_sim(
    run_dir: str | Path,
    *,
    params_path: str | Path | None = None,
    mode: str = "ztrade_csv",
    data_dir: str | Path | None = None,
    codes: list[str] | None = None,
    window_start: str = FROZEN_CSV_START,
    window_end: str = FROZEN_CSV_END,
    max_symbols: int = 200,
    initial_cash: float = 1_000_000.0,
    synthetic_periods: int = 80,
) -> dict[str, Any]:
    """Run a local paper-trading replay for a promoted ztrade strategy.

    The result is broker-free by construction: it writes deterministic local
    artifacts and never reaches an order gateway.
    """

    run_path = safe_run_dir(str(run_dir))
    run_path.mkdir(parents=True, exist_ok=True)
    (run_path / "artifacts").mkdir(parents=True, exist_ok=True)

    payload = load_strategy_payload(params_path)
    data_map, selected_codes, config, loader_name = _prepare_inputs(
        mode=mode,
        data_dir=data_dir,
        codes=codes,
        window_start=window_start,
        window_end=window_end,
        max_symbols=max_symbols,
        initial_cash=initial_cash,
        synthetic_periods=synthetic_periods,
    )
    if not selected_codes:
        raise ValueError("no symbols available for ztrade paper simulation")

    write_signal_engine(run_path / "code" / "signal_engine.py", payload)
    (run_path / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    signal_engine = ZTradeV47SignalEngine(
        **payload.params,
        active_start_date=config.get("research_window_start") or config["start_date"],
    )
    loader = StaticDataLoader(data_map, name=loader_name)
    engine = PaperChinaAEngine(config)
    metrics = engine.run_backtest(
        config,
        loader,
        signal_engine,
        run_path,
        bars_per_year=252,
    )

    return _write_paper_state(
        run_path=run_path,
        payload=payload,
        mode=mode,
        config=config,
        data_map=data_map,
        engine=engine,
        metrics=metrics,
    )


def _prepare_inputs(
    *,
    mode: str,
    data_dir: str | Path | None,
    codes: list[str] | None,
    window_start: str,
    window_end: str,
    max_symbols: int,
    initial_cash: float,
    synthetic_periods: int,
) -> tuple[dict[str, pd.DataFrame], list[str], dict[str, Any], str]:
    if mode == "synthetic":
        data_map = _synthetic_data_map(
            seed=41,
            start=window_start,
            periods=synthetic_periods,
            regime="live_like",
        )
        selected_codes = [code for code in (codes or list(data_map)) if code in data_map]
        last_date = str(data_map[selected_codes[0]].index[-1].date()) if selected_codes else window_end
        config = _base_config(
            codes=selected_codes,
            start_date=window_start,
            end_date=last_date,
            initial_cash=initial_cash,
            source="synthetic_paper",
        )
        config["_run_card_effective_sources"] = ["synthetic_paper"]
        return data_map, selected_codes, config, "synthetic_paper"

    if mode != "ztrade_csv":
        raise ValueError("mode must be 'ztrade_csv' or 'synthetic'")
    if data_dir is None:
        raise ValueError("data_dir is required when mode='ztrade_csv'")

    selected_codes = codes or discover_ztrade_csv_universe(
        data_dir,
        start_date=window_start,
        end_date=window_end,
        max_symbols=max_symbols,
        min_rows=1,
    )
    data_start = _warmup_start(window_start)
    loader = ZtradeCsvLoader(data_dir)
    data_map = loader.fetch(selected_codes, data_start, window_end, interval="1D")
    selected_codes = [code for code in selected_codes if code in data_map]
    config = _base_config(
        codes=selected_codes,
        start_date=data_start,
        end_date=window_end,
        initial_cash=initial_cash,
        source="ztrade_csv_paper",
    )
    config["research_window_start"] = window_start
    config["research_window_end"] = window_end
    config["_run_card_effective_sources"] = ["ztrade_csv"]
    return data_map, selected_codes, config, "ztrade_csv"


def _base_config(
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    source: str,
) -> dict[str, Any]:
    return {
        "codes": codes,
        "start_date": start_date,
        "end_date": end_date,
        "source": source,
        "engine": "daily",
        "interval": "1D",
        "initial_cash": initial_cash,
        "commission_rate": 0.00025,
        "commission_min": 5.0,
        "stamp_tax": 0.0005,
        "transfer_fee": 0.00001,
        "slippage": 0.001,
        "paper_trading": True,
        "broker": None,
    }


def _write_paper_state(
    *,
    run_path: Path,
    payload: StrategyPayload,
    mode: str,
    config: dict[str, Any],
    data_map: dict[str, pd.DataFrame],
    engine: PaperChinaAEngine,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    positions_path = run_path / "artifacts" / "positions.csv"
    target_pos = pd.read_csv(positions_path, index_col="timestamp", parse_dates=True)
    last_ts = pd.Timestamp(target_pos.index[-1])
    latest_targets = {
        code: round(float(weight), 8)
        for code, weight in target_pos.iloc[-1].dropna().items()
        if abs(float(weight)) > 1e-9
    }

    state = {
        "status": "ok",
        "mode": mode,
        "broker": None,
        "no_broker": True,
        "execution": "local_paper_simulation",
        "strategy": {
            "candidate_id": payload.candidate_id,
            "strategy_family": payload.strategy_family,
            "evaluator_score": payload.score,
        },
        "run_dir": str(run_path),
        "as_of": str(last_ts.date()),
        "window": [
            config.get("research_window_start") or config["start_date"],
            config.get("research_window_end") or config["end_date"],
        ],
        "universe_size": len(config.get("codes") or []),
        "portfolio": _portfolio_state(engine),
        "open_positions": _open_positions(engine, data_map, latest_targets, last_ts),
        "latest_targets": latest_targets,
        "next_rebalance_intents": _rebalance_intents(target_pos, data_map, last_ts, engine),
        "metrics": {
            key: value
            for key, value in metrics.items()
            if key
            in {
                "total_return",
                "annual_return",
                "max_drawdown",
                "sharpe",
                "win_rate",
                "trade_count",
            }
        },
        "artifacts": {
            "config": str(run_path / "config.json"),
            "signal_engine": str(run_path / "code" / "signal_engine.py"),
            "paper_state": str(run_path / "artifacts" / "paper_state.json"),
            "equity": str(run_path / "artifacts" / "equity.csv"),
            "positions": str(positions_path),
            "trades": str(run_path / "artifacts" / "trades.csv"),
            "run_card": str(run_path / "run_card.json"),
        },
        "safety": {
            "places_real_orders": False,
            "order_gateway": None,
            "notes": "Research-only paper simulation; does not connect to a broker or submit orders.",
        },
    }
    (run_path / "artifacts" / "paper_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return state


def _portfolio_state(engine: PaperChinaAEngine) -> dict[str, float | int]:
    if engine.equity_snapshots:
        snap = engine.equity_snapshots[-1]
        return {
            "initial_cash": round(engine.initial_capital, 4),
            "cash": round(snap.capital, 4),
            "unrealized": round(snap.unrealized, 4),
            "equity": round(snap.equity, 4),
            "open_positions": snap.positions,
        }
    return {
        "initial_cash": round(engine.initial_capital, 4),
        "cash": round(engine.capital, 4),
        "unrealized": 0.0,
        "equity": round(engine.capital, 4),
        "open_positions": len(engine.positions),
    }


def _open_positions(
    engine: PaperChinaAEngine,
    data_map: dict[str, pd.DataFrame],
    latest_targets: dict[str, float],
    last_ts: pd.Timestamp,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, position in sorted(engine.positions.items()):
        last_price = _last_close(data_map, symbol, last_ts) or position.entry_price
        unrealized = engine._calc_pnl(
            symbol,
            position.direction,
            position.size,
            position.entry_price,
            last_price,
        )
        rows.append(
            {
                "symbol": symbol,
                "direction": "long" if position.direction > 0 else "short",
                "size": round(position.size, 6),
                "entry_price": round(position.entry_price, 4),
                "last_price": round(last_price, 4),
                "entry_time": str(position.entry_time.date()),
                "market_value": round(position.size * last_price, 4),
                "unrealized_pnl": round(unrealized, 4),
                "target_weight": latest_targets.get(symbol, 0.0),
            }
        )
    return rows


def _rebalance_intents(
    target_pos: pd.DataFrame,
    data_map: dict[str, pd.DataFrame],
    last_ts: pd.Timestamp,
    engine: PaperChinaAEngine,
) -> list[dict[str, Any]]:
    if target_pos.empty:
        return []
    latest = target_pos.iloc[-1].fillna(0.0)
    previous = target_pos.iloc[-2].fillna(0.0) if len(target_pos) > 1 else latest * 0.0
    equity = engine.equity_snapshots[-1].equity if engine.equity_snapshots else engine.initial_capital
    intents: list[dict[str, Any]] = []
    for symbol in target_pos.columns:
        old = float(previous.get(symbol, 0.0))
        new = float(latest.get(symbol, 0.0))
        delta = new - old
        if abs(delta) <= 1e-9:
            continue
        price = _last_close(data_map, symbol, last_ts)
        raw_qty = abs(delta) * equity / price if price and price > 0 else 0.0
        qty = engine.round_size(raw_qty, price or 0.0) if raw_qty else 0.0
        intents.append(
            {
                "symbol": symbol,
                "side": "buy" if delta > 0 else "sell",
                "previous_weight": round(old, 8),
                "target_weight": round(new, 8),
                "weight_delta": round(delta, 8),
                "reference_price": round(price, 4) if price else None,
                "estimated_qty": qty,
                "simulated_only": True,
            }
        )
    return intents


def _last_close(data_map: dict[str, pd.DataFrame], symbol: str, last_ts: pd.Timestamp) -> float | None:
    frame = data_map.get(symbol)
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    eligible = frame.loc[frame.index <= last_ts]
    if eligible.empty:
        return None
    return float(eligible["close"].iloc[-1])
