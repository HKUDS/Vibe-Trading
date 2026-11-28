"""Verified numeric evidence retained when summarizing a turn."""
import json


def _verification_ledger(messages: list) -> str:
    """Extract terse deterministic-verification records from a message list."""
    lines: list[str] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except Exception:  # noqa: BLE001 - non-JSON results are skipped
            continue
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            continue
        command = payload.get("command")
        if command == "calc" and payload.get("result_exact") is not None:
            expr = payload.get("expr", "?")
            result_exact = payload.get("result_exact")
            lines.append(f"calc {expr} = {result_exact}")
        elif command == "verify_market_cap" and payload.get("verdict") is not None:
            verdict = payload.get("verdict")
            deviation_pct = payload.get("deviation_pct")
            lines.append(f"market_cap verdict={verdict} dev={deviation_pct}%")
        elif command == "verify_valuation" and payload.get("metrics"):
            metrics = payload["metrics"]
            if isinstance(metrics, dict) and metrics:
                summary = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:8])
                lines.append(f"valuation {summary}")
        elif command == "cross_validate" and payload.get("all_consistent") is not None:
            field_name = payload.get("field", "?")
            all_consistent = payload.get("all_consistent")
            lines.append(f"cross_validate field={field_name} consistent={all_consistent}")
        elif command == "benford" and payload.get("reliable") is not None:
            reliable = payload.get("reliable")
            conformity = payload.get("conformity", "?")
            lines.append(f"benford reliable={reliable} conformity={conformity}")
    return "\n".join(list(dict.fromkeys(lines))[:60])
