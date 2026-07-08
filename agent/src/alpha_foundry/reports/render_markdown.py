from __future__ import annotations

from src.alpha_foundry.reports.model import AlphaGenesisReport


def render_markdown(report: AlphaGenesisReport) -> str:
    payload = report.to_dict()
    lines = [
        f"# Alpha Genesis Report: {payload['candidate_id']}",
        "",
        f"- report_id: {payload['report_id']}",
        f"- decision: {payload['decision']}",
        f"- hard_failures: {', '.join(payload['hard_failures']) or 'none'}",
        f"- warnings: {', '.join(payload['warnings']) or 'none'}",
        f"- trial_count: {payload['trial_count']}",
        "",
        "## Evidence",
        "",
        f"- data_snapshot_hash: {payload.get('data_snapshot_hash') or 'unknown'}",
        f"- pit_contract_present: {payload.get('pit_contract_present')}",
        f"- survivorship_bias: {payload.get('survivorship_bias')}",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["limitations"])
    lines.append("")
    lines.append("## Non Goals")
    lines.append("")
    lines.extend(f"- {item}" for item in payload["non_goals"])
    lines.append("")
    return "\n".join(lines)
