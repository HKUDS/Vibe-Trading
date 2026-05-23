"""Trader process supervisor — start/stop one trader process per strategy.

The supervisor is a singleton instantiated at server startup. Each running
trader is a subprocess running ``python -m trader.loop``.

Environment variables forwarded to the subprocess:
  BYBIT_API_KEY
  BYBIT_API_SECRET
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class TraderProcess:
    strategy_id: str
    testnet_id: str
    proc: subprocess.Popen
    run_dir: str
    symbol: str
    interval: str


class Supervisor:
    """Manages one subprocess per promoted strategy."""

    def __init__(self, repo_root: Path, dashboard_dir: Path) -> None:
        self.repo_root = repo_root
        self.dashboard_dir = dashboard_dir
        self._procs: Dict[str, TraderProcess] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def start(
        self,
        strategy_id: str,
        testnet_id: str,
        run_dir: str,
        symbol: str,
        interval: str = "1H",
        qty: float = 0.001,
    ) -> None:
        """Launch a trader subprocess for *strategy_id*.

        Does nothing if already running.
        """
        if self.is_running(strategy_id):
            logger.info("Trader for %s already running", strategy_id)
            return

        env = {**os.environ}
        # Ensure BYBIT_* credentials are forwarded
        for key in ("BYBIT_API_KEY", "BYBIT_API_SECRET"):
            if key not in env:
                raise EnvironmentError(f"{key} not set — cannot start trader")

        # trader/ package lives next to server/ inside dashboard/
        trader_pkg_dir = self.dashboard_dir.parent / "trader"
        if not trader_pkg_dir.exists():
            raise FileNotFoundError(f"trader package not found at {trader_pkg_dir}")

        # Run from dashboard/ so relative imports work
        cmd = [
            sys.executable, "-m", "trader.loop",
            "--strategy-id", strategy_id,
            "--testnet-id", testnet_id,
            "--run-dir", run_dir,
            "--symbol", symbol,
            "--interval", interval,
            "--repo-root", str(self.repo_root),
            "--qty", str(qty),
        ]

        # Add dashboard/ parent so ``trader`` package is importable
        python_path = str(self.dashboard_dir.parent)
        env["PYTHONPATH"] = python_path + os.pathsep + env.get("PYTHONPATH", "")

        logger.info("Starting trader subprocess: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._procs[strategy_id] = TraderProcess(
            strategy_id=strategy_id,
            testnet_id=testnet_id,
            proc=proc,
            run_dir=run_dir,
            symbol=symbol,
            interval=interval,
        )
        logger.info("Trader for %s started (pid %s)", strategy_id, proc.pid)

    def stop(self, strategy_id: str) -> bool:
        """Send SIGTERM to the trader subprocess.

        Returns True if a process was running and was stopped.
        """
        tp = self._procs.get(strategy_id)
        if tp is None:
            return False
        if tp.proc.poll() is not None:
            del self._procs[strategy_id]
            return False

        tp.proc.terminate()
        try:
            tp.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tp.proc.kill()
        del self._procs[strategy_id]
        logger.info("Trader for %s stopped", strategy_id)
        return True

    def is_running(self, strategy_id: str) -> bool:
        tp = self._procs.get(strategy_id)
        if tp is None:
            return False
        if tp.proc.poll() is not None:
            del self._procs[strategy_id]
            return False
        return True

    def status(self, strategy_id: str) -> dict:
        running = self.is_running(strategy_id)
        tp = self._procs.get(strategy_id)
        return {
            "running": running,
            "pid": tp.proc.pid if running and tp else None,
            "testnet_id": tp.testnet_id if running and tp else None,
        }

    def stop_all(self) -> None:
        for sid in list(self._procs.keys()):
            self.stop(sid)


# Module-level singleton — populated by main.py on startup
_supervisor: Optional[Supervisor] = None


def get_supervisor() -> Supervisor:
    if _supervisor is None:
        raise RuntimeError("Supervisor not initialised — call init_supervisor() first")
    return _supervisor


def init_supervisor(repo_root: Path, dashboard_dir: Path) -> Supervisor:
    global _supervisor
    _supervisor = Supervisor(repo_root, dashboard_dir)
    return _supervisor
