"""Live trading loop — fetch → signal → order → write status.

Usage:
    python -m trader.loop \\
        --strategy-id btc_s1_funding_carry \\
        --testnet-id  btc_s1_funding_carry_testnet \\
        --run-dir     /repo/runs/btc_s1_funding_carry_oos \\
        --symbol      BTC/USDT:USDT \\
        --interval    1H \\
        --lookback    200 \\
        --repo-root   /repo

Writes to:
    <repo_root>/runs/testnet/<testnet_id>/testnet_status.json
    <repo_root>/runs/testnet/<testnet_id>/trades.csv
    <repo_root>/runs/testnet/<testnet_id>/equity.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import signal as _signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("trader.loop")

# ── Interval → sleep seconds mapping ─────────────────────────────────────────

_INTERVAL_SLEEP: dict[str, int] = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "30m": 1800,
    "1H":  3600,
    "4H":  14400,
    "1D":  86400,
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _write_status(
    out_dir: Path,
    strategy_id: str,
    testnet_id: str,
    symbol: str,
    live_status: str,
    equity: Optional[float],
    open_positions: int,
    trades: int,
    sharpe: Optional[float],
    max_drawdown: Optional[float],
    ks_triggered: bool,
    ks_triggered_at: Optional[str],
    ks_reason: Optional[str],
    pause_dd: float,
    terminate_dd: float,
    alerts: list,
    started_at: str,
) -> None:
    status = {
        "schema_version": 1,
        "testnet_id": testnet_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "live": {
            "started_at": started_at,
            "updated_at": _now_iso(),
            "status": live_status,
            "equity": equity,
            "open_positions": open_positions,
            "trades": trades,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
        },
        "vs_backtest": None,
        "killswitch": {
            "triggered": ks_triggered,
            "triggered_at": ks_triggered_at,
            "reason": ks_reason,
            "pause_drawdown": pause_dd,
            "terminate_drawdown": terminate_dd,
        },
        "alerts": alerts[-50:],  # keep last 50
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "testnet_status.json"
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")


def _append_trade(out_dir: Path, trade: dict) -> None:
    path = out_dir / "trades.csv"
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "side", "qty", "price"])
        if write_header:
            w.writeheader()
        w.writerow(trade)


def _append_equity(out_dir: Path, ts: str, equity: float) -> None:
    path = out_dir / "equity.csv"
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "equity"])
        if write_header:
            w.writeheader()
        w.writerow({"timestamp": ts, "equity": equity})


def _signal_to_side(sig: int) -> Optional[str]:
    """Convert signal int to order side. Returns None if flat (0)."""
    if sig == 1:
        return "buy"
    if sig == -1:
        return "sell"
    return None


def run(args: argparse.Namespace) -> None:
    from trader.broker import Broker
    from trader.killswitch import KillSwitch
    from trader.signal import compute_signal

    strategy_id: str = args.strategy_id
    testnet_id: str = args.testnet_id
    run_dir = Path(args.run_dir)
    symbol: str = args.symbol
    interval: str = args.interval
    lookback: int = args.lookback
    repo_root = Path(args.repo_root)
    qty: float = args.qty

    out_dir = repo_root / "runs" / "testnet" / testnet_id
    sleep_secs = _INTERVAL_SLEEP.get(interval, 3600)
    started_at = _now_iso()

    logger.info("Starting trader: strategy=%s testnet_id=%s symbol=%s interval=%s",
                strategy_id, testnet_id, symbol, interval)

    broker = Broker()
    initial_equity = broker.get_equity()
    ks = KillSwitch(initial_equity, pause_dd=0.05, terminate_dd=0.07)

    live_status = "running"
    ks_triggered = False
    ks_triggered_at: Optional[str] = None
    ks_reason: Optional[str] = None
    trade_count = 0
    alerts: list = []
    current_signal = 0

    # Graceful shutdown on SIGTERM / SIGINT
    _shutdown = {"flag": False}

    def _handle_sig(signum, frame):
        logger.info("Received signal %s — shutting down", signum)
        _shutdown["flag"] = True

    _signal.signal(_signal.SIGTERM, _handle_sig)
    _signal.signal(_signal.SIGINT, _handle_sig)

    while not _shutdown["flag"]:
        try:
            # ── Fetch equity & check kill switch ─────────────────────────────
            equity = broker.get_equity()
            decision, reason = ks.check(equity)
            max_dd = ks.current_drawdown(equity)

            if decision == "terminate" and not ks_triggered:
                ks_triggered = True
                ks_triggered_at = _now_iso()
                ks_reason = reason
                live_status = "stopped"
                alerts.append({
                    "timestamp": _now_iso(),
                    "severity": "critical",
                    "message": f"Kill switch terminated: {reason}",
                })
                # Close all positions
                try:
                    broker.close_position(symbol)
                except Exception as e:
                    logger.warning("Failed to close position on terminate: %s", e)
                logger.warning("Kill switch TERMINATE: %s", reason)
                _write_status(
                    out_dir, strategy_id, testnet_id, symbol, live_status,
                    equity, 0, trade_count, None, max_dd,
                    ks_triggered, ks_triggered_at, ks_reason, 0.05, 0.07,
                    alerts, started_at,
                )
                break

            if decision == "pause":
                if live_status == "running":
                    live_status = "paused"
                    alerts.append({
                        "timestamp": _now_iso(),
                        "severity": "warning",
                        "message": f"Kill switch paused: {reason}",
                    })
                    logger.warning("Kill switch PAUSE: %s", reason)

            # ── Compute signal ────────────────────────────────────────────────
            if live_status == "running":
                new_signal = compute_signal(
                    run_dir, broker.exchange, symbol, interval, lookback
                )

                # ── Execute signal ────────────────────────────────────────────
                if new_signal != current_signal:
                    pos = broker.get_position(symbol)

                    # Close existing position if changing direction or going flat
                    if pos is not None:
                        try:
                            close_order = broker.close_position(symbol)
                            if close_order:
                                trade_count += 1
                                _append_trade(out_dir, {
                                    "timestamp": _now_iso(),
                                    "symbol": symbol,
                                    "side": "sell" if pos["side"] == "long" else "buy",
                                    "qty": pos["size"],
                                    "price": close_order.get("average") or 0,
                                })
                        except Exception as e:
                            logger.error("Failed to close position: %s", e)

                    # Open new position
                    new_side = _signal_to_side(new_signal)
                    if new_side is not None:
                        try:
                            order = broker.place_market_order(symbol, new_side, qty)
                            trade_count += 1
                            _append_trade(out_dir, {
                                "timestamp": _now_iso(),
                                "symbol": symbol,
                                "side": new_side,
                                "qty": qty,
                                "price": order.get("average") or 0,
                            })
                        except Exception as e:
                            logger.error("Failed to place order: %s", e)
                            alerts.append({
                                "timestamp": _now_iso(),
                                "severity": "warning",
                                "message": f"Order failed: {e}",
                            })

                    current_signal = new_signal

            # ── Write status & equity snapshot ────────────────────────────────
            pos = broker.get_position(symbol)
            open_positions = 1 if pos else 0
            ts = _now_iso()
            _append_equity(out_dir, ts, equity)
            _write_status(
                out_dir, strategy_id, testnet_id, symbol, live_status,
                equity, open_positions, trade_count, None, max_dd,
                ks_triggered, ks_triggered_at, ks_reason, 0.05, 0.07,
                alerts, started_at,
            )

        except Exception as e:
            logger.error("Loop error: %s", e, exc_info=True)
            alerts.append({
                "timestamp": _now_iso(),
                "severity": "warning",
                "message": f"Loop error: {e}",
            })

        # ── Sleep until next bar ──────────────────────────────────────────────
        elapsed = 0
        while elapsed < sleep_secs and not _shutdown["flag"]:
            time.sleep(min(5, sleep_secs - elapsed))
            elapsed += 5

    # Final stopped status
    live_status = "stopped"
    try:
        equity = broker.get_equity()
    except Exception:
        equity = None
    _write_status(
        out_dir, strategy_id, testnet_id, symbol, live_status,
        equity, 0, trade_count, None, None,
        ks_triggered, ks_triggered_at, ks_reason, 0.05, 0.07,
        alerts, started_at,
    )
    logger.info("Trader stopped. strategy=%s", strategy_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vibe-Trading testnet trader loop")
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--testnet-id", required=True)
    parser.add_argument("--run-dir", required=True, help="Path to backtest run dir with code/signal_engine.py")
    parser.add_argument("--symbol", required=True, help="ccxt symbol, e.g. BTC/USDT:USDT")
    parser.add_argument("--interval", default="1H")
    parser.add_argument("--lookback", type=int, default=200)
    parser.add_argument("--repo-root", default="/repo")
    parser.add_argument("--qty", type=float, default=0.001, help="Order size in base asset")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
