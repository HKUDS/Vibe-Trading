"""Persistable Chan-structure analysis for training snapshots.

The analyzer is deliberately incremental in its semantics: a fractal is only
published at ``confirmed_index`` (the first bar after the pivot), and every
API consumer filters objects by that index before exposing them to a live
training session.  This keeps the stored snapshot useful for review without
letting the live exercise see structures that were not confirmed yet.
"""

from __future__ import annotations

from typing import Any


ANALYSIS_VERSION = "chan-structure-v2"
MIN_FRACTAL_DISTANCE = 3


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _bar_index(item: dict[str, Any], fallback: int) -> int:
    value = item.get("bar_index", fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalise_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve Chan inclusion while retaining source extrema indices.

    A merged Chan bar is not a real market bar.  Keeping the source indices
    of its high and low prevents a later fractal from being drawn on the
    closing bar of an inclusion group when the actual extreme happened on a
    different source bar.
    """
    result: list[dict[str, Any]] = []
    direction = 0
    for raw_index, raw in enumerate(bars):
        current = {
            "bar_index": _bar_index(raw, raw_index),
            "source_start_index": _bar_index(raw, raw_index),
            "source_end_index": _bar_index(raw, raw_index),
            "high_index": _bar_index(raw, raw_index),
            "low_index": _bar_index(raw, raw_index),
            "open": _number(raw.get("open")),
            "high": _number(raw.get("high")),
            "low": _number(raw.get("low")),
            "close": _number(raw.get("close")),
        }
        if current["high"] < current["low"]:
            current["high"], current["low"] = current["low"], current["high"]
        if not result:
            result.append(current)
            continue
        previous = result[-1]
        contained = (current["high"] <= previous["high"] and current["low"] >= previous["low"]) or (
            current["high"] >= previous["high"] and current["low"] <= previous["low"]
        )
        if contained:
            if direction >= 0:
                if current["high"] >= previous["high"]:
                    previous["high"] = current["high"]
                    previous["high_index"] = current["high_index"]
                if current["low"] >= previous["low"]:
                    previous["low"] = current["low"]
                    previous["low_index"] = current["low_index"]
            else:
                if current["high"] <= previous["high"]:
                    previous["high"] = current["high"]
                    previous["high_index"] = current["high_index"]
                if current["low"] <= previous["low"]:
                    previous["low"] = current["low"]
                    previous["low_index"] = current["low_index"]
            previous["close"] = current["close"]
            previous["source_end_index"] = current["source_end_index"]
            continue
        direction = 1 if current["high"] > previous["high"] else -1
        result.append(current)
    return result


def _fractals(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index in range(1, len(bars) - 1):
        left, middle, right = bars[index - 1], bars[index], bars[index + 1]
        top = middle["high"] >= left["high"] and middle["high"] >= right["high"] and (
            middle["high"] > left["high"] or middle["high"] > right["high"]
        )
        bottom = middle["low"] <= left["low"] and middle["low"] <= right["low"] and (
            middle["low"] < left["low"] or middle["low"] < right["low"]
        )
        if top == bottom:
            continue
        points.append({
            "kind": "top" if top else "bottom",
            "bar_index": middle["high_index"] if top else middle["low_index"],
            "normalized_index": index,
            "confirmed_index": right["source_end_index"],
            "price": middle["high"] if top else middle["low"],
        })
    return points


def _alternating_fractals(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for point in points:
        if result and point["kind"] == result[-1]["kind"]:
            more_extreme = point["price"] > result[-1]["price"] if point["kind"] == "top" else point["price"] < result[-1]["price"]
            if more_extreme:
                result[-1] = point
            continue
        if result and point["normalized_index"] - result[-1]["normalized_index"] < MIN_FRACTAL_DISTANCE:
            continue
        result.append(point)
    return result


def _strokes(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index in range(1, len(points)):
        start, end = points[index - 1], points[index]
        if start["kind"] == end["kind"] or end["normalized_index"] - start["normalized_index"] < MIN_FRACTAL_DISTANCE:
            continue
        result.append({
            "stroke_index": len(result),
            "start_fractal_index": index - 1,
            "end_fractal_index": index,
            "start_index": start["bar_index"],
            "end_index": end["bar_index"],
            "start_price": start["price"],
            "end_price": end["price"],
            "direction": "up" if start["kind"] == "bottom" else "down",
            "high": max(start["price"], end["price"]),
            "low": min(start["price"], end["price"]),
            "confirmed_index": end["confirmed_index"],
        })
    return result


def _segments(strokes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build segments from valid three-stroke seeds and stroke breaks.

    A segment starts only when its first three strokes overlap and the first
    and third strokes point in the same direction.  It is extended by later
    same-direction strokes only while each new swing makes a fresh extreme;
    the first failed extension closes the segment.  This avoids the former
    fixed ``range(..., 2)`` grouping, which could label unrelated strokes as
    one segment.
    """
    result: list[dict[str, Any]] = []
    start = 0
    while start + 2 < len(strokes):
        first, middle, third = strokes[start:start + 3]
        if first["direction"] != third["direction"]:
            start += 1
            continue
        seed_high = min(first["high"], middle["high"], third["high"])
        seed_low = max(first["low"], middle["low"], third["low"])
        if seed_low >= seed_high:
            start += 1
            continue

        end = start + 2
        direction = first["direction"]
        while end + 2 < len(strokes):
            candidate = strokes[end + 2]
            if candidate["direction"] != direction:
                break
            extends = candidate["end_price"] > strokes[end]["end_price"] if direction == "up" else candidate["end_price"] < strokes[end]["end_price"]
            if not extends:
                break
            end += 2

        group = strokes[start:end + 1]
        result.append({
            "stroke_start_index": start,
            "stroke_end_index": end,
            "start_index": group[0]["start_index"],
            "end_index": group[-1]["end_index"],
            "start_price": group[0]["start_price"],
            "end_price": group[-1]["end_price"],
            "direction": direction,
            "high": max(item["high"] for item in group),
            "low": min(item["low"] for item in group),
            "confirmed_index": max(item["confirmed_index"] for item in group),
        })
        start = end + 1
    return result


def _centers(strokes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find and extend non-duplicated centres from three consecutive strokes."""
    candidates: list[dict[str, Any]] = []
    for index in range(len(strokes) - 2):
        window = strokes[index:index + 3]
        high = min(item["high"] for item in window)
        low = max(item["low"] for item in window)
        if low >= high:
            continue
        end = index + 2
        while end + 1 < len(strokes):
            following = strokes[end + 1]
            next_high = min(high, following["high"])
            next_low = max(low, following["low"])
            if next_low >= next_high:
                break
            high, low = next_high, next_low
            end += 1
        candidates.append({
            "stroke_start_index": index,
            "stroke_end_index": end,
            "start_index": strokes[index]["start_index"],
            "end_index": strokes[end]["end_index"],
            "high": high,
            "low": low,
            "confirmed_index": max(item["confirmed_index"] for item in strokes[index:end + 1]),
        })

    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if not result:
            result.append(candidate)
            continue
        previous = result[-1]
        overlaps = max(previous["low"], candidate["low"]) < min(previous["high"], candidate["high"])
        touches = candidate["stroke_start_index"] <= previous["stroke_end_index"] + 1
        if not (overlaps and touches):
            result.append(candidate)
            continue
        previous["stroke_end_index"] = max(previous["stroke_end_index"], candidate["stroke_end_index"])
        previous["end_index"] = strokes[previous["stroke_end_index"]]["end_index"]
        previous["high"] = min(previous["high"], candidate["high"])
        previous["low"] = max(previous["low"], candidate["low"])
        previous["confirmed_index"] = max(previous["confirmed_index"], candidate["confirmed_index"])
    return result


def _signals(strokes: list[dict[str, Any]], centers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create structural second/third buy and sell points.

    A signal is emitted only after a confirmed centre exit and its first
    retracement.  A retracement that stays outside the centre is a third
    class point; one that returns into the centre without breaking it is a
    second class point.  No signal is emitted when the exit/retracement pair
    is incomplete.
    """
    result: list[dict[str, Any]] = []
    for center in centers:
        exit_index = center["stroke_end_index"] + 1
        retrace_index = exit_index + 1
        if retrace_index >= len(strokes):
            continue
        exit_stroke = strokes[exit_index]
        retrace = strokes[retrace_index]
        if exit_stroke["direction"] == "up" and retrace["direction"] == "down":
            if retrace["low"] > center["high"]:
                label = "B3"
            elif retrace["low"] >= center["low"]:
                label = "B2"
            else:
                continue
        elif exit_stroke["direction"] == "down" and retrace["direction"] == "up":
            if retrace["high"] < center["low"]:
                label = "S3"
            elif retrace["high"] <= center["high"]:
                label = "S2"
            else:
                continue
        else:
            continue
        result.append({
            "label": label,
            "side": "buy" if label.startswith("B") else "sell",
            "bar_index": retrace["end_index"],
            "price": retrace["end_price"],
            "confirmed_index": retrace["confirmed_index"],
            "center_start_index": center["start_index"],
            "center_end_index": center["end_index"],
        })
    return result


def build_chan_analysis(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the immutable analysis snapshot for one session's bars."""
    normalised = _normalise_bars(bars)
    fractals = _alternating_fractals(_fractals(normalised))
    strokes = _strokes(fractals)
    centers = _centers(strokes)
    return {
        "version": ANALYSIS_VERSION,
        "fractals": fractals,
        "strokes": strokes,
        "segments": _segments(strokes),
        "centers": centers,
        "signals": _signals(strokes, centers),
    }


def filter_chan_analysis(analysis: dict[str, Any], max_index: int) -> dict[str, Any]:
    """Return only structures confirmed by the current training cursor."""
    result: dict[str, Any] = {"version": analysis.get("version", ANALYSIS_VERSION)}
    for key in ("fractals", "strokes", "segments", "centers", "signals"):
        values = analysis.get(key, [])
        result[key] = [
            item for item in values
            if int(item.get("confirmed_index", max_index + 1)) <= max_index
            and int(item.get("bar_index", item.get("end_index", 0))) <= max_index
        ]
    return result
