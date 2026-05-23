"""Kill switch — drawdown-based auto-pause and auto-terminate."""

from __future__ import annotations

from typing import Literal, Tuple


KillDecision = Literal["ok", "pause", "terminate"]


class KillSwitch:
    """Track peak equity and trigger pause/terminate on drawdown breach.

    Args:
        initial_equity: Starting equity (sets the first peak).
        pause_dd: Drawdown fraction that pauses trading (default 5%).
        terminate_dd: Drawdown fraction that terminates trading (default 7%).
    """

    def __init__(
        self,
        initial_equity: float,
        pause_dd: float = 0.05,
        terminate_dd: float = 0.07,
    ) -> None:
        self.initial_equity = initial_equity
        self.peak_equity = initial_equity
        self.pause_dd = pause_dd
        self.terminate_dd = terminate_dd

    def check(self, current_equity: float) -> Tuple[KillDecision, str | None]:
        """Evaluate current equity against thresholds.

        Updates internal peak. Returns (decision, reason) where decision is:
          "ok"        — continue trading
          "pause"     — drawdown >= pause_dd, stop new orders
          "terminate" — drawdown >= terminate_dd, shut down process

        Args:
            current_equity: Current total equity.

        Returns:
            (decision, reason_string or None)
        """
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        if self.peak_equity <= 0:
            return "ok", None

        dd = (self.peak_equity - current_equity) / self.peak_equity

        if dd >= self.terminate_dd:
            return (
                "terminate",
                f"Drawdown {dd:.2%} reached terminate threshold {self.terminate_dd:.2%}",
            )
        if dd >= self.pause_dd:
            return (
                "pause",
                f"Drawdown {dd:.2%} reached pause threshold {self.pause_dd:.2%}",
            )
        return "ok", None

    def current_drawdown(self, current_equity: float) -> float:
        """Return current drawdown as a positive fraction (0.0 = no DD)."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - current_equity) / self.peak_equity)
