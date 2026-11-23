"""Sourced corrections to the library's HKEX historical session schedule.

These are observed exceptions, not an exhaustive weather-event reconstruction.
Since 2024-09-23 ordinary severe weather no longer implies a market closure:
https://www.hkex.com.hk/News/Market-Communications/2024/240618news?sc_lang=en
"""

import pandas as pd

WEATHER_REFORM = pd.Timestamp("2024-09-23")

# HKEX explicitly cancelled every securities session on these dates.
FULL_CLOSURES = {
    "2016-08-02": "https://www.hkex.com.hk/News/Market-Communications/2016/1608022news?sc_lang=en",
    "2016-10-21": "https://www.hkex.com.hk/News/Market-Communications/2016/1610212news?sc_lang=en",
    "2017-08-23": "https://www.hkex.com.hk/news/market-communications/2017/1708232news?sc_lang=en",
    "2023-07-17": "https://www.hkex.com.hk/News/Market-Communications/2023/2307172news?sc_lang=en",
    "2023-09-01": "https://www.hkex.com.hk/News/Market-Communications/2023/2309012news?sc_lang=en",
    "2023-09-08": "https://www.hkex.com.hk/News/Market-Communications/2023/2309083news?sc_lang=en",
}
# Official Stock Connect notice: resumed at 14:00 HKT, after the normal lunch.
LATE_OPENS = {
    "2023-10-09": (
        "14:00",
        "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20231009_5727317.shtml",
    ),
}


def apply_weather_overrides(frame: pd.DataFrame) -> pd.DataFrame:
    """Correct known pre-reform dates without inferring closures from weather."""
    historical = [day for day in FULL_CLOSURES if pd.Timestamp(day) < WEATHER_REFORM]
    frame = frame.drop(index=pd.DatetimeIndex(historical), errors="ignore").copy()
    for day, (opening, _source) in LATE_OPENS.items():
        stamp = pd.Timestamp(day)
        if stamp < WEATHER_REFORM and stamp in frame.index:
            frame.loc[stamp, "open"] = pd.Timestamp(
                f"{day} {opening}", tz="Asia/Hong_Kong"
            ).tz_convert("UTC")
            frame.loc[stamp, ["break_start", "break_end"]] = pd.NaT
    return frame


def weather_closure_inventory() -> list[dict]:
    """Return the small sourced historical date/session exception table."""
    records = [
        {"date": day, "session": "full", "source": source}
        for day, source in FULL_CLOSURES.items()
        if pd.Timestamp(day) < WEATHER_REFORM
    ]
    records.extend(
        {
            "date": day,
            "session": "morning",
            "reopens_hkt": opening,
            "detail": "Morning suspended; afternoon resumes at the stated time",
            "source": source,
        }
        for day, (opening, source) in LATE_OPENS.items()
        if pd.Timestamp(day) < WEATHER_REFORM
    )
    return sorted(records, key=lambda value: value["date"])


def audit_hsi_session_coverage(
    hsi_daily: pd.DataFrame,
    start: str,
    end: str,
    *,
    provenance: dict,
) -> dict:
    """Reconcile daily ^HSI bars with sourced sessions without hiding data gaps.

    A missing pre-reform benchmark bar is a closure candidate, not proof that
    the exchange closed: it can also mean a failed provider request. Known
    sourced exceptions are excluded by the calendar. Additional candidates
    remain explicitly unverified until a dated closure source is supplied.
    Post-reform missing bars are data gaps, never automatic weather closures.
    """
    from src.data_gateway.calendars import schedule

    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("HSI coverage requires the daily loader's provenance")
    if "close" not in hsi_daily:
        raise ValueError("HSI daily observations require close prices")
    days = pd.DatetimeIndex(hsi_daily.index)
    if days.hasnans or days.has_duplicates:
        raise ValueError("HSI daily labels must be valid and unique")
    if days.tz is not None:
        days = days.tz_convert("Asia/Hong_Kong").tz_localize(None)
    days = days.normalize()
    if days.has_duplicates:
        raise ValueError("HSI daily labels must identify unique sessions")
    valid = pd.to_numeric(hsi_daily["close"], errors="coerce")
    observed = days[(valid.gt(0) & valid.lt(float("inf"))).to_numpy()]
    observed = observed[
        (observed >= pd.Timestamp(start)) & (observed <= pd.Timestamp(end))
    ]
    expected = schedule("hk_equity", start, end)[2].index
    missing = expected.difference(observed)
    pre = missing[missing < WEATHER_REFORM]
    post = missing[missing >= WEATHER_REFORM]
    extra = observed.difference(expected)
    return {
        "symbol": "^HSI",
        "source": dict(provenance),
        "coverage_verified": len(missing) == 0 and len(extra) == 0,
        "unverified_pre_reform_closure_candidates": list(pre.strftime("%Y-%m-%d")),
        "post_reform_data_gaps": list(post.strftime("%Y-%m-%d")),
        "unexpected_benchmark_sessions": list(extra.strftime("%Y-%m-%d")),
        "sourced_weather_exceptions": weather_closure_inventory(),
    }
