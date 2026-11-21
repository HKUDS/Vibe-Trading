"""Sourced corrections to the library's HKEX historical session schedule.

These are observed exceptions, not an exhaustive weather-event reconstruction.
Since 2024-09-23 ordinary severe weather no longer implies a market closure:
https://www.hkex.com.hk/News/Market-Communications/2024/240618news?sc_lang=en
"""

import pandas as pd

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
    frame = frame.drop(index=pd.DatetimeIndex(FULL_CLOSURES), errors="ignore").copy()
    for day, (opening, _source) in LATE_OPENS.items():
        stamp = pd.Timestamp(day)
        if stamp in frame.index:
            frame.loc[stamp, "open"] = pd.Timestamp(
                f"{day} {opening}", tz="Asia/Hong_Kong"
            ).tz_convert("UTC")
            frame.loc[stamp, ["break_start", "break_end"]] = pd.NaT
    return frame
