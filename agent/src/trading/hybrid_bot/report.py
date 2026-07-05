# agent/src/trading/hybrid_bot/report.py
import json
from agent.src.trading.hybrid_bot.runner import (
    get_history,
    get_wallet,
    get_positions,
    get_settings,
    REJECTED_FILE,
)

def build_report() -> dict:
    """Performance snapshot from trade history + rejected-signal log."""
    history = get_history()
    wallet = get_wallet()
    wins = [t for t in history if t.get("net_pnl_usd", 0) > 0]
    losses = [t for t in history if t.get("net_pnl_usd", 0) <= 0]
    gross_win = sum(t["net_pnl_usd"] for t in wins)
    gross_loss = -sum(t["net_pnl_usd"] for t in losses)

    def bucket(trades: list) -> dict:
        return {"count": len(trades), "net_usd": round(sum(t.get("net_pnl_usd", 0) for t in trades), 2)}

    by_quality = {}
    for q in ("strong", "marginal"):
        qt = [t for t in history if t.get("quality") == q]
        if qt:
            by_quality[q] = bucket(qt)

    rejected = []
    if REJECTED_FILE.exists():
        try:
            rejected = json.loads(REJECTED_FILE.read_text())
        except Exception:
            pass
    rej_by_class = {}
    for r in rejected:
        cls = r.get("reason_class", "?")
        rej_by_class[cls] = rej_by_class.get(cls, 0) + 1

    return {
        "closed_trades": len(history),
        "win_rate_pct": round(len(wins) / len(history) * 100, 1) if history else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "realized_net_usd": round(sum(t.get("net_pnl_usd", 0) for t in history), 2),
        "balance": wallet.get("balance"),
        "initial_balance": wallet.get("initial_balance"),
        "by_side": {
            "LONG": bucket([t for t in history if t.get("side") == "LONG"]),
            "SHORT": bucket([t for t in history if t.get("side") == "SHORT"]),
        },
        "by_quality": by_quality,
        "biggest_win_usd": max((t.get("net_pnl_usd", 0) for t in history), default=0.0),
        "biggest_loss_usd": min((t.get("net_pnl_usd", 0) for t in history), default=0.0),
        "rejected_by_class": rej_by_class,
        "open_positions": len(get_positions()),
        "settings": get_settings(),
    }
