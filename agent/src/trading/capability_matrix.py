"""Generate the broker capability matrix from the profile registry (#1626).

Render declared capabilities per profile into the marked README block.
The registry does not attest to successful runtime verification or enumerate
order kinds; the generated text explicitly preserves those limits. A CI drift
guard keeps the published declarations aligned with the registry.

Regenerate after touching connector profiles:

    PYTHONPATH=agent python -m src.trading.capability_matrix
"""

from __future__ import annotations

import re
from pathlib import Path

from src.trading.profiles import BUILTIN_PROFILES

README_PATH = Path(__file__).resolve().parents[3] / "README.md"
_BEGIN = "<!-- BEGIN GENERATED broker-capability-matrix -->"
_END = "<!-- END GENERATED broker-capability-matrix -->"

_HEADER = """Declared built-in profiles, generated from `agent/src/trading/profiles.py`.
Each row keeps its own environment and permissions; a paper order capability
never grants live trading. These are declarations, not successful runtime or
broker verification. Local plugins and user connection settings are excluded.

The quote column shows the declared transport, not a verified endpoint or
pricing coverage. Order kinds (market, limit, etc.) are not declared in the
registry and are therefore not inferred here. The placement column reports
the declared mandate requirement only; it does not attest to cancellation,
flattening, copy-trading, or other runtime guard coverage. Paper placement can
use a broker sandbox or local simulation. See each profile's notes and the
[broker bring-up checklist](CONTRIBUTING.md#broker-bring-up-checklist).

| Profile | Connector | Environment | Transport | Mode | Read capabilities | Quote path (declared) | Other capabilities | Placement requirement (declared) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""


def _cell(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in sorted(values)) or "none declared"


def render() -> str:
    """Render each built-in profile without merging its permissions with others."""
    lines = [_HEADER]
    for profile in sorted(BUILTIN_PROFILES, key=lambda p: (p.connector, p.id)):
        reads = [cap for cap in profile.capabilities if cap.endswith(".read")]
        other = [cap for cap in profile.capabilities if not cap.endswith(".read")]
        quote = profile.transport if "quotes.read" in profile.capabilities else "none declared"
        if profile.readonly:
            placement = "disabled (read-only)"
        elif "orders.place.requires_mandate" in profile.capabilities:
            placement = "mandate required"
        elif "orders.place" in profile.capabilities:
            placement = "no mandate declared"
        else:
            placement = "no placement declared"
        mode = "read-only" if profile.readonly else "write-enabled"
        lines.append(
            f"| `{profile.id}` | {profile.connector} | {profile.environment} | "
            f"{profile.transport} | {mode} | {_cell(reads)} | {quote} | "
            f"{_cell(other)} | {placement} |"
        )
    return "\n".join(lines) + "\n"


def render_block() -> str:
    return f"{_BEGIN}\n\n{render()}\n{_END}"


def sync_readme(readme: str) -> str:
    block = render_block()
    pattern = re.compile(re.escape(_BEGIN) + r".*?" + re.escape(_END), re.DOTALL)
    if readme.count(_BEGIN) != 1 or readme.count(_END) != 1 or not pattern.search(readme):
        raise ValueError(f"README must contain exactly one ordered {_BEGIN} marker block")
    return pattern.sub(lambda _: block, readme)


def main() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    README_PATH.write_text(sync_readme(text), encoding="utf-8")
    print(f"synced {README_PATH} ({len(BUILTIN_PROFILES)} profiles)")


if __name__ == "__main__":
    main()
