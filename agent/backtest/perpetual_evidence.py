"""Strict USD-M audit evidence, never read back into accounting decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1"
RESOLUTION_LIMITATION = (
    "At 100x, an interval of at most 1 hour is only a resolution boundary; "
    "exact liquidation sequence precision is not guaranteed."
)


def build_perpetual_summary(
    *,
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    trades: Sequence[Any],
    terminal_status: str,
    maintenance_bracket_versions: Mapping[str, str],
    market_risk_sources: Sequence[str],
) -> dict[str, Any]:
    """Build a strict-JSON-safe summary from append-only audit evidence."""
    funding = [event for event in events if event["event_type"] == "funding_settlement"]
    liquidation_types = {"position_liquidation", "account_liquidation"}
    liquidations = [event for event in events if event["event_type"] in liquidation_types]
    flags = sorted({flag for event in events for flag in event.get("fidelity_flags", [])})
    liquidated_positions = sum(len(event.get("symbols", [event.get("symbol")])) for event in liquidations)
    return {
        "schema_version": SCHEMA_VERSION,
        "margin_mode": str(config.get("margin_mode", "isolated")),
        "funding_mode": str(config.get("funding_mode", "fixed")),
        "interval": str(config.get("interval", "1D")),
        "leverage": float(config.get("leverage", 1.0)),
        "taker_rate": float(config.get("taker_rate", 0.0005)),
        "liquidation_fee_rate": float(config.get("liquidation_fee_rate", 0.0)),
        "terminal_status": terminal_status,
        "event_count": len(events),
        "funding_settlement_count": len(funding),
        "total_funding_pnl": sum(float(event["funding_pnl"]) for event in funding),
        "liquidation_event_count": len(liquidations),
        "liquidated_position_count": liquidated_positions,
        "total_trading_fee": sum(float(trade.commission) for trade in trades),
        "total_liquidation_fee": sum(float(event["liquidation_fee"]) for event in liquidations),
        "fee_model": {
            "market_fill_rate": "taker_rate",
            "maker_rate_used": False,
            "funding_separate": True,
            "liquidation_separate": True,
        },
        "maintenance_bracket_versions": dict(sorted(maintenance_bracket_versions.items())),
        "market_risk_sources": sorted(set(market_risk_sources)),
        "fidelity_flags": flags,
        "resolution_limitation": RESOLUTION_LIMITATION,
        "assumptions": [
            "single_asset_usdt",
            "no_open_order_margin",
            "one_way_positions",
            "bar_extrema_order_unknown",
            "not_an_identical_binance_liquidation_engine_reproduction",
        ],
    }


def write_perpetual_evidence(
    run_dir: Path,
    events: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> None:
    """Write ordered lifecycle JSONL and its aggregate summary."""
    out = Path(run_dir) / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    event_lines = [json.dumps(event, sort_keys=True, allow_nan=False) for event in events]
    (out / "perpetual_events.jsonl").write_text(
        "\n".join(event_lines) + ("\n" if event_lines else ""),
        encoding="utf-8",
    )
    (out / "perpetual_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
