"""Compact observations from returned bars, without another read or retained cache."""

from datetime import datetime
import math


def summarize_bars(payload, interval):
    """Summarize existing records without claiming an exchange calendar is complete.

    Args:
        payload: Parsed market-data envelope before artifact delivery.
        interval: Requested case-sensitive bar interval.

    Returns:
        Counts, endpoints, sequence checks and existing provenance per symbol.
        Sampled series are explicitly identified; spacing is not calendar coverage.
    """
    summaries = {}
    seconds = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400}.get(interval)
    for symbol, value in payload.items():
        if symbol.startswith("_"):
            continue
        sampled = isinstance(value, dict) and value.get("truncated") is True
        rows = value.get("data") if isinstance(value, dict) else value
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            continue
        first, last = rows[0], rows[-1]
        def stamp(row):
            return row.get("trade_date", row.get("time"))
        summary = {
            "returned_rows": len(rows), "source_rows": value.get("rows") if sampled else len(rows),
            "sampled": sampled, "first_time": stamp(first), "last_time": stamp(last),
            "first_close": first.get("close"), "last_close": last.get("close"),
            "provenance": payload.get("_provenance", {}).get(symbol, {}),
            "coverage": payload.get("_coverage", {}).get(symbol, {"coverage_verified": False, "reason": "calendar_not_checked_on_this_path"}),
        }
        if not sampled:
            def numeric(value):
                return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

            def aggregate(field, operation):
                if not all(numeric(row.get(field)) for row in rows):
                    return None
                try:
                    result = operation(row[field] for row in rows)
                    return result if numeric(result) else None
                except (OverflowError, ValueError):
                    return None

            opening, closing = first.get("close"), last.get("close")
            change = ((closing / opening - 1) * 100
                      if numeric(opening) and numeric(closing) and opening > 0 else None)
            summary["first_row"] = first
            summary["last_row"] = last
            summary["statistics"] = {
                "high": aggregate("high", max), "low": aggregate("low", min),
                "volume_sum": aggregate("volume", math.fsum),
                "first_to_last_close_change_pct": change if numeric(change) else None,
                "basis": "calculated_from_returned_rows; not_total_return; volume_unit_in_provenance",
            }
        if not sampled and seconds:
            previous = None
            non_increasing = irregular = 0
            parsed = True
            for row in rows:
                try:
                    current = datetime.fromisoformat(str(stamp(row)).replace("Z", "+00:00"))
                    if previous is not None:
                        delta = (current - previous).total_seconds()
                        non_increasing += delta <= 0
                        irregular += delta != seconds
                    previous = current
                except (ValueError, TypeError):
                    parsed = False
                    break
            summary["sequence"] = {
                "timestamps_parsed": parsed, "expected_step_seconds": seconds,
                "non_increasing_steps": non_increasing if parsed else None,
                "irregular_steps": irregular if parsed else None,
                "basis": "returned_timestamps_only; exchange_breaks_can_cause_irregular_steps",
            }
        summaries[symbol] = summary
    return summaries
