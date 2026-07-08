from __future__ import annotations

import html
import re

from src.alpha_foundry.reports.model import AlphaGenesisReport


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKDOWN_META_CHARS_RE = re.compile(r"([\\`*_{}\[\]<>()#.!])")
_DANGEROUS_URI_SCHEME_RE = re.compile(r"(?i)\b(javascript|vbscript|data)\s*:")


def _safe_markdown_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = _CONTROL_CHARS_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _DANGEROUS_URI_SCHEME_RE.sub(lambda m: f"{m.group(1)}\\:", text)
    escaped = html.escape(text, quote=True)
    return _MARKDOWN_META_CHARS_RE.sub(r"\\\1", escaped)


def _safe_csv(values: list[object]) -> str:
    rendered = ", ".join(_safe_markdown_text(value) for value in values if str(value))
    return rendered or "none"


def render_markdown(report: AlphaGenesisReport) -> str:
    payload = report.to_dict()
    lines = [
        f"# Alpha Genesis Report: {_safe_markdown_text(payload['candidate_id'])}",
        "",
        f"- report_id: {_safe_markdown_text(payload['report_id'])}",
        f"- decision: {_safe_markdown_text(payload['decision'])}",
        f"- hard_failures: {_safe_csv(payload['hard_failures'])}",
        f"- warnings: {_safe_csv(payload['warnings'])}",
        f"- trial_count: {_safe_markdown_text(payload['trial_count'])}",
        "",
        "## Evidence",
        "",
        f"- data_snapshot_hash: {_safe_markdown_text(payload.get('data_snapshot_hash') or 'unknown')}",
        f"- pit_contract_present: {_safe_markdown_text(payload.get('pit_contract_present'))}",
        f"- survivorship_bias: {_safe_markdown_text(payload.get('survivorship_bias'))}",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {_safe_markdown_text(item)}" for item in payload["limitations"])
    lines.append("")
    lines.append("## Non Goals")
    lines.append("")
    lines.extend(f"- {_safe_markdown_text(item)}" for item in payload["non_goals"])
    lines.append("")
    return "\n".join(lines)
