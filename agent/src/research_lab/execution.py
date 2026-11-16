"""Run ordinary engine trials against one immutable, exported input snapshot."""

from __future__ import annotations

import ast
import hashlib
import json
import io
import os
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from src.config.paths import get_runs_dir
from src.core.runner import Runner
from src.tools.backtest_tool import _backtest_timeout_seconds
from src.tools.path_utils import safe_run_dir


def digest(path: Path) -> str:
    """Hash a file's exact bytes."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def source_run(value: str) -> Path:
    """Resolve a run identifier or an explicitly allowed run directory."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = get_runs_dir() / path
    return safe_run_dir(str(path))


def constructor_defaults(source: str) -> dict[str, Any]:
    """Inspect literal constructor defaults without importing generated code."""
    tree = ast.parse(source)
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or cls.name != "SignalEngine":
            continue
        for method in cls.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                defaults = {}
                args = method.args.posonlyargs + method.args.args
                pairs = list(zip(args[-len(method.args.defaults) :], method.args.defaults))
                pairs.extend(zip(method.args.kwonlyargs, method.args.kw_defaults))
                for arg, node in pairs:
                    try:
                        value = ast.literal_eval(node)
                    except (ValueError, TypeError):
                        continue
                    if value is None or isinstance(value, (str, bool, int, float)):
                        defaults[arg.arg] = value
                return defaults
    return {}


def freeze_run(run: Path, destination: Path) -> tuple[dict, Path, pd.DatetimeIndex, str]:
    """Copy verified engine inputs and strategy, retaining every exported field.

    Args:
        run: Completed source run.
        destination: New experiment root.

    Returns:
        Original config, sealed data manifest, union calendar and strategy hash.

    Raises:
        ValueError: If inputs are incomplete, changed or cannot be reproduced.
    """
    for relative in ("config.json", "run_card.json", "code/signal_engine.py"):
        if not (run / relative).resolve().is_relative_to(run.resolve()):
            raise ValueError(f"source file escapes its run: {relative}")
    config_bytes = (run / "config.json").read_bytes()
    config = json.loads(config_bytes)
    card = json.loads((run / "run_card.json").read_text())
    entries = {row["path"]: row for row in card.get("artifacts", [])}
    config_hash = hashlib.sha256(config_bytes).hexdigest()
    if entries.get("config.json", {}).get("sha256") != config_hash:
        raise ValueError("source configuration changed since its completed backtest; rerun it before studying it")
    code = run / "code/signal_engine.py"
    from backtest.runner import _validate_signal_engine_source

    _validate_signal_engine_source(code)
    wanted = [symbol.removeprefix("local:") for symbol in config["codes"]]
    if not wanted or len(wanted) != len(set(wanted)):
        raise ValueError("source run must declare distinct instrument codes")
    frames = {}
    calendar = None
    snapshot = destination / "snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(config_bytes)
    for index, symbol in enumerate(wanted):
        relative = f"artifacts/ohlcv_{symbol}.csv"
        path = (run / relative).resolve()
        if not path.is_relative_to(run.resolve()) or relative not in entries:
            raise ValueError(f"source run has no manifested price snapshot for {symbol}; rerun its backtest")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entries[relative]["sha256"]:
            raise ValueError(f"source price snapshot changed: {symbol}")
        frame = pd.read_csv(io.BytesIO(raw), index_col=0, parse_dates=True)
        if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_unique:
            raise ValueError(f"price snapshot has an invalid calendar: {symbol}")
        frame = frame.sort_index()
        if calendar is None:
            calendar = frame.index
        else:
            calendar = calendar.union(frame.index)
        filename = f"frame-{index}.csv"
        (snapshot / filename).write_bytes(raw)
        frames[symbol] = {"path": filename, "sha256": digest(snapshot / filename), "rows": len(frame)}
    strategy_entry = entries.get("code/signal_engine.py")
    strategy_bytes = code.read_bytes()
    strategy_hash = hashlib.sha256(strategy_bytes).hexdigest()
    if strategy_entry is None or strategy_hash != strategy_entry["sha256"]:
        raise ValueError("source strategy changed since its completed backtest; rerun it before studying it")
    (snapshot / "signal_engine.py").write_bytes(strategy_bytes)
    manifest = {
        "schema_version": 1,
        "interval": config.get("interval", "1D"),
        "frames": frames,
        "sources": card.get("data_sources", [config.get("source", "auto")]),
        "source_run": run.name,
        "strategy_sha256": strategy_hash,
        "config_sha256": config_hash,
    }
    manifest_path = snapshot / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
    if calendar is None or len(calendar) < 2:
        raise ValueError("snapshot needs at least two trading bars")
    return config, manifest_path, calendar.sort_values(), strategy_hash


def trial(study: Path, name: str, config: dict, manifest: Path, *, parameters: dict | None = None) -> dict:
    """Execute a real sandboxed engine trial and return persisted measurements."""
    root = study / "trials" / name
    root.mkdir(parents=True)
    (root / "code").mkdir()
    (root / "code/signal_engine.py").write_bytes((manifest.parent / "signal_engine.py").read_bytes())
    settings = dict(config)
    # These are experiments, not evidence writes for the parent's registered
    # strategy. Keep the engine itself and all execution rules unchanged.
    for key in ("artifact_id", "strategy_adaptation", "validation"):
        settings.pop(key, None)
    settings["codes"] = [code.removeprefix("local:") for code in settings["codes"]]
    # The trial-local files must obey the same cutoff as data_map. Otherwise
    # a strategy loading its own snapshot could accidentally see future bars
    # even though the normal loader returns a correctly truncated frame.
    local_snapshot = root / "snapshot"
    local_snapshot.mkdir()
    parent_bytes = manifest.read_bytes()
    parent_hash = hashlib.sha256(parent_bytes).hexdigest()
    parent_snapshot = json.loads(parent_bytes)
    frozen = json.loads(parent_bytes)
    for entry in frozen["frames"].values():
        source = manifest.parent / entry["path"]
        target = local_snapshot / entry["path"]
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("sealed prices changed before trial execution")
        frame = pd.read_csv(io.BytesIO(raw), index_col=0, parse_dates=True)
        visible = frame.loc[settings["start_date"] : settings["end_date"]]
        if len(visible) == len(frame):
            try:
                os.link(source, target)
            except OSError:
                shutil.copyfile(source, target)
        else:
            visible.to_csv(target)
        entry.update(sha256=digest(target), rows=len(visible))
    frozen["parent_manifest_sha256"] = parent_hash
    frozen["visible_window"] = {key: settings[key] for key in ("start_date", "end_date")}
    local_manifest = local_snapshot / "manifest.json"
    local_manifest.write_text(json.dumps(frozen, ensure_ascii=False, allow_nan=False))
    settings["frozen_data_manifest"] = str(local_manifest)
    if parameters is not None:
        settings["signal_parameters"] = {**settings.get("signal_parameters", {}), **parameters}
    (root / "config.json").write_text(json.dumps(settings, indent=2, allow_nan=False))
    agent = Path(__file__).resolve().parents[2]
    process = Runner(timeout=_backtest_timeout_seconds()).execute(
        agent / "backtest/runner.py",
        root,
        cwd=agent,
        cli_args=[str(root)],
    )
    if not process.success:
        raise ValueError(f"trial {name} failed; inspect its logs in {root}")
    if digest(manifest) != parent_hash or digest(manifest.parent / "signal_engine.py") != parent_snapshot["strategy_sha256"]:
        raise ValueError("sealed manifest or strategy changed during trial execution")
    for entry in parent_snapshot["frames"].values():
        if digest(manifest.parent / entry["path"]) != entry["sha256"]:
            raise ValueError("sealed prices changed during trial execution")
    card = json.loads((root / "run_card.json").read_text())
    equity = pd.read_csv(root / "artifacts/equity.csv", index_col=0, parse_dates=True)
    raw_metrics = pd.read_csv(root / "artifacts/metrics.csv").iloc[0]
    metrics = {
        name: float(raw_metrics[name])
        for name in (
            "final_value",
            "total_return",
            "annual_return",
            "max_drawdown",
            "sharpe",
            "trade_count",
            "total_turnover",
        )
        if name in raw_metrics and pd.notna(raw_metrics[name])
    }
    if not metrics:
        raise ValueError(f"trial {name} produced no structured metrics")
    return {
        "run_dir": str(root),
        "metrics": metrics,
        "equity": equity,
        "benchmark": card.get("benchmark"),
        "config": settings,
    }
