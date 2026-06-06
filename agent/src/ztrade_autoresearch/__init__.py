"""ztrade Auto Research adapter for Vibe-Trading.

This package keeps the ztrade research loop intentionally narrow:
the agent may propose candidate strategy parameters/code, while the
protocol, evaluator, data windows, and backtest harness stay fixed.
"""

from src.ztrade_autoresearch.candidate_strategy import ZTradeV47SignalEngine
from src.ztrade_autoresearch.evaluator import GateVerdict, MetricRow, evaluate_candidate
from src.ztrade_autoresearch.paper_sim import run_ztrade_paper_sim
from src.ztrade_autoresearch.research_loop import initialize_karpathy_workspace
from src.ztrade_autoresearch.runner import run_synthetic_research, run_ztrade_csv_research

__all__ = [
    "GateVerdict",
    "MetricRow",
    "ZTradeV47SignalEngine",
    "evaluate_candidate",
    "initialize_karpathy_workspace",
    "run_ztrade_paper_sim",
    "run_synthetic_research",
    "run_ztrade_csv_research",
]
