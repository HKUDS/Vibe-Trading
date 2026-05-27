"""Tool wrapper for the ztrade autoresearch adapter."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.ztrade_autoresearch.runner import run_synthetic_research, run_ztrade_csv_research


class ZTradeAutoResearchTool(BaseTool):
    """Run the bounded ztrade autoresearch smoke loop."""

    name = "ztrade_autoresearch"
    description = (
        "Run ztrade Auto Research on Vibe-Trading scaffolding. "
        "This tool uses a fixed evaluator/protocol and an offline synthetic "
        "A-share smoke dataset; it does not place trades or modify live state."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Output directory for research artifacts."},
            "mode": {
                "type": "string",
                "description": "Run mode: synthetic_smoke or ztrade_csv. Default synthetic_smoke.",
            },
            "data_dir": {
                "type": "string",
                "description": "ztrade local CSV data directory, required when mode=ztrade_csv.",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Number of candidate iterations after the baseline, default 4.",
            },
            "max_symbols": {
                "type": "integer",
                "description": "Maximum symbols per ztrade_csv window, default 50.",
            },
            "use_mutable_candidate": {
                "type": "boolean",
                "description": (
                    "When true, evaluate the Karpathy-style workspace candidate "
                    "from autoresearch/mutable/v47_params.json instead of the "
                    "built-in static search-space candidates."
                ),
            },
        },
        "required": ["run_dir"],
    }

    def execute(self, **kwargs: Any) -> str:
        mode = str(kwargs.get("mode", "synthetic_smoke"))
        if mode == "ztrade_csv":
            data_dir = kwargs.get("data_dir")
            if not data_dir:
                raise ValueError("data_dir is required when mode=ztrade_csv")
            summary = run_ztrade_csv_research(
                kwargs["run_dir"],
                data_dir=data_dir,
                max_iterations=int(kwargs.get("max_iterations", 4)),
                max_symbols=int(kwargs.get("max_symbols", 50)),
                use_mutable_candidate=bool(kwargs.get("use_mutable_candidate", False)),
            )
        else:
            summary = run_synthetic_research(
                kwargs["run_dir"],
                max_iterations=int(kwargs.get("max_iterations", 4)),
                use_mutable_candidate=bool(kwargs.get("use_mutable_candidate", False)),
            )
        return json.dumps(summary, ensure_ascii=False)
