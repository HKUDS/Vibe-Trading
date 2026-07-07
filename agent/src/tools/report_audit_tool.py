"""Agent tool: research-report data audit (extract → verify → verdict).

A ``BaseTool`` wrapper around the report-audit routines that guard published
research against hallucinated numbers. Auto-discovered and registered via
``BaseTool.__subclasses__()``.

Two-phase quality gate:

1. ``extract`` — parse a markdown report, collect its numeric data points
   (tables, ``label: value`` lines, ``亿 / 万亿 / x / 倍 / %`` units), and
   draw a random sample (default 15%, clamped to [3, 30]).
2. ``verdict`` — compare each sampled point's reported value against one or two
   authoritative fetched values at a 1% tolerance; a single failed point fails
   the whole report, mixed results warn.

The tool takes text/results only — it does not fetch data itself. Pair it with
market-data / financial-statement tools: read the report, extract here, fetch
there, then verdict here. Read-only: returns JSON, writes nothing.
"""

from __future__ import annotations

import json
import math
import re
from random import Random
from typing import Any

from src.agent.tools import BaseTool

# ---------------------------------------------------------------------------
# Markdown data-point extraction (handles Chinese financial reports)
# ---------------------------------------------------------------------------

_KV_LABEL_RE = re.compile(
    r"(?P<label>[一-龥A-Za-z][^|\n：:*]{1,30})[：:]\s*[~约]?\$?"
    r"(?P<num>[\d,，.]+)\s*"
    r"(?P<unit>亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?"
)

_NUMUNIT_RE = re.compile(r"[~约]?\$?([\d,，.]+)\s*(亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?")
_TABLE_SEP_RE = re.compile(r"^\|[\-\s|:]+\|$")

_SKIP_LABELS = {
    "来源", "sources", "source", "说明", "注意", "备注", "数据来源",
    "n/a", "—", "-", "/", "合计", "total", "单位", "趋势",
}

_QUARTER_RE = re.compile(r"(20\d{2}|Q[1-4]|\d{4}\s*Q[1-4])")


def _clean_num(s: str) -> float | None:
    """Normalise a numeric string with commas (ASCII or wide) to float."""
    s = s.replace(",", "").replace("，", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _is_valid_label(label: str) -> bool:
    """True if a label looks like a meaningful financial field name."""
    label = label.strip()
    if len(label) < 2:
        return False
    if re.fullmatch(r"[\d\s年季度Q]+", label):
        return False
    if re.match(r"^[+\-*#|~$>_`]", label):
        return False
    if "**" in label or "`" in label or "__" in label:
        return False
    if re.fullmatch(r"[+-]?\d+(\.\d+)?%", label):
        return False
    if label.lower() in _SKIP_LABELS:
        return False
    return True


def _parse_md_tables(lines: list[str]) -> list[tuple[str, str, float, str, int, str]]:
    """Parse markdown tables into (row_label, col_header, value, unit, lineno, raw)."""
    results: list[tuple[str, str, float, str, int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "|" in line and not _TABLE_SEP_RE.match(line):
            headers_raw = [h.strip().strip("*_").strip() for h in line.split("|")]
            headers_raw = [h for h in headers_raw if h]
            if i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1].strip()):
                i += 2  # skip the separator row
                while i < len(lines):
                    dline = lines[i].strip()
                    if not dline or not dline.startswith("|"):
                        break
                    cells = [c.strip().strip("*_~").strip() for c in dline.split("|")]
                    cells = [c for c in cells if c != ""]
                    if len(cells) < 2:
                        i += 1
                        continue
                    row_label = cells[0]
                    for col_idx, cell in enumerate(cells[1:], start=1):
                        col_header = (
                            headers_raw[col_idx]
                            if col_idx < len(headers_raw)
                            else f"col{col_idx}"
                        )
                        m = _NUMUNIT_RE.search(cell)
                        if m:
                            val = _clean_num(m.group(1))
                            unit = (m.group(2) or "").strip()
                            if val and val != 0 and val < 1e15:
                                results.append((row_label, col_header, val, unit, i + 1, dline))
                    i += 1
                continue
        i += 1
    return results


def extract_data_points(md_text: str) -> list[dict[str, Any]]:
    """Extract recognizable financial data points from a markdown report.

    Covers multi-column tables and ``label: value unit`` lines. De-duplicates
    by (label, value, unit).

    Args:
        md_text: Full markdown text of the report.

    Returns:
        List of point dicts: ``{id, label, reported_value, unit, raw_text,
        line_number}``.
    """
    points: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(label: str, val: float | None, unit: str, lineno: int, raw: str) -> None:
        label = re.sub(r"[*_`]+", "", label).strip()
        if not _is_valid_label(label):
            return
        if val is None or val == 0 or val > 1e15:
            return
        if _QUARTER_RE.fullmatch(label.strip()):
            return
        key = f"{label}|{round(val, 4)}|{unit}"
        if key in seen:
            return
        seen.add(key)
        points.append({
            "id": len(points) + 1,
            "label": label,
            "reported_value": val,
            "unit": unit,
            "raw_text": raw[:120],
            "line_number": lineno,
        })

    lines = md_text.split("\n")
    in_code = False

    # 1. Multi-column tables.
    _YOY_HEADERS = {"YOY", "YOY增速", "增速", "同比", "变化", "趋势", "说明", "备注"}
    for row_label, col_header, val, unit, lineno, raw in _parse_md_tables(lines):
        if not _is_valid_label(row_label):
            continue
        if col_header.upper() in _YOY_HEADERS:
            continue
        label = f"{row_label} · {col_header}" if (col_header and col_header != row_label) else row_label
        _add(label, val, unit, lineno, raw)

    # 2. ``label: value unit`` lines.
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith("> ") or re.match(r"^#{1,6}\s", stripped):
            continue
        if "|" in stripped:
            continue  # handled as a table above
        for m in _KV_LABEL_RE.finditer(stripped):
            _add(
                m.group("label"),
                _clean_num(m.group("num")),
                (m.group("unit") or "").strip(),
                lineno,
                stripped,
            )

    return points


def sample_points(
    points: list[dict[str, Any]], ratio: float = 0.15, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Draw a random sample, clamped to [3, 30], ordered by line number.

    Args:
        points: Data points returned by :func:`extract_data_points`.
        ratio: Sampling fraction.
        seed: Optional seed for reproducibility.

    Returns:
        Sampled points sorted by ``line_number``.
    """
    n = max(3, min(30, math.ceil(len(points) * ratio)))
    n = min(n, len(points))
    if n == 0:
        return []
    rng = Random(seed)
    sampled = rng.sample(points, n)
    return sorted(sampled, key=lambda p: p["line_number"])


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

_TOLERANCE = 0.01  # 1% absolute relative tolerance


def _pct_diff(reported: float, fetched: float) -> float:
    """Absolute relative percent difference (inf when reported is 0 and fetched isn't)."""
    if reported == 0:
        return 0.0 if fetched == 0 else float("inf")
    return abs(reported - fetched) / abs(reported)


def render_verdict(results: list[dict[str, Any]], report_name: str = "") -> dict[str, Any]:
    """Render a PASS/FAIL verdict from per-point verification results.

    Each result with a ``fetched_value`` is judged against the reported value
    at :data:`_TOLERANCE`. A second source (``fetched_value2``) may be supplied;
    both sources must pass for a point to pass, both fail to fail, otherwise the
    point warns (treated as a caliber mismatch, not a failure).

    Args:
        results: List of verification objects — ``{id, label, reported_value,
            unit, fetched_value, fetched_source, (optional) fetched_value2,
            fetched_source2, ...}``.
        report_name: Optional report name for display.

    Returns:
        Verdict dict: ``verdict`` is ``PASS`` (zero failures) or ``FAIL``.
    """
    fail_items: list[dict[str, Any]] = []
    warn_items: list[dict[str, Any]] = []
    pass_count = 0
    total = 0

    for item in results:
        fetched = item.get("fetched_value")
        if fetched is None:
            continue  # not verified — skip, do not count
        total += 1
        reported = float(item.get("reported_value", 0))
        label = item.get("label", "?")
        unit = item.get("unit", "")
        source = item.get("fetched_source", "?")
        fetched = float(fetched)
        diff1 = _pct_diff(reported, fetched)

        fetched2 = item.get("fetched_value2")
        source2 = item.get("fetched_source2", "")
        pass1 = diff1 <= _TOLERANCE

        if fetched2 is None:
            # Single source: pass or fail outright.
            if pass1:
                pass_count += 1
            else:
                fail_items.append({
                    "id": item.get("id"), "label": label,
                    "reported": reported, "unit": unit,
                    "fetched": fetched, "source": source,
                    "fetched2": None, "source2": source2,
                    "diff1_pct": round(diff1 * 100, 2), "diff2_pct": None,
                    "raw_text": item.get("raw_text", ""),
                    "line_number": item.get("line_number", 0),
                })
        else:
            # Two sources: PASS only if both agree within tolerance; FAIL if
            # both miss; otherwise WARN (a caliber / GAAP mismatch, not a fail).
            f2 = float(fetched2)
            diff2 = _pct_diff(reported, f2)
            pass2 = diff2 <= _TOLERANCE
            if pass1 and pass2:
                pass_count += 1
            elif not pass1 and not pass2:
                fail_items.append({
                    "id": item.get("id"), "label": label,
                    "reported": reported, "unit": unit,
                    "fetched": fetched, "source": source,
                    "fetched2": f2, "source2": source2,
                    "diff1_pct": round(diff1 * 100, 2),
                    "diff2_pct": round(diff2 * 100, 2),
                    "raw_text": item.get("raw_text", ""),
                    "line_number": item.get("line_number", 0),
                })
            else:
                warn_items.append({
                    "id": item.get("id"), "label": label,
                    "reported": reported, "unit": unit,
                    "diff1_pct": round(diff1 * 100, 2),
                    "diff2_pct": round(diff2 * 100, 2),
                })

    fail_count = len(fail_items)
    verdict = "PASS" if fail_count == 0 else "FAIL"
    return {
        "verdict": verdict,
        "report_name": report_name,
        "total": total,
        "pass_count": pass_count,
        "warn_count": len(warn_items),
        "fail_count": fail_count,
        "fail_items": fail_items,
        "warn_items": warn_items,
    }


class ReportAuditTool(BaseTool):
    """Research-report data audit gate (extract sample → verdict)."""

    name = "report_audit"
    description = (
        "Audit a research report's numeric data points for accuracy before "
        "publishing. Two sub-commands via `command`: 'extract' parses a "
        "markdown report and returns a random sample (~15%, clamped 3-30) of "
        "its financial data points to verify; 'verdict' compares each sampled "
        "point's reported value against one or two authoritative fetched values "
        "at 1% tolerance and returns a PASS/FAIL gate (one failure fails the "
        "report). Workflow: read the report, extract here, verify each sample "
        "point against market-data/financial-statement tools, then verdict here."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["extract", "verdict"],
                "description": "Which audit phase to run.",
            },
            "report_text": {
                "type": "string",
                "description": "extract: full markdown text of the report to audit.",
            },
            "ratio": {
                "type": "number", "default": 0.15,
                "description": "extract: fraction of data points to sample.",
            },
            "seed": {
                "type": "integer",
                "description": "extract: random seed for reproducible sampling.",
            },
            "results": {
                "type": "array", "items": {"type": "object"},
                "description": "verdict: list of {id, label, reported_value, unit, "
                               "fetched_value, fetched_source, (optional) "
                               "fetched_value2, fetched_source2}.",
            },
            "report_name": {
                "type": "string",
                "description": "verdict: report name for display.",
            },
        },
        "required": ["command"],
    }
    is_readonly = True
    repeatable = True  # loop.py dedups non-repeatable tools by name; extract
                       # and verdict are commonly called back-to-back.

    def execute(self, **kwargs: Any) -> str:
        """Dispatch to ``extract`` or ``verdict`` and return a JSON envelope.

        Args:
            **kwargs: ``command`` plus the inputs for that phase.

        Returns:
            JSON string — ``status="ok"`` with the result on success,
            ``status="error"`` with a message otherwise.
        """
        command = str(kwargs.get("command") or "").strip()
        try:
            if command == "extract":
                report_text = kwargs.get("report_text")
                if not isinstance(report_text, str) or not report_text.strip():
                    return _err("report_text (non-empty markdown) is required for extract")
                ratio = float(kwargs.get("ratio") or 0.15)
                seed = kwargs.get("seed")
                seed = int(seed) if seed is not None else None
                points = extract_data_points(report_text)
                sampled = sample_points(points, ratio=ratio, seed=seed)
                result: dict[str, Any] = {
                    "total_extracted": len(points),
                    "sample_size": len(sampled),
                    "ratio": ratio,
                    "seed": seed,
                    "sample": sampled,
                    "hint": (
                        "For each point in `sample`, fetch its value from an "
                        "authoritative source, then call the 'verdict' command "
                        "with results=[{id, reported_value, fetched_value, "
                        "fetched_source, ...}]."
                    ),
                }
            elif command == "verdict":
                results = kwargs.get("results")
                if not isinstance(results, list) or not results:
                    return _err("results (non-empty list) is required for verdict")
                result = render_verdict(
                    results, report_name=str(kwargs.get("report_name") or ""),
                )
            else:
                return _err(f"unknown command: {command}")
        except Exception as exc:  # noqa: BLE001 - surface a clean tool error
            return json.dumps(
                {"status": "error", "command": command, "error": str(exc)},
                ensure_ascii=False,
            )
        return json.dumps(
            {"status": "ok", "command": command, **result}, ensure_ascii=False,
        )


def _err(msg: str) -> str:
    return json.dumps({"status": "error", "error": msg}, ensure_ascii=False)
