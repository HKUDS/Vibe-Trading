"""ztrade autoresearch runner on top of Vibe-Trading backtest primitives."""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.engines.china_a import ChinaAEngine
from src.ztrade_autoresearch.candidate_strategy import ZTradeV47SignalEngine
from src.ztrade_autoresearch.evaluator import MetricRow, evaluate_candidate
from src.ztrade_autoresearch.protocol import (
    BASELINE_ID,
    ROLLING_WINDOWS,
    SEARCH_SPACE,
    ZTRADE_CSV_WINDOWS,
    merged_params,
    protocol_payload,
)


class SyntheticAshareLoader:
    """Deterministic in-memory OHLCV loader for offline smoke backtests."""

    name = "synthetic_ashare"

    def __init__(self, data_map: dict[str, pd.DataFrame]) -> None:
        self._data_map = data_map

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


class ZtradeCsvLoader:
    """Read local ztrade ``data/*.csv`` files through Vibe's loader contract."""

    name = "ztrade_csv"

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        fields: list[str] | None = None,
        interval: str = "1D",
    ) -> dict[str, pd.DataFrame]:
        del fields
        if interval != "1D":
            raise ValueError("ztrade_csv loader only supports 1D bars")
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        result: dict[str, pd.DataFrame] = {}
        for code in codes:
            csv_path = self.data_dir / f"{_bare_code(code)}.csv"
            if not csv_path.exists():
                continue
            frame = pd.read_csv(csv_path)
            if frame.empty or "date" not in frame.columns:
                continue
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
            if frame.empty:
                continue
            frame = frame.set_index("date").sort_index()
            if "volume" not in frame.columns and "vol" in frame.columns:
                frame["volume"] = frame["vol"]
            for col in ("open", "high", "low", "close", "volume"):
                if col not in frame.columns:
                    raise ValueError(f"{csv_path} missing required column: {col}")
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
            frame = frame[["open", "high", "low", "close", "volume"]].dropna(
                subset=["open", "high", "low", "close"]
            )
            if frame.empty:
                continue
            frame["pre_close"] = frame["close"].shift(1).fillna(frame["close"])
            frame["pct_chg"] = (frame["close"] / frame["pre_close"].replace(0.0, np.nan) - 1.0) * 100.0
            result[code] = frame
        return result


def run_synthetic_research(
    run_dir: str | Path,
    *,
    max_iterations: int = 4,
) -> dict[str, Any]:
    """Run a bounded ztrade autoresearch smoke loop.

    This is intentionally offline and deterministic. It proves the Vibe
    scaffolding, run-card generation, fixed evaluator, and candidate strategy
    rendering work before connecting live Tushare data.
    """
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    candidates = SEARCH_SPACE[: max(1, max_iterations + 1)]
    rows: list[MetricRow] = []
    experiment_records: list[dict[str, Any]] = []

    (root / "protocol.json").write_text(
        json.dumps(protocol_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for candidate in candidates:
        candidate_id = str(candidate["id"])
        params = merged_params(candidate.get("params", {}))
        for window in ROLLING_WINDOWS:
            row = _run_one_window(root, candidate_id, str(candidate["role"]), params, window)
            rows.append(row)
        if candidate_id != BASELINE_ID:
            verdict = evaluate_candidate(rows, baseline_id=BASELINE_ID, candidate_id=candidate_id)
            experiment_records.append(
                {
                    "candidate_id": candidate_id,
                    "role": candidate["role"],
                    "rationale": candidate.get("rationale", ""),
                    "params": params,
                    "verdict": verdict.verdict,
                    "score": verdict.score,
                    "gates": verdict.gates,
                    "reasons": verdict.reasons,
                    "diagnostics": verdict.diagnostics,
                }
            )

    best = _best_candidate(experiment_records)
    summary = {
        "status": "ok",
        "mode": "synthetic_smoke",
        "run_dir": str(root),
        "baseline_id": BASELINE_ID,
        "rows": [asdict(row) for row in rows],
        "iterations": experiment_records,
        "best_candidate": best,
    }
    (root / "metrics_rows.json").write_text(
        json.dumps(summary["rows"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "experiments.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in experiment_records),
        encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def run_ztrade_csv_research(
    run_dir: str | Path,
    *,
    data_dir: str | Path,
    max_iterations: int = 4,
    max_symbols: int = 50,
    windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the V47 autoresearch loop against local ztrade CSV history."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    loader = ZtradeCsvLoader(data_dir)
    candidate_defs = SEARCH_SPACE[: max(1, max_iterations + 1)]
    active_windows = windows or ZTRADE_CSV_WINDOWS
    rows: list[MetricRow] = []
    experiment_records: list[dict[str, Any]] = []
    universe_by_window: dict[str, list[str]] = {}

    protocol = protocol_payload()
    protocol["mode"] = "ztrade_csv"
    protocol["data_dir"] = str(Path(data_dir))
    protocol["max_symbols"] = max_symbols
    (root / "protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for window in active_windows:
        universe = discover_ztrade_csv_universe(
            data_dir,
            start_date=str(window["start"]),
            end_date=str(window["end"]),
            max_symbols=max_symbols,
        )
        if not universe:
            raise ValueError(f"no ztrade CSV universe for window {window['id']}")
        universe_by_window[str(window["id"])] = universe

    for candidate in candidate_defs:
        candidate_id = str(candidate["id"])
        params = merged_params(candidate.get("params", {}))
        for window in active_windows:
            row = _run_one_csv_window(
                root,
                candidate_id,
                str(candidate["role"]),
                params,
                window,
                loader,
                universe_by_window[str(window["id"])],
            )
            rows.append(row)
        if candidate_id != BASELINE_ID:
            verdict = evaluate_candidate(rows, baseline_id=BASELINE_ID, candidate_id=candidate_id)
            experiment_records.append(
                {
                    "candidate_id": candidate_id,
                    "role": candidate["role"],
                    "rationale": candidate.get("rationale", ""),
                    "params": params,
                    "verdict": verdict.verdict,
                    "score": verdict.score,
                    "gates": verdict.gates,
                    "reasons": verdict.reasons,
                    "diagnostics": verdict.diagnostics,
                }
            )

    best = _best_candidate(experiment_records)
    summary = {
        "status": "ok",
        "mode": "ztrade_csv",
        "run_dir": str(root),
        "data_dir": str(Path(data_dir)),
        "baseline_id": BASELINE_ID,
        "max_symbols": max_symbols,
        "universe_by_window": universe_by_window,
        "rows": [asdict(row) for row in rows],
        "iterations": experiment_records,
        "best_candidate": best,
    }
    (root / "metrics_rows.json").write_text(
        json.dumps(summary["rows"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "experiments.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in experiment_records),
        encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def discover_ztrade_csv_universe(
    data_dir: str | Path,
    *,
    start_date: str,
    end_date: str,
    max_symbols: int = 50,
    min_rows: int = 8,
) -> list[str]:
    """Select liquid, covered symbols from ztrade local CSV files."""
    root = Path(data_dir)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    scores: list[tuple[float, str]] = []
    for csv_path in root.glob("*.csv"):
        bare = csv_path.stem
        if len(bare) != 6 or not bare.isdigit():
            continue
        try:
            frame = pd.read_csv(csv_path, usecols=["date", "close", "volume"])
        except ValueError:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
        if len(frame) < min_rows:
            continue
        close = pd.to_numeric(frame["close"], errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        amount_proxy = (close * volume).dropna()
        if amount_proxy.empty:
            continue
        scores.append((float(amount_proxy.mean()), _vibe_code(bare)))
    scores.sort(reverse=True)
    return [code for _, code in scores[:max_symbols]]


def _run_one_window(
    root: Path,
    candidate_id: str,
    role: str,
    params: dict[str, Any],
    window: dict[str, Any],
) -> MetricRow:
    window_id = str(window["id"])
    run_path = root / candidate_id / window_id
    code_dir = run_path / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    _write_signal_engine(code_dir / "signal_engine.py", params)

    data_map = _synthetic_data_map(
        seed=int(window["seed"]),
        start=str(window["start"]),
        periods=int(window["periods"]),
        regime=str(window["regime"]),
    )
    codes = list(data_map)
    config = {
        "codes": codes,
        "start_date": str(window["start"]),
        "end_date": str(data_map[codes[0]].index[-1].date()),
        "source": "tushare",
        "engine": "daily",
        "interval": "1D",
        "initial_cash": 1_000_000,
        "commission_rate": 0.00025,
        "commission_min": 5.0,
        "stamp_tax": 0.0005,
        "transfer_fee": 0.00001,
        "slippage": 0.001,
        "validation": {"walk_forward": {"n_windows": 3}},
    }
    (run_path / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_path / "artifacts").mkdir(parents=True, exist_ok=True)

    engine = ChinaAEngine(config)
    with redirect_stdout(io.StringIO()):
        metrics = engine.run_backtest(
            config,
            SyntheticAshareLoader(data_map),
            ZTradeV47SignalEngine(**params),
            run_path,
            bars_per_year=252,
        )
    return MetricRow(
        candidate_id=candidate_id,
        window_id=window_id,
        role=role,
        return_pct=round(float(metrics["total_return"]) * 100.0, 6),
        max_drawdown_pct=round(abs(float(metrics["max_drawdown"])) * 100.0, 6),
        trade_count=int(metrics["trade_count"]),
        win_rate=round(float(metrics["win_rate"]), 6),
        regime=str(window["regime"]),
    )


def _run_one_csv_window(
    root: Path,
    candidate_id: str,
    role: str,
    params: dict[str, Any],
    window: dict[str, Any],
    loader: ZtradeCsvLoader,
    codes: list[str],
) -> MetricRow:
    window_id = str(window["id"])
    run_path = root / candidate_id / window_id
    code_dir = run_path / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    _write_signal_engine(code_dir / "signal_engine.py", params)
    warmup_start = _warmup_start(str(window["start"]))

    config = {
        "codes": codes,
        "start_date": warmup_start,
        "end_date": str(window["end"]),
        "research_window_start": str(window["start"]),
        "research_window_end": str(window["end"]),
        "source": "ztrade_csv",
        "engine": "daily",
        "interval": "1D",
        "initial_cash": 1_000_000,
        "commission_rate": 0.00025,
        "commission_min": 5.0,
        "stamp_tax": 0.0005,
        "transfer_fee": 0.00001,
        "slippage": 0.001,
        "_run_card_effective_sources": ["ztrade_csv"],
    }
    (run_path / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_path / "artifacts").mkdir(parents=True, exist_ok=True)

    engine = ChinaAEngine(config)
    with redirect_stdout(io.StringIO()):
        metrics = engine.run_backtest(
            config,
            loader,
            ZTradeV47SignalEngine(**params, active_start_date=str(window["start"])),
            run_path,
            bars_per_year=252,
        )
    return MetricRow(
        candidate_id=candidate_id,
        window_id=window_id,
        role=role,
        return_pct=round(float(metrics["total_return"]) * 100.0, 6),
        max_drawdown_pct=round(abs(float(metrics["max_drawdown"])) * 100.0, 6),
        trade_count=int(metrics["trade_count"]),
        win_rate=round(float(metrics["win_rate"]), 6),
        regime=str(window["regime"]),
    )


def _write_signal_engine(path: Path, params: dict[str, Any]) -> None:
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True, indent=4)
    path.write_text(
        "\n".join(
            [
                '"""Rendered ztrade autoresearch candidate SignalEngine."""',
                "",
                "from src.ztrade_autoresearch.candidate_strategy import ZTradeV47SignalEngine",
                "",
                f"PARAMS = {payload}",
                "",
                "class SignalEngine(ZTradeV47SignalEngine):",
                "    def __init__(self):",
                "        super().__init__(**PARAMS)",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _synthetic_data_map(seed: int, start: str, periods: int, regime: str) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=periods)
    symbols = ["000001.SZ", "000002.SZ", "600000.SH", "600519.SH", "300750.SZ"]
    data: dict[str, pd.DataFrame] = {}
    for idx, symbol in enumerate(symbols):
        base = 18.0 + idx * 7.0
        drift = {"recovery": 0.06, "chop": 0.015, "drawdown": -0.015, "live_like": 0.035}.get(regime, 0.02)
        cycle = np.sin(np.linspace(0, 5.5 * np.pi, periods) + idx * 0.6) * (0.7 + idx * 0.05)
        noise = rng.normal(0.0, 0.28 + idx * 0.02, periods).cumsum()
        trend = np.linspace(0, drift * periods, periods)
        close = np.maximum(base + trend + cycle + noise, 2.0)
        open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0.0, 0.004, periods))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.002, 0.018, periods))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.002, 0.018, periods))
        volume = rng.integers(800_000, 3_000_000, periods).astype(float)
        reversal_days = np.arange(20 + idx, periods, 23)
        volume[reversal_days] *= 1.8
        pre_close = np.r_[close[0], close[:-1]]
        pct_chg = (close / np.where(pre_close == 0, close, pre_close) - 1.0) * 100.0
        data[symbol] = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "pre_close": pre_close,
                "pct_chg": pct_chg,
            },
            index=dates,
        )
    return data


def _best_candidate(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    keepers = [record for record in records if record.get("verdict") == "KEEP"]
    if not keepers:
        return None
    return max(keepers, key=lambda item: float(item.get("score", 0.0)))


def _bare_code(code: str) -> str:
    return code.split(".", 1)[0]


def _vibe_code(bare: str) -> str:
    if bare.startswith(("6", "9")):
        return f"{bare}.SH"
    if bare.startswith(("8", "4")):
        return f"{bare}.BJ"
    return f"{bare}.SZ"


def _warmup_start(start_date: str, days: int = 180) -> str:
    return str((pd.Timestamp(start_date) - pd.Timedelta(days=days)).date())
