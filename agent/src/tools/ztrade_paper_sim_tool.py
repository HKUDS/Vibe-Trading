"""Tool wrapper for ztrade local paper simulation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.ztrade_autoresearch.paper_sim import default_params_path, run_ztrade_paper_sim


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_repo_path(raw: str | None) -> Path:
    root = _repo_root().resolve()
    candidate = Path(raw).expanduser() if raw else default_params_path()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("params_path must stay inside the repository")
    return resolved


class ZTradePaperSimTool(BaseTool):
    """Run the current ztrade V47 strategy as a broker-free paper account."""

    name = "ztrade_paper_sim"
    description = (
        "Promote a ztrade autoresearch V47 params file into a local paper-trading "
        "run_dir and replay it without connecting to a broker or placing orders."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Output run directory under an allowed runs root."},
            "params_path": {
                "type": "string",
                "description": "Repository-local params JSON. Default: autoresearch/best/v47_params.json.",
            },
            "mode": {
                "type": "string",
                "enum": ["ztrade_csv", "synthetic"],
                "description": "Data mode. ztrade_csv uses local ztrade CSV history; synthetic is offline smoke.",
            },
            "data_dir": {"type": "string", "description": "Local ztrade CSV data directory for mode=ztrade_csv."},
            "codes": {"type": "array", "items": {"type": "string"}},
            "window_start": {"type": "string", "description": "Paper replay window start date."},
            "window_end": {"type": "string", "description": "Paper replay window end date."},
            "max_symbols": {"type": "integer", "description": "Max CSV symbols when codes is omitted."},
            "initial_cash": {"type": "number", "description": "Starting cash for the simulated account."},
        },
        "required": ["run_dir"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            params_path = _resolve_repo_path(kwargs.get("params_path"))
            state = run_ztrade_paper_sim(
                kwargs["run_dir"],
                params_path=params_path,
                mode=str(kwargs.get("mode", "ztrade_csv")),
                data_dir=kwargs.get("data_dir"),
                codes=kwargs.get("codes"),
                window_start=str(kwargs.get("window_start", "2023-12-28")),
                window_end=str(kwargs.get("window_end", "2026-05-27")),
                max_symbols=int(kwargs.get("max_symbols", 200)),
                initial_cash=float(kwargs.get("initial_cash", 1_000_000.0)),
            )
        except Exception as exc:  # noqa: BLE001 - tools must return JSON errors
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps(state, ensure_ascii=False, default=str)
