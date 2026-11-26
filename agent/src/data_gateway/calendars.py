"""Bounded exchange-session validation; no retained calendar/minute cache."""

from datetime import timedelta
from importlib import import_module
import json
from pathlib import Path

_POLICY = json.loads(Path(__file__).with_name("calendars.json").read_text())


class CalendarCoverageError(ValueError):
    """Observed timestamps do not match the requested exchange grid."""


def schedule(market, start, end):
    """Build just the requested session range without global factory caching.

    Args:
        market: A market with a declared calendar in calendars.json.
        start: Inclusive local session date.
        end: Inclusive local session date.

    Returns:
        Calendar name, exchange timezone and schedule, or None if unsupported.
    """
    name = _POLICY["markets"].get(market)
    if name is None:
        return None
    import pandas as pd

    module = import_module(f"exchange_calendars.exchange_calendar_{name.lower()}")
    calendar_type = getattr(module, f"{name}ExchangeCalendar")
    lower, upper = pd.Timestamp(start), pd.Timestamp(end)
    # Padding permits an all-weekend/holiday request; never create the default
    # multi-decade calendar or its materialized all-minutes property.
    calendar = calendar_type(start=lower - timedelta(days=7), end=upper + timedelta(days=7), side="left")
    return name, str(calendar.tz), calendar.schedule.loc[start:end].copy()


def validate(rows, market, start, end, interval, provenance, *, prepared=None):
    """Check every session/bar, exposing any excluded non-trading close points.

    Args:
        rows: Unsampled records with trade_date or time, ordered and unique.
        market: Declared market identity, never guessed from price values.
        start: Inclusive local session date.
        end: Inclusive local session date.
        interval: Case-sensitive bar interval.
        provenance: Source and observed timestamp timezone/basis metadata.
        prepared: Optional schedule owned by the current request, never global.

    Returns:
        Kept rows and coverage metadata. Unsupported calendars or unknown
        intraday timestamp semantics remain explicitly unverified.

    Raises:
        CalendarCoverageError: Missing, duplicate or unexpected session bars.
    """
    found = prepared if prepared is not None else schedule(market, start, end)
    if found is None:
        return rows, {"coverage_verified": False, "coverage": "calendar_unavailable"}
    import exchange_calendars
    import pandas as pd

    name, exchange_zone, frame = found
    meta = {
        "calendar": name,
        "calendar_version": exchange_calendars.__version__,
        "exchange_timezone": exchange_zone,
        "sessions": len(frame),
        "coverage_verified": False,
        "coverage": "exchange_calendar_grid",
    }
    raw = [row.get("trade_date", row.get("time")) for row in rows]
    excluded = []
    kept = list(rows)
    if interval in {"1D", "1W", "1M"}:
        expected = frame.index
        if interval != "1D" and len(expected):
            # Production resampling stamps the final requested session in each
            # week/month, including a partial boundary period.
            periods = expected.to_period("W-SUN" if interval == "1W" else "M")
            expected = expected[~periods.duplicated(keep="last")]
        expected_values = list(expected.strftime("%Y-%m-%d"))
        observed = [str(value)[:10] for value in raw]
        meta.update(timestamp_basis="session_date", timezone=exchange_zone)
    else:
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60}.get(interval)
        semantics = {**_POLICY["legacy_intraday_sources"].get(provenance.get("source"), {}), **provenance}
        zone, basis = semantics.get("timezone"), semantics.get("timestamp_basis")
        if minutes is None or not zone or zone == "source_timezone_unverified" or basis != "bar_open":
            return rows, {**meta, "coverage": "source_timestamp_semantics_unverified"}
        expected_values = []
        close_points = set()
        for _, session in frame.iterrows():
            close_points.add(session["close"])
            if pd.isna(session["break_start"]):
                segments = [(session["open"], session["close"])]
            else:
                segments = [(session["open"], session["break_start"]), (session["break_end"], session["close"])]
            for left, right in segments:
                expected_values.extend(pd.date_range(left, right, freq=f"{minutes}min", inclusive="left"))
        expected_set = set(expected_values)
        observed, kept = [], []
        for row, value in zip(rows, raw):
            stamp = pd.Timestamp(value)
            stamp = stamp.tz_localize(zone) if stamp.tzinfo is None else stamp
            stamp = stamp.tz_convert("UTC")
            if (
                stamp not in expected_set
                and stamp in close_points
                and provenance.get("source") in _POLICY["close_point_sources"]
                and row.get("volume") == 0
                and row.get("open") == row.get("high") == row.get("low") == row.get("close")
            ):
                excluded.append({"time": str(value), "reason": "zero_volume_point_at_session_close_not_a_bar_open"})
                continue
            observed.append(stamp)
            kept.append(row)
        meta.update(timestamp_basis="bar_open", timezone=zone)
    missing = set(expected_values) - set(observed)
    extra = set(observed) - set(expected_values)
    if missing or extra or len(observed) != len(set(observed)):
        raise CalendarCoverageError(
            f"{name} calendar grid mismatch: missing={len(missing)}, extra={len(extra)}, "
            f"duplicates={len(observed) - len(set(observed))}; "
            f"missing_sample={[str(v) for v in sorted(missing)[:3]]}; "
            f"extra_sample={[str(v) for v in sorted(extra)[:3]]}"
        )
    meta.update(coverage_verified=True, expected_rows=len(expected_values), excluded_source_points=excluded)
    return kept, meta
